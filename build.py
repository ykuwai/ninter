#!/usr/bin/env python3
"""
Ninter - Noto Sans JP + Inter mixed (混植) font builder.

Produces a full-weight family (Thin..Black x Upright/Italic) where:
  - Latin/Western glyphs come from Inter (Roman for upright, true Italic for italic).
  - Japanese/CJK glyphs come from Noto Sans JP; for italic they are gently sheared
    (default 3 deg) so Ctrl+I gives a natural Japanese italic instead of Office's
    ugly 18 deg fake oblique.
  - Regular/Bold/Italic/Bold Italic form one RIBBI "Ninter" family, and every weight
    is also linked under the "Ninter" typographic (WWS) family, so Ctrl+I / Ctrl+B
    work in both legacy (GDI) and modern (DirectWrite) Office.

Usage:
    python build.py                 # build all weights from ninter.config.json
    python build.py --weights 400 700
    python build.py --slant 2.5 --inter-yshift -8

Source fonts are expected in ./sources (run scripts/download_sources.py first).
Outputs land in ./build.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.ttLib.scaleUpem import scale_upem
from fontTools.merge import Merger

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "sources")
OUT = os.path.join(ROOT, "build")
CONFIG_PATH = os.path.join(ROOT, "ninter.config.json")

INTER_ROMAN = os.path.join(SRC, "Inter[opsz,wght].ttf")
INTER_ITALIC = os.path.join(SRC, "Inter-Italic[opsz,wght].ttf")
NOTO = os.path.join(SRC, "NotoSansJP[wght].ttf")

# weight value -> style name
WEIGHT_NAMES = {
    100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular",
    500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black",
}

# Line metrics for the merged font. We mirror Noto Sans JP so line spacing matches
# a normal Japanese document (1em) and CJK glyphs are never clipped.
NOTO_TYPO_ASC, NOTO_TYPO_DESC, NOTO_TYPO_GAP = 880, -120, 0
NOTO_WIN_ASC, NOTO_WIN_DESC = 1160, 288
NOTO_XHEIGHT, NOTO_CAPHEIGHT = 543, 733

# Tables that carry variation data or vertical-writing metrics. Stripping them makes
# the instanced statics mergeable and keeps the output horizontal-text clean.
DROP_TABLES = ["gvar", "avar", "fvar", "HVAR", "VVAR", "MVAR", "STAT", "cvar",
               "BASE", "vhea", "vmtx", "VORG"]

OFL_URL = "https://openfontlicense.org"
COPYRIGHT = ("Ninter is a mix of Noto Sans JP (c) Google and Inter (c) The Inter "
             "Project Authors. Both under the SIL Open Font License 1.1.")


def load_config(cli: argparse.Namespace) -> dict:
    cfg = {
        "family": "Ninter", "slant_angle": 3.0, "inter_yshift": 0,
        "inter_scale": 1.0, "inter_tracking": 0,
        "inter_weights": {}, "inter_weight_offset": 0,
        "cjk_tighten": 1.0, "cjk_tracking": 0, "defer_cjk_symbols": True,
        "numeric_colon": True,
        "variants": [
            {"family": "Ninter", "cjk_tighten": 0.0},     # no tsume (full-width beta)
            {"family": "Ninter P", "cjk_tighten": 1.0},   # tsume (palt baked)
        ],
        "weights": [100, 200, 300, 400, 500, 600, 700, 800, 900],
        "opsz": 14, "subset": True, "version": "1.000",
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            disk = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        cfg.update(disk)
    # normalize inter_weights keys to int
    cfg["inter_weights"] = {int(k): float(v) for k, v in (cfg.get("inter_weights") or {}).items()}
    # CLI overrides
    if cli.slant is not None:
        cfg["slant_angle"] = cli.slant
    if cli.inter_yshift is not None:
        cfg["inter_yshift"] = cli.inter_yshift
    if cli.inter_scale is not None:
        cfg["inter_scale"] = cli.inter_scale
    if cli.inter_weight_offset is not None:
        cfg["inter_weight_offset"] = cli.inter_weight_offset
    if cli.cjk_tighten is not None:
        cfg["cjk_tighten"] = cli.cjk_tighten
    if cli.cjk_tracking is not None:
        cfg["cjk_tracking"] = cli.cjk_tracking
    if cli.weights:
        cfg["weights"] = cli.weights
    if cli.no_subset:
        cfg["subset"] = False
    # Ad-hoc single-variant build when --family / --cjk-tighten given on the CLI.
    fam = getattr(cli, "family", None)
    only = getattr(cli, "only_variant", None)
    if fam or cli.cjk_tighten is not None:
        cfg["variants"] = [{"family": fam or cfg["family"], "cjk_tighten": cfg["cjk_tighten"]}]
    elif only:
        cfg["variants"] = [v for v in cfg["variants"] if v["family"] == only] or cfg["variants"]
    # each variant must carry a family; default cjk_tighten from cfg if omitted
    for v in cfg["variants"]:
        v.setdefault("cjk_tighten", cfg["cjk_tighten"])
    return cfg


# CJK-context blocks that should be full-width from Noto (consistent, never Inter's
# oversized/proportional versions): Roman numerals, Enclosed Alphanumerics,
# Box Drawing + Block Elements + Geometric Shapes.
DEFER_BLOCKS = [(0x2160, 0x2188), (0x2460, 0x24FF), (0x2500, 0x25FF)]
# Any other Inter glyph wider than this (units @1000upm) is a designed-large symbol
# (enclosing marks, oversized dingbats) that clashes with CJK context -> use Noto.
DEFER_SIZE_THRESHOLD = 1350

_NOTO_CPS = None


def noto_codepoints() -> set:
    global _NOTO_CPS
    if _NOTO_CPS is None:
        _NOTO_CPS = set(TTFont(NOTO).getBestCmap().keys())
    return _NOTO_CPS


def defer_cjk_symbols_to_noto(inter_font: TTFont) -> int:
    """Drop from Inter's cmap the CJK-context symbols (circled numbers ①②, Roman
    numerals, box/geometric shapes, and any oversized symbol) that Noto also covers,
    so the merge takes Noto's consistent full-width versions instead of Inter's
    oversized ones. Call while Inter is at 1000 upm, before inter_scale."""
    noto = noto_codepoints()
    hmtx = inter_font["hmtx"]
    remove = set()
    for table in inter_font["cmap"].tables:
        for cp, gn in table.cmap.items():
            if cp not in noto or cp < 0x2000:
                continue
            in_block = any(lo <= cp <= hi for lo, hi in DEFER_BLOCKS)
            oversized = gn in hmtx.metrics and hmtx[gn][0] > DEFER_SIZE_THRESHOLD
            if in_block or oversized:
                remove.add(cp)
    for table in inter_font["cmap"].tables:
        for cp in list(table.cmap.keys()):
            if cp in remove:
                del table.cmap[cp]
    return len(remove)


def defer_latin_to_inter(noto_font: TTFont, inter_cps: set) -> int:
    """Drop from Noto's cmap every codepoint Inter still maps, BEFORE the merge.

    fontTools.merge resolves a cmap conflict (both fonts map the same codepoint) by
    keeping the *first* font's glyph — Inter — and then **synthesising a `locl` lookup**
    that substitutes back to the second font's (Noto's) glyph whenever a language system
    is active (fontTools/merge/layout.py `GSUB.merge`). That lookup is prepended to the
    `locl` feature of *every* script in Noto's GSUB, hani/kana included. Uniscribe applies
    `locl` for a Japanese run (OpenType language JAN) but not for a bare Latin run, so a
    Latin word touching Japanese silently gets its glyphs swapped Inter->Noto — this is
    the "英数字が全角と隣接すると Noto 由来になる" bug (standalone Latin stays Inter).

    Removing the overlapping codepoints from Noto here means the merge sees no conflict,
    synthesises no `locl`, and Inter wins cleanly in *every* context. Inter already won
    these in cmap (merge order is Inter-first), so nothing visible changes except the
    unwanted back-substitution disappears; the now-unreachable Noto duplicates are subset
    away. Deferred CJK symbols (①②, Roman numerals, box shapes) were already removed from
    Inter's cmap, so they are absent from `inter_cps` and stay mapped to Noto."""
    removed = 0
    for table in noto_font["cmap"].tables:
        for cp in list(table.cmap.keys()):
            if cp in inter_cps:
                del table.cmap[cp]
                removed += 1
    return removed


