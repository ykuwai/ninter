#!/usr/bin/env python3
"""
Ninter variable fonts (wght 100 to 900), built next to the static TTFs.

The static faces stay the main deliverable. This script reuses build.py to make the
nine weights of each style as masters, then joins them with fontTools.varLib into one
variable font per family and style:

    build/variable/NinterVariable.ttf          Ninter Variable, roman
    build/variable/NinterVariable-Italic.ttf   Ninter Variable, italic
    build/variable/NinterPVariable.ttf         Ninter P Variable, roman
    build/variable/NinterPVariable-Italic.ttf  Ninter P Variable, italic

How the axis is laid out
  Noto Sans JP is a two-master font (100 and 900) with an avar curve. The design axis
  here reuses that curve, so every Noto glyph is a straight line in design space and
  needs only the 100, 400 and 900 masters. Inter's weights are mapped per weight
  (inter_weights in ninter.config.json) and are not linear, so Latin glyphs keep all
  nine masters. A glyph keeps only the masters it needs to stay within OUTLINE_TOL
  units (ITALIC_OUTLINE_TOL for the italics) of every static weight with exactly the
  same advance (sparse masters).

  From Bold up, Noto's palt and vpal add a lookup (a GPOS FeatureVariations record in
  Noto). The plain Ninter statics keep that, so the variable font switches the same
  lookups on at the same point of the axis.

Glyph set
  A variable font needs the same glyphs at every weight. build.py already gives every
  face the same set: it decides which oversized Inter symbols go to Noto once, at the
  lightest Inter weight (oversized_inter_symbols), so the masters are the static faces
  as they are. assemble() still stops if two masters differ in glyph order, cmap, GSUB
  or GDEF.

Usage
    python scripts/build_variable.py                       # all four files
    python scripts/build_variable.py --only-variant "Ninter P" --upright-only
    python scripts/build_variable.py --masters-dir /tmp/m --keep-masters
    python scripts/build_variable.py --masters-dir /tmp/m --skip-masters  # reuse masters

The masters are built into a temporary folder, never into build/.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402
from fontTools.designspaceLib import (  # noqa: E402
    AxisDescriptor, DesignSpaceDocument, InstanceDescriptor, SourceDescriptor)
from fontTools.otlLib.builder import buildStatTable  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.ttLib.tables._g_l_y_f import Glyph  # noqa: E402
from fontTools.varLib import build as varlib_build  # noqa: E402
from fontTools.varLib.models import piecewiseLinearMap  # noqa: E402

STATIC_OUT = os.path.realpath(build.OUT)          # build/, never written here
VF_OUT = os.path.join(ROOT, "build", "variable")
DEFAULT_WEIGHT = 400
OUTLINE_TOL = 1.0      # font units a sparse glyph may drift from a static weight
# The italic statics shear an already rounded Noto outline and round again, so their
# CJK points sit up to about 1.5 units off a straight line between weights. Holding the
# italic to 1.0 keeps 8 or 9 masters for most kanji (33 MB instead of 14 MB).
ITALIC_OUTLINE_TOL = 1.5
SPARSE_ADVANCE = 0xFFFF  # varLib's marker for "this master has no advance for the glyph"


# --------------------------------------------------------------------------- #
# Masters
# --------------------------------------------------------------------------- #
def _master_worker(task):
    """Build one master with build.build_face, redirected away from build/.

    Runs in a worker process (spawned on macOS), so the redirect is set here rather
    than in main()."""
    weight, italic, vcfg, tmpdir, out_dir = task
    if os.path.realpath(out_dir) == STATIC_OUT:
        raise SystemExit("refusing to write masters into build/")
    build.OUT = out_dir
    name = build.build_face(weight, italic, vcfg, tmpdir)
    return name, os.path.getsize(os.path.join(out_dir, name)) // 1024


def build_masters(cfg: dict, variants: list, styles: list, out_dir: str, jobs: int) -> None:
    tmpdir = tempfile.mkdtemp(prefix="ninter_vf_")
    tasks = []
    for variant in variants:
        vcfg = {**cfg, **variant}
        for weight in cfg["weights"]:
            for italic in styles:
                tasks.append((weight, italic, vcfg, tmpdir, out_dir))
    jobs = max(1, min(jobs, len(tasks)))
    print(f"  {len(tasks)} masters on {jobs} worker(s) -> {out_dir}")
    done = 0
    try:
        if jobs == 1:
            for t in tasks:
                out, size = _master_worker(t)
                done += 1
                print(f"  [{done:>2}/{len(tasks)}] {out:34s} {size:>6d} KB", flush=True)
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=jobs) as ex:
                futs = [ex.submit(_master_worker, t) for t in tasks]
                for fut in as_completed(futs):
                    out, size = fut.result()
                    done += 1
                    print(f"  [{done:>2}/{len(tasks)}] {out:34s} {size:>6d} KB", flush=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Axis
# --------------------------------------------------------------------------- #
def noto_axis_map() -> dict:
    """Noto Sans JP's own wght avar as {normalized: normalized} (default at 100)."""
    font = TTFont(build.NOTO, lazy=True)
    return dict(font["avar"].segments["wght"])