def use_numeric_colon(font: TTFont) -> None:
    """Bake Inter's figure-height colon into the default `colon` glyph.

    Inter's plain `colon` is a low *text* colon (dots centered near x-height); the
    number-flanked colon in times/ratios like 12:34 is a separate `colon.case` glyph,
    vertically centered on the digits, that Inter normally swaps in via `case`/`calt`.
    In Ninter that substitution is unreliable: PowerPoint doesn't consistently apply
    those features (especially in a CJK-shaped run), and our subset can drop the
    unencoded `colon.case` outright. Since this font's half-width colon is overwhelmingly
    used between figures, copy the raised outline into the default `colon` (and the
    tabular `colon.tf`) so it is always figure-centered, regardless of app support.
    Call while Inter is at 1000 upm, before the vertical shift/scale. (issue #1)"""
    import copy
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    for base, raised in (("colon", "colon.case"), ("colon.tf", "colon.case.tf")):
        if base in glyf and raised in glyf:
            glyf[base] = copy.deepcopy(glyf[raised])  # deep copy: transform_inter later
            hmtx[base] = hmtx[raised]                  # touches each glyph name once


def resolve_inter_weight(weight: int, cfg: dict) -> float:
    """Inter's wght for a given Noto/output weight. Inter reads heavier at the same
    nominal weight, so this lets Inter be dialed independently (per-weight map first,
    then a global offset, clamped to Inter's 100-900 axis)."""
    mp = cfg.get("inter_weights") or {}
    if weight in mp:
        iw = mp[weight]
    else:
        iw = weight + cfg.get("inter_weight_offset", 0)
    return max(100.0, min(900.0, float(iw)))