def design_coordinate(weight: float, noto_avar: dict) -> float:
    """Design coordinate of a user weight: Noto's avar curve rescaled to 100..900.

    Noto interpolates linearly along this coordinate, so its glyphs need no master
    between 100, 400 and 900."""
    return 100 + 800 * piecewiseLinearMap((weight - 100) / 800, noto_avar)


def axis_breakpoints(cfg: dict, noto_avar: dict) -> list[float]:
    user = {100 + 800 * k for k in noto_avar if k >= 0} | set(cfg["weights"])
    return sorted(user)


def master_design_coordinates(weights: list, noto_avar: dict, default: int) -> dict:
    """Design coordinate of each master, snapped so that its normalized position is
    an exact F2Dot14 value, then moved one F2Dot14 step for the in-between masters.

    Renderers quantize the normalized coordinate to F2Dot14 before reading avar, gvar
    and HVAR, but varLib computes the deltas from the unquantized master positions.
    Without the snap a master's own instance lands a fraction off and some advances
    round one unit away from the static face. The extra step avoids exact halves:
    Noto's curve puts 200, 600 and 800 exactly halfway between their neighbours, so a
    neighbour's odd delta contributes x.5 and the sum ties at the rounding point. A
    step of 1/16384 moves a Noto glyph by far less than a unit."""
    raw = {w: design_coordinate(w, noto_avar) for w in weights}
    lo, hi, d0 = raw[min(weights)], raw[max(weights)], raw[default]
    out = {}
    for w, d in raw.items():
        span = (d0 - lo) if d < d0 else (hi - d0)
        q = round((d - d0) / span * 16384) if span else 0
        if w not in (min(weights), max(weights), default):
            q += 1
        out[w] = d0 + q / 16384 * span
    return out


# --------------------------------------------------------------------------- #
# Sparse masters
# --------------------------------------------------------------------------- #
def sparsify(masters: dict, weights: list, design: dict, default: int,
             tolerance: float = OUTLINE_TOL) -> dict:
    """Blank each glyph in the masters it does not need.

    A glyph keeps the 100, default and 900 masters, then gains the master with the
    largest error until linear interpolation along the design axis lands within
    `tolerance` units of every master's outline and on every master's advance exactly
    (phantom points included, so gvar and HVAR agree). The other masters get an empty
    glyph and the 0xFFFF advance, which varLib reads as "missing" in gvar and HVAR.
    The advance must land within 0.25 of the master, away from a rounding tie.

    stats["keep"] maps each thinned glyph to the masters it kept (rebuild_hvar uses it);
    a glyph not listed keeps all of them."""
    lo, hi = min(weights), max(weights)
    order = masters[default].getGlyphOrder()
    stats = {"glyphs": len(order), "constant": 0, "dense": 0, "by_count": {}, "keep": {}}
    for gname in order:
        values, controls = {}, []
        for w in weights:
            m = masters[w]
            coords, control = m["glyf"]._getCoordinatesAndControls(gname, m["hmtx"].metrics)[:2]
            values[w] = list(coords.array)
            controls.append(control)
        if any(c != controls[0] for c in controls):
            raise SystemExit(f"glyph {gname} is not compatible across masters")
        if controls[0].numberOfContours == 0:     # empty in the default: leave as is
            continue
        if all(values[w] == values[default] for w in weights):
            stats["constant"] += 1
            continue
        npts = len(values[default]) // 2
        adv_cols = (2 * (npts - 4), 2 * (npts - 3))   # phantom points 0 and 1, x
        keep = {lo, default, hi}
        while True:
            nodes = sorted(keep)
            worst_out, bad_adv = {}, {}
            for w in weights:
                if w in keep:
                    continue
                # neighbours along the design axis; interpolation is linear between them
                left = max(n for n in nodes if n < w)
                right = min(n for n in nodes if n > w)
                t = (design[w] - design[left]) / (design[right] - design[left])
                a, b, v = values[left], values[right], values[w]
                pred = [x + (y - x) * t for x, y in zip(a, b)]
                worst_out[w] = max(abs(p - q) for p, q in zip(pred, v))
                bad_adv[w] = any(abs(pred[c] - v[c]) > 0.25 for c in adv_cols)
            bad = [w for w in worst_out if worst_out[w] > tolerance or bad_adv[w]]
            if not bad:
                break
            keep.add(max(bad, key=lambda w: (bad_adv[w], worst_out[w])))
        stats["by_count"][len(keep)] = stats["by_count"].get(len(keep), 0) + 1
        if len(keep) == len(weights):
            stats["dense"] += 1
            continue
        stats["keep"][gname] = sorted(keep)
        for w in weights:
            if w in keep:
                continue
            m = masters[w]
            m["glyf"].glyphs[gname] = Glyph()
            m["hmtx"].metrics[gname] = (SPARSE_ADVANCE, 0)
    return stats


def rebuild_hvar(vf: TTFont, advances: dict, keep: dict, weights: list, design: dict,
                 default: int) -> None:
    """Replace varLib's HVAR with one where each kept master owns a tent between its
    kept neighbours.

    varLib's model leaves earlier masters partly active at an in-between master, so the
    advance there is a fraction that can sit next to x.5. Renderers differ by one F2Dot14
    step in the coordinate they compute for, say, wght 700 (HarfBuzz lands one above
    avar's own value), and that flips the rounding by a unit. With tents, only the
    master's own region is active at its position and the advance is an exact integer.
    Between masters the result is the same piecewise-linear line as gvar."""
    from fontTools.misc.roundTools import noRound
    from fontTools.varLib import builder as vbuilder
    from fontTools.varLib import varStore
    lo, hi, d0 = design[min(weights)], design[max(weights)], design[default]
    pos = {w: (design[w] - d0) / ((d0 - lo) if design[w] < d0 else (hi - d0)) for w in weights}
    store = varStore.OnlineVarStoreBuilder(["wght"])
    mapping = {}
    for gname in vf.getGlyphOrder():
        nodes = keep.get(gname, weights)
        adv = advances[gname]
        supports, deltas = [], []
        for i, w in enumerate(nodes):
            if w == default:
                continue
            prev = pos[nodes[i - 1]] if i > 0 else -1.0
            nxt = pos[nodes[i + 1]] if i + 1 < len(nodes) else 1.0
            supports.append({"wght": (prev, pos[w], nxt)})
            deltas.append(adv[w] - adv[default])
        store.setSupports(supports)
        mapping[gname] = store.storeDeltas(deltas, round=noRound)
    vs = store.finish()
    remap = vs.optimize(use_NO_VARIATION_INDEX=False)
    hvar = vf["HVAR"].table
    hvar.VarStore = vs
    hvar.AdvWidthMap = vbuilder.buildVarIdxMap(
        [remap[mapping[g]] for g in vf.getGlyphOrder()], vf.getGlyphOrder())
    hvar.LsbMap = hvar.RsbMap = None