# --------------------------------------------------------------------------- #
# Glyph transforms
# --------------------------------------------------------------------------- #
def cleanup_tables(font: TTFont) -> None:
    for t in DROP_TABLES:
        if t in font:
            del font[t]
    if "GDEF" in font and getattr(font["GDEF"].table, "VarStore", None) is not None:
        font["GDEF"].table.VarStore = None


def transform_inter(font: TTFont, yshift: int, scale: float) -> None:
    """Scale about the baseline and shift vertically, to visually align Inter's
    baseline/size with Noto. Advances are scaled too so spacing stays proportional."""
    if scale == 1.0 and yshift == 0:
        return
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    for name in glyf.keys():
        g = glyf[name]
        if g.isComposite():
            # Component offsets only scale — the yshift is already applied to the
            # referenced base glyph's own points, so adding it here too would shift a
            # composite (accented letters, the colon) down by yshift twice, dropping
            # it below the simple glyphs (digits) it should align with. (issue #1)
            for comp in g.components:
                comp.x = round(comp.x * scale)
                comp.y = round(comp.y * scale)
        elif hasattr(g, "coordinates"):
            for i, (x, y) in enumerate(g.coordinates):
                g.coordinates[i] = (round(x * scale), round(y * scale + yshift))
        g.recalcBounds(glyf)
    if scale != 1.0:
        for name in hmtx.metrics:
            w, lsb = hmtx[name]
            hmtx[name] = (round(w * scale), round(lsb * scale))
    # fix lsb from new bounds
    for name in glyf.keys():
        g = glyf[name]
        w, _ = hmtx[name]
        hmtx[name] = (w, getattr(g, "xMin", 0))


def slant_font(font: TTFont, angle_deg: float) -> None:
    """Shear glyphs by angle_deg (positive = forward/right lean) in place.
    Advances are preserved; only outlines and component offsets move."""
    if not angle_deg:
        return
    tan = math.tan(math.radians(angle_deg))
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    for name in glyf.keys():
        g = glyf[name]
        if g.isComposite():
            for comp in g.components:
                comp.x = comp.x + round(tan * comp.y)
        elif hasattr(g, "coordinates"):
            for i, (x, y) in enumerate(g.coordinates):
                g.coordinates[i] = (x + round(tan * y), y)
        g.recalcBounds(glyf)
        w, _ = hmtx[name]
        hmtx[name] = (w, getattr(g, "xMin", 0))


# --------------------------------------------------------------------------- #
# Component preparation
# --------------------------------------------------------------------------- #
def prepare_inter(weight: int, italic: bool, cfg: dict, path: str) -> None:
    src = INTER_ITALIC if italic else INTER_ROMAN
    font = TTFont(src)
    inter_wght = resolve_inter_weight(weight, cfg)
    instancer.instantiateVariableFont(
        font, {"wght": inter_wght, "opsz": cfg["opsz"]}, inplace=True)
    scale_upem(font, 1000)
    cleanup_tables(font)
    if cfg.get("defer_cjk_symbols", True):
        defer_cjk_symbols_to_noto(font)
    if cfg.get("numeric_colon", True):
        use_numeric_colon(font)
    transform_inter(font, int(cfg["inter_yshift"]), float(cfg["inter_scale"]))
    font.save(path)