# --------------------------------------------------------------------------- #
# Weight-conditional GPOS lookups
# --------------------------------------------------------------------------- #
def noto_feature_threshold() -> float | None:
    """Noto switches palt/vpal to an extra lookup from about Bold up (a GPOS
    FeatureVariations record). Return where, in Noto's normalized wght, or None."""
    gpos = TTFont(build.NOTO)["GPOS"].table
    fv = getattr(gpos, "FeatureVariations", None)
    if fv is None:
        return None
    lows = {c.FilterRangeMinValue for r in fv.FeatureVariationRecord
            for c in r.ConditionSet.ConditionTable}
    if len(lows) != 1:
        raise SystemExit(f"unexpected Noto GPOS FeatureVariations: {sorted(lows)}")
    return lows.pop()


def align_conditional_lookups(masters: dict, weights: list, default: int):
    """Make GPOS structurally equal across masters, and return what varies.

    From Bold up, Noto's palt and vpal carry one more lookup each. The statics keep
    that (Ninter, where palt is not baked). varLib needs one feature list for all
    masters, so the extra lookups are appended to every master (the lighter masters
    borrow the first heavy master's values; the lookups are only switched on above
    the threshold, where only heavy masters interpolate) and the features are reset
    to the default lists. Returns {feature index: heavy lookup list} and the lightest
    heavy weight, for add_conditional_features() after the build."""
    from copy import deepcopy
    base = masters[default]["GPOS"].table
    base_lists = [list(r.Feature.LookupListIndex) for r in base.FeatureList.FeatureRecord]
    n_base = len(base.LookupList.Lookup)
    heavy = {}
    for w in weights:
        table = masters[w]["GPOS"].table
        lists = [list(r.Feature.LookupListIndex) for r in table.FeatureList.FeatureRecord]
        if lists == base_lists and len(table.LookupList.Lookup) == n_base:
            continue
        if len(lists) != len(base_lists):
            raise SystemExit(f"GPOS feature count differs at weight {w}")
        changed = {}
        for i, (a, b) in enumerate(zip(base_lists, lists)):
            if a != b:
                if b[:len(a)] != a or any(li < n_base for li in b[len(a):]):
                    raise SystemExit(f"GPOS feature {i} differs at weight {w} in an unexpected way")
                changed[i] = b
        heavy[w] = changed
    if not heavy:
        return {}, None
    first = min(heavy)
    if any(heavy[w] != heavy[first] for w in heavy) or \
            sorted(heavy) != [w for w in weights if w >= first]:
        raise SystemExit("weight-conditional GPOS lookups are not one upper range of weights")
    extra = masters[first]["GPOS"].table.LookupList.Lookup[n_base:]
    for w in weights:
        table = masters[w]["GPOS"].table
        if w not in heavy:
            table.LookupList.Lookup.extend(deepcopy(lk) for lk in extra)
            table.LookupList.LookupCount = len(table.LookupList.Lookup)
        for rec, lst in zip(table.FeatureList.FeatureRecord, base_lists):
            rec.Feature.LookupListIndex = list(lst)
            rec.Feature.LookupCount = len(lst)
    return heavy[first], first


def add_conditional_features(vf: TTFont, changed: dict, threshold: float) -> None:
    """Switch the features in `changed` to their heavy lookup lists above
    `threshold` (normalized wght, after avar), as Noto does."""
    from fontTools.ttLib.tables import otTables as ot
    gpos = vf["GPOS"].table
    cond = ot.ConditionTable()
    cond.Format, cond.AxisIndex = 1, 0
    cond.FilterRangeMinValue, cond.FilterRangeMaxValue = threshold, 1.0
    cset = ot.ConditionSet()
    cset.ConditionTable = [cond]
    cset.ConditionCount = 1
    subst = ot.FeatureTableSubstitution()
    subst.Version = 0x00010000
    subst.SubstitutionRecord = []
    for index, lookups in sorted(changed.items()):
        rec = ot.FeatureTableSubstitutionRecord()
        rec.FeatureIndex = index
        rec.Feature = ot.Feature()
        rec.Feature.FeatureParams = None
        rec.Feature.LookupListIndex = list(lookups)
        rec.Feature.LookupCount = len(lookups)
        subst.SubstitutionRecord.append(rec)
    subst.SubstitutionCount = len(subst.SubstitutionRecord)
    record = ot.FeatureVariationRecord()
    record.ConditionSet = cset
    record.FeatureTableSubstitution = subst
    fv = ot.FeatureVariations()
    fv.Version = 0x00010000
    fv.FeatureVariationRecord = [record]
    fv.FeatureVariationCount = 1
    gpos.FeatureVariations = fv
    gpos.Version = 0x00010001


# --------------------------------------------------------------------------- #
# Names, style bits, STAT
# --------------------------------------------------------------------------- #
def vf_family(family: str) -> str:
    return f"{family} Variable"


def vf_filename(family: str, italic: bool) -> str:
    return vf_family(family).replace(" ", "") + ("-Italic" if italic else "") + ".ttf"


def set_vf_names(font: TTFont, family: str, italic: bool, cfg: dict) -> None:
    fam = vf_family(family)
    ps_family = fam.replace(" ", "")
    style = "Italic" if italic else "Regular"
    version = cfg["version"]
    name = font["name"]
    keep = [r for r in name.names if r.nameID > 255]   # axis and instance names
    name.names = keep

    def s(nid, val):
        name.setName(val, nid, 3, 1, 0x409)
        name.setName(val, nid, 1, 0, 0)

    s(0, build.COPYRIGHT)
    s(1, fam)
    s(2, style)
    s(3, f"{version};NINT;{ps_family}-{style}")
    s(4, f"{fam} {style}")
    s(5, f"Version {version}")
    s(6, f"{ps_family}-{style}")
    s(7, "Ninter is a trademark of no one; use freely under the OFL.")
    s(11, build.OFL_URL)
    s(13, "This Font Software is licensed under the SIL Open Font License, "
          "Version 1.1. Inherited from Noto Sans JP and Inter.")
    s(14, build.OFL_URL)
    s(25, ps_family + ("Italic" if italic else ""))


def add_stat(font: TTFont, cfg: dict, italic: bool) -> None:
    ELIDABLE = 0x2
    weights = []
    for w in cfg["weights"]:
        value = {"value": w, "name": build.WEIGHT_NAMES[w]}
        if w == DEFAULT_WEIGHT:
            value.update(flags=ELIDABLE, linkedValue=700)
        weights.append(value)
    ital = ([{"value": 1, "name": "Italic"}] if italic else
            [{"value": 0, "name": "Roman", "flags": ELIDABLE, "linkedValue": 1}])
    buildStatTable(font, [
        {"tag": "wght", "name": "Weight", "values": weights},
        {"tag": "ital", "name": "Italic", "values": ital},
    ], elidedFallbackName="Italic" if italic else "Regular")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _digest(font: TTFont, tag: str) -> str:
    return hashlib.md5(font[tag].compile(font)).hexdigest()