def _cjk_codepoints(font: TTFont) -> set:
    """Glyph names whose Unicode falls in Japanese/CJK ranges (kana, kanji,
    punctuation, fullwidth forms) — i.e. the glyphs that come from Noto, not Inter."""
    ranges = [(0x3000, 0x303F), (0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF),
              (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0xFF00, 0xFFEF)]
    names = set()
    for cp, gn in font.getBestCmap().items():
        if any(lo <= cp <= hi for lo, hi in ranges):
            names.add(gn)
    return names


def _read_palt(font: TTFont) -> dict:
    """Return {glyphName: (dXAdvance, dXPlacement)} from the font's `palt` feature —
    the designer's proportional (tightened) metrics for CJK/kana/punctuation."""
    if "GPOS" not in font:
        return {}
    gpos = font["GPOS"].table
    palt_lookups = set()
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "palt":
            palt_lookups.update(fr.Feature.LookupListIndex)
    adjust = {}

    def handle_singlepos(st):
        if st.Format == 1:
            for g in st.Coverage.glyphs:
                adjust[g] = (getattr(st.Value, "XAdvance", 0) or 0,
                             getattr(st.Value, "XPlacement", 0) or 0)
        else:
            for i, g in enumerate(st.Coverage.glyphs):
                v = st.Value[i]
                adjust[g] = (getattr(v, "XAdvance", 0) or 0,
                             getattr(v, "XPlacement", 0) or 0)

    for li in palt_lookups:
        lk = gpos.LookupList.Lookup[li]
        for st in lk.SubTable:
            if lk.LookupType == 9:              # Extension -> deref
                st = st.ExtSubTable
                lt = st.LookupType if hasattr(st, "LookupType") else 1
            else:
                lt = lk.LookupType
            if getattr(st, "Coverage", None) is not None and hasattr(st, "Format"):
                handle_singlepos(st)
    return adjust


def _shift_and_setwidth(font: TTFont, gname: str, dx: int, new_adv: int) -> None:
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    g = glyf[gname]
    if dx:
        if g.isComposite():
            for comp in g.components:
                comp.x += dx
        elif hasattr(g, "coordinates"):
            for i, (x, y) in enumerate(g.coordinates):
                g.coordinates[i] = (x + dx, y)
        g.recalcBounds(glyf)
    hmtx[gname] = (new_adv, getattr(g, "xMin", 0))


def apply_palt(font: TTFont, factor: float) -> None:
    """Bake `factor` (0..1) of the palt proportional metrics into default advances,
    so kana/punctuation tighten without the app needing palt enabled. factor=1 is the
    full designer proportional; kanji get ~0 so they stay full-width."""
    if factor <= 0:
        return
    adjust = _read_palt(font)
    for gn, (dadv, dpla) in adjust.items():
        if gn not in font["glyf"]:
            continue
        adv, _ = font["hmtx"][gn]
        _shift_and_setwidth(font, gn, round(dpla * factor), adv + round(dadv * factor))
    # neutralise palt so an app that enables it can't tighten a second time
    for fr in font["GPOS"].table.FeatureList.FeatureRecord:
        if fr.FeatureTag in ("palt", "vpal", "halt", "vhal"):
            fr.Feature.LookupListIndex = []


def apply_cjk_tracking(font: TTFont, units: int) -> None:
    """Uniformly tighten (units>0) or loosen (units<0) every CJK glyph's advance,
    re-centering the glyph. On top of palt, an overall density knob."""
    if not units:
        return
    for gn in _cjk_codepoints(font):
        if gn not in font["glyf"]:
            continue
        adv, _ = font["hmtx"][gn]
        _shift_and_setwidth(font, gn, -round(units / 2), adv - units)


def prepare_noto(weight: int, italic: bool, cfg: dict, path: str,
                 inter_cps: set | None = None) -> None:
    font = TTFont(NOTO)
    instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)
    cleanup_tables(font)
    if inter_cps:
        defer_latin_to_inter(font, inter_cps)
    apply_palt(font, float(cfg.get("cjk_tighten", 1.0)))
    apply_cjk_tracking(font, int(cfg.get("cjk_tracking", 0)))
    if italic:
        slant_font(font, float(cfg["slant_angle"]))
    font.save(path)