def assemble(variant: dict, italic: bool, cfg: dict, masters_dir: str,
             noto_avar: dict, sparse: bool, tolerance: float = OUTLINE_TOL) -> str:
    family = variant["family"]
    vcfg = {**cfg, **variant}
    weights = list(cfg["weights"])
    if DEFAULT_WEIGHT not in weights:
        raise SystemExit("the default weight 400 must be one of the weights")
    tag = "Italic" if italic else ""
    paths = {w: os.path.join(masters_dir, family.replace(" ", "") + "-"
                             + build.WEIGHT_NAMES[w] + tag + ".ttf") for w in weights}
    t0 = time.time()
    masters = {w: TTFont(p) for w, p in paths.items()}

    base = masters[DEFAULT_WEIGHT]
    for w, m in masters.items():
        if m.getGlyphOrder() != base.getGlyphOrder():
            raise SystemExit(f"glyph order of {paths[w]} differs from the default master")
        for t in ("cmap", "GSUB", "GDEF"):
            if _digest(m, t) != _digest(base, t):
                raise SystemExit(f"{t} of {paths[w]} differs from the default master")

    design = master_design_coordinates(weights, noto_avar, DEFAULT_WEIGHT)
    changed, first_heavy = align_conditional_lookups(masters, weights, DEFAULT_WEIGHT)
    threshold = None
    if changed:
        noto_low = noto_feature_threshold()
        d_low = (100 + 800 * noto_low) if noto_low is not None else \
            (design[first_heavy] + design[max(w for w in weights if w < first_heavy)]) / 2
        if not design[max(w for w in weights if w < first_heavy)] < d_low <= design[first_heavy]:
            raise SystemExit("Noto's palt/vpal switch does not fall between two masters")
        threshold = (d_low - design[DEFAULT_WEIGHT]) / (max(design.values()) - design[DEFAULT_WEIGHT])
        print(f"  GPOS features {sorted(changed)} switch lookups from wght {first_heavy} "
              f"(normalized {threshold:.4f})", flush=True)
    advances = {g: {w: masters[w]["hmtx"][g][0] for w in weights}
                for g in base.getGlyphOrder()}
    keep = {}
    if sparse:
        stats = sparsify(masters, weights, design, DEFAULT_WEIGHT, tolerance)
        keep = stats["keep"]
        print(f"  sparse masters: {stats['glyphs']} glyphs, {stats['constant']} constant, "
              f"masters kept per varying glyph {dict(sorted(stats['by_count'].items()))}",
              flush=True)

    doc = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.tag, axis.name = "wght", "Weight"
    axis.minimum, axis.default, axis.maximum = min(weights), DEFAULT_WEIGHT, max(weights)
    axis.map = [(u, design[u] if u in design else design_coordinate(u, noto_avar))
                for u in axis_breakpoints(cfg, noto_avar)]
    doc.addAxis(axis)
    for w in weights:
        src = SourceDescriptor()
        src.font = masters[w]
        src.name = f"master {w}"
        src.location = {"Weight": design[w]}
        doc.addSource(src)
    fam = vf_family(family)
    ps_family = fam.replace(" ", "")
    for w in weights:
        inst = InstanceDescriptor()
        inst.familyName = fam
        inst.styleName = build.typographic_subfamily(w, italic)
        inst.postScriptFontName = f"{ps_family}-{inst.styleName.replace(' ', '')}"
        inst.userLocation = {"Weight": w}
        doc.addInstance(inst)

    vf, _, _ = varlib_build(doc, exclude=["STAT", "MVAR"])
    del masters

    rebuild_hvar(vf, advances, keep, weights, design, DEFAULT_WEIGHT)
    if changed:
        add_conditional_features(vf, changed, threshold)
    build.repair_langsys(vf)           # varLib rebuilt GPOS; keep kana/hani kern order
    build.fix_metrics(vf)
    build.set_style_bits(vf, DEFAULT_WEIGHT, italic, vcfg)
    set_vf_names(vf, family, italic, vcfg)
    add_stat(vf, cfg, italic)

    os.makedirs(VF_OUT, exist_ok=True)
    out = os.path.join(VF_OUT, vf_filename(family, italic))
    vf.save(out)
    print(f"  {os.path.relpath(out, ROOT):44s} {os.path.getsize(out) // 1024:>7d} KB "
          f"({time.time() - t0:.0f} s)", flush=True)
    return out