# --------------------------------------------------------------------------- #
# Metrics + naming
# --------------------------------------------------------------------------- #
def unify_script_features(font: TTFont) -> None:
    """Make Inter's Latin OpenType features (kern, liga, ss01-20, cv*, tnum, frac, …)
    reachable from the CJK OpenType scripts (kana/hani). Apps like Illustrator shape a
    mixed Japanese+Latin run under the CJK script, where — without this — Inter's
    features registered only under 'latn' silently stop working. We union the latn/DFLT
    feature set into the kana/hani LangSys so those features still apply to Latin glyphs
    inside a CJK-shaped run. (gen-interface-jp issue #1.)"""
    CJK_SCRIPTS = {"kana", "hani", "hang"}
    SRC_SCRIPTS = {"latn", "DFLT"}
    for tag in ("GSUB", "GPOS"):
        if tag not in font:
            continue
        sl = font[tag].table.ScriptList
        src = set()
        for sr in sl.ScriptRecord:
            if sr.ScriptTag.strip() in SRC_SCRIPTS:
                langsyses = [sr.Script.DefaultLangSys] + [r.LangSys for r in sr.Script.LangSysRecord]
                for ls in langsyses:
                    if ls:
                        src.update(ls.FeatureIndex)
        if not src:
            continue
        add = sorted(src)
        for sr in sl.ScriptRecord:
            if sr.ScriptTag.strip() not in CJK_SCRIPTS:
                continue
            langsyses = [sr.Script.DefaultLangSys] + [r.LangSys for r in sr.Script.LangSysRecord]
            for ls in langsyses:
                if not ls:
                    continue
                merged = list(dict.fromkeys(list(ls.FeatureIndex) + add))
                ls.FeatureIndex = merged
                ls.FeatureCount = len(merged)


def fix_metrics(font: TTFont) -> None:
    os2 = font["OS/2"]
    hhea = font["hhea"]
    os2.sTypoAscender = NOTO_TYPO_ASC
    os2.sTypoDescender = NOTO_TYPO_DESC
    os2.sTypoLineGap = NOTO_TYPO_GAP
    os2.usWinAscent = NOTO_WIN_ASC
    os2.usWinDescent = NOTO_WIN_DESC
    os2.sxHeight = NOTO_XHEIGHT
    os2.sCapHeight = NOTO_CAPHEIGHT
    hhea.ascent = NOTO_WIN_ASC
    hhea.descent = -NOTO_WIN_DESC
    hhea.lineGap = 0


def family_subfamily(weight: int, italic: bool, family: str):
    """RIBBI grouping used by legacy GDI style-linking."""
    if weight in (400, 700):
        fam = family
        if weight == 400:
            sub = "Italic" if italic else "Regular"
        else:
            sub = "Bold Italic" if italic else "Bold"
    else:
        fam = f"{family} {WEIGHT_NAMES[weight]}"
        sub = "Italic" if italic else "Regular"
    return fam, sub


def typographic_subfamily(weight: int, italic: bool) -> str:
    """WWS subfamily used by DirectWrite so all 9 weights group under 'Ninter'."""
    name = WEIGHT_NAMES[weight]
    if name == "Regular":
        return "Italic" if italic else "Regular"
    return name + (" Italic" if italic else "")


def set_names(font: TTFont, weight: int, italic: bool, cfg: dict) -> None:
    base = cfg["family"]                       # "Ninter" or "Ninter P"
    family, subfamily = family_subfamily(weight, italic, base)
    typo_sub = typographic_subfamily(weight, italic)
    version = cfg["version"]
    full = f"{base} {typo_sub}"
    ps = base.replace(" ", "") + "-" + typo_sub.replace(" ", "")
    unique = f"{version};NINT;{ps}"

    name = font["name"]
    name.names = []

    def s(nid, val):
        name.setName(val, nid, 3, 1, 0x409)   # Windows Unicode BMP, en-US
        name.setName(val, nid, 1, 0, 0)        # Mac Roman, en

    s(0, COPYRIGHT)
    s(1, family)
    s(2, subfamily)
    s(3, unique)
    s(4, full)
    s(5, f"Version {version}")
    s(6, ps)
    s(7, "Ninter is a trademark of no one; use freely under the OFL.")
    s(11, OFL_URL)
    s(13, "This Font Software is licensed under the SIL Open Font License, "
          "Version 1.1. Inherited from Noto Sans JP and Inter.")
    s(14, OFL_URL)
    # Typographic (WWS) family/subfamily: ties every weight to one base family.
    s(16, base)
    s(17, typo_sub)


def set_style_bits(font: TTFont, weight: int, italic: bool, cfg: dict) -> None:
    os2 = font["OS/2"]
    head = font["head"]
    post = font["post"]

    os2.usWeightClass = weight

    ITALIC, BOLD, REGULAR, USE_TYPO, WWS = 0x01, 0x20, 0x40, 0x80, 0x100
    sel = USE_TYPO | WWS
    if italic:
        sel |= ITALIC
    if weight == 700:
        sel |= BOLD
    if (not italic) and weight != 700:
        sel |= REGULAR
    os2.fsSelection = sel

    mac = 0
    if weight == 700:
        mac |= 0x01
    if italic:
        mac |= 0x02
    head.macStyle = mac

    post.italicAngle = -float(cfg["slant_angle"]) if italic else 0.0
    head.fontRevision = float(cfg["version"])


# --------------------------------------------------------------------------- #
# Subsetting (drop Noto's now-unused Latin duplicates to shrink the file)
# --------------------------------------------------------------------------- #
def subset_reachable(font: TTFont) -> TTFont:
    from fontTools import subset
    unicodes = set()
    for table in font["cmap"].tables:
        unicodes.update(table.cmap.keys())
    opt = subset.Options()
    opt.name_IDs = ["*"]
    opt.name_legacy = True
    opt.name_languages = ["*"]
    opt.recalc_bounds = True
    opt.recalc_timestamp = False
    opt.glyph_names = True
    opt.notdef_outline = True
    opt.layout_features = ["*"]
    opt.drop_tables = []
    ss = subset.Subsetter(options=opt)
    ss.populate(unicodes=unicodes)
    ss.subset(font)
    return font


# --------------------------------------------------------------------------- #
# One face
# --------------------------------------------------------------------------- #
def build_face(weight: int, italic: bool, cfg: dict, tmpdir: str) -> str:
    tag = f"{WEIGHT_NAMES[weight]}{'Italic' if italic else ''}"
    # temp names include the family so parallel workers building the two variants of
    # the same weight can't clobber each other's intermediates.
    stem = f"{cfg['family'].replace(' ', '')}_{tag}"
    inter_path = os.path.join(tmpdir, f"inter_{stem}.ttf")
    noto_path = os.path.join(tmpdir, f"noto_{stem}.ttf")
    prepare_inter(weight, italic, cfg, inter_path)
    # Codepoints Inter still maps (after its own defer). Dropping these from Noto's cmap
    # before the merge stops fontTools from synthesising a `locl` that swaps Inter's Latin
    # back to Noto's inside CJK-shaped (JAN) runs. See defer_latin_to_inter().
    inter_cps = set(TTFont(inter_path).getBestCmap().keys())
    prepare_noto(weight, italic, cfg, noto_path, inter_cps)

    merged = Merger().merge([inter_path, noto_path])  # Inter first -> Latin wins

    unify_script_features(merged)   # Latin features reachable from kana/hani (gen #1)
    fix_metrics(merged)
    set_names(merged, weight, italic, cfg)
    set_style_bits(merged, weight, italic, cfg)

    if cfg.get("subset", True):
        merged = subset_reachable(merged)
        # subset may reset OS/2 metrics recompute; re-assert ours
        fix_metrics(merged)
        set_names(merged, weight, italic, cfg)
        set_style_bits(merged, weight, italic, cfg)

    out_name = cfg["family"].replace(" ", "") + "-" + tag + ".ttf"
    out_path = os.path.join(OUT, out_name)
    merged.save(out_path)
    return out_name


def _build_worker(task):
    """Top-level (picklable) worker for ProcessPoolExecutor. Builds one face and
    returns (out_name, size_kb). Args are simple values only, results are strings —
    no fontTools objects cross the process boundary (avoids pickling deadlocks)."""
    weight, italic, vcfg, tmpdir = task
    out = build_face(weight, italic, vcfg, tmpdir)
    return out, os.path.getsize(os.path.join(OUT, out)) // 1024