# --------------------------------------------------------------------------- #
def _static_fingerprint() -> dict:
    out = {}
    for name in sorted(os.listdir(STATIC_OUT)):
        if name.endswith(".ttf"):
            st = os.stat(os.path.join(STATIC_OUT, name))
            out[name] = (st.st_size, st.st_mtime_ns)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Ninter variable fonts.")
    ap.add_argument("--only-variant", type=str, help='Build one family, e.g. "Ninter P"')
    ap.add_argument("--upright-only", action="store_true")
    ap.add_argument("--italic-only", action="store_true")
    ap.add_argument("--masters-dir", type=str,
                    help="Folder for the masters (default: a temporary folder)")
    ap.add_argument("--keep-masters", action="store_true",
                    help="Keep the temporary masters folder (a --masters-dir is always kept)")
    ap.add_argument("--skip-masters", action="store_true",
                    help="Reuse masters already in --masters-dir")
    ap.add_argument("--masters-only", action="store_true",
                    help="Build the masters and stop")
    ap.add_argument("--dense", action="store_true",
                    help="Keep all nine masters for every glyph (larger file)")
    ap.add_argument("--tolerance", type=float, default=None,
                    help="Font units a glyph may drift from a static weight before it keeps "
                         f"more masters (default {OUTLINE_TOL} roman, {ITALIC_OUTLINE_TOL} italic)")
    ap.add_argument("--jobs", "-j", type=int, default=None,
                    help="Parallel workers for the masters (default: as build.py)")
    cli = ap.parse_args()

    for p in (build.INTER_ROMAN, build.INTER_ITALIC, build.NOTO):
        if not os.path.exists(p):
            raise SystemExit(f"Missing source font: {p}\nRun: python scripts/download_sources.py")

    cfg = build.load_config(argparse.Namespace(
        slant=None, inter_yshift=None, inter_scale=None, inter_weight_offset=None,
        cjk_tighten=None, cjk_tracking=None, weights=None, no_subset=False,
        family=None, only_variant=cli.only_variant))
    variants = cfg["variants"]
    styles = [s for s in (False, True)
              if not (s and cli.upright_only) and not ((not s) and cli.italic_only)]

    if cli.skip_masters and not cli.masters_dir:
        raise SystemExit("--skip-masters needs --masters-dir")
    masters_dir = cli.masters_dir or tempfile.mkdtemp(prefix="ninter_masters_")
    os.makedirs(masters_dir, exist_ok=True)
    if os.path.realpath(masters_dir) == STATIC_OUT:
        raise SystemExit("--masters-dir must not be build/")

    print("Ninter variable build | families: "
          + ", ".join(v["family"] for v in variants)
          + " | styles: " + ", ".join("italic" if s else "roman" for s in styles))
    before = _static_fingerprint()
    try:
        if not cli.skip_masters:
            jobs = cli.jobs if cli.jobs is not None else int(cfg.get("jobs") or build.default_jobs())
            build_masters(cfg, variants, styles, masters_dir, jobs)
        if cli.masters_only:
            return
        noto_avar = noto_axis_map()
        for variant in variants:
            for italic in styles:
                assemble(variant, italic, cfg, masters_dir, noto_avar, sparse=not cli.dense,
                         tolerance=cli.tolerance if cli.tolerance is not None else
                         (ITALIC_OUTLINE_TOL if italic else OUTLINE_TOL))
    finally:
        if not cli.masters_dir and not cli.keep_masters:   # only a folder we made
            shutil.rmtree(masters_dir, ignore_errors=True)
        if _static_fingerprint() != before:
            print("WARNING: build/*.ttf changed during the variable build")
    print(f"Done -> {VF_OUT}")


if __name__ == "__main__":
    main()