def _free_ram_gb() -> float:
    """Best-effort free physical RAM in GB (Windows), else a safe assumption."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / (1024 ** 3)
    except Exception:
        return 4.0


def default_jobs() -> int:
    """Memory-bound, not core-bound: each worker instantiates the full Noto CJK
    (~0.6 GB peak). Use as many workers as both cores-2 and free RAM allow, capped
    at 8. Lower --jobs if you keep other memory-heavy apps open."""
    by_cpu = (os.cpu_count() or 2) - 2
    by_ram = int(_free_ram_gb() / 0.7)
    return max(1, min(by_cpu, by_ram, 8))


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Ninter font family.")
    ap.add_argument("--weights", nargs="*", type=int, help="Subset of weights to build")
    ap.add_argument("--slant", type=float, help="Italic slant angle (deg)")
    ap.add_argument("--inter-yshift", type=int, help="Vertical shift of Inter glyphs (units)")
    ap.add_argument("--inter-scale", type=float, help="Scale of Inter glyphs")
    ap.add_argument("--inter-weight-offset", type=float,
                    help="Add this to every Inter wght (e.g. -60 to make Inter lighter)")
    ap.add_argument("--cjk-tighten", type=float,
                    help="0..1 fraction of palt proportional metrics to bake (kana/punct tighten)")
    ap.add_argument("--cjk-tracking", type=int,
                    help="Uniformly tighten every CJK advance by N units (re-centered)")
    ap.add_argument("--family", type=str,
                    help="Ad-hoc single-variant build with this family name")
    ap.add_argument("--only-variant", type=str,
                    help="Build only the config variant with this family name")
    ap.add_argument("--no-subset", action="store_true", help="Keep unused glyphs (faster, larger)")
    ap.add_argument("--jobs", "-j", type=int, default=None,
                    help="Parallel worker processes (default: cores-2, capped 6). "
                         "Lower it if RAM is tight; 1 = sequential.")
    ap.add_argument("--upright-only", action="store_true")
    ap.add_argument("--italic-only", action="store_true")
    cli = ap.parse_args()

    for p in (INTER_ROMAN, INTER_ITALIC, NOTO):
        if not os.path.exists(p):
            raise SystemExit(f"Missing source font: {p}\n"
                             f"Run: python scripts/download_sources.py")

    cfg = load_config(cli)
    os.makedirs(OUT, exist_ok=True)

    styles = []
    if not cli.italic_only:
        styles.append(False)
    if not cli.upright_only:
        styles.append(True)

    wmap = ", ".join(f"{w}->{resolve_inter_weight(w, cfg):g}" for w in cfg["weights"])
    variants = cfg["variants"]
    print(f"Ninter build | slant={cfg['slant_angle']} deg  "
          f"inter_yshift={cfg['inter_yshift']}  inter_scale={cfg['inter_scale']}  "
          f"subset={cfg['subset']}")
    print(f"  inter weight map (Noto->Inter): {wmap}")
    print(f"  variants: " + ", ".join(f"{v['family']}(palt={v.get('cjk_tighten',1.0)})" for v in variants))

    tasks = []
    for variant in variants:
        vcfg = {**cfg, **variant}   # variant overrides family + cjk_tighten
        for weight in cfg["weights"]:
            for italic in styles:
                tasks.append((weight, italic, vcfg, None))  # tmpdir filled in below

    jobs = cli.jobs if cli.jobs is not None else int(cfg.get("jobs") or default_jobs())
    jobs = max(1, min(jobs, len(tasks)))
    print(f"  {len(tasks)} faces on {jobs} worker(s)")

    tmpdir = tempfile.mkdtemp(prefix="ninter_")
    tasks = [(w, i, c, tmpdir) for (w, i, c, _) in tasks]
    done = 0
    try:
        if jobs == 1:
            for t in tasks:
                out, sz = _build_worker(t)
                done += 1
                print(f"  [{done:>2}/{len(tasks)}] {out:34s} {sz:>6d} KB")
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=jobs) as ex:
                futs = {ex.submit(_build_worker, t): t for t in tasks}
                for fut in as_completed(futs):
                    out, sz = fut.result()
                    done += 1
                    print(f"  [{done:>2}/{len(tasks)}] {out:34s} {sz:>6d} KB")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"Done -> {OUT}")


if __name__ == "__main__":
    main()
