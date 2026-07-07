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
            for comp in g.components:
                comp.x = round(comp.x * scale)
                comp.y = round(comp.y * scale + yshift)
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


def prepare_noto(weight: int, italic: bool, cfg: dict, path: str) -> None:
    font = TTFont(NOTO)
    instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)
    cleanup_tables(font)
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


def family_subfamily(weight: int, italic: bool):
    """RIBBI grouping used by legacy GDI style-linking."""
    if weight in (400, 700):
        fam = "Ninter"
        if weight == 400:
            sub = "Italic" if italic else "Regular"
        else:
            sub = "Bold Italic" if italic else "Bold"
    else:
        fam = "Ninter " + WEIGHT_NAMES[weight]
        sub = "Italic" if italic else "Regular"
    return fam, sub


def typographic_subfamily(weight: int, italic: bool) -> str:
    """WWS subfamily used by DirectWrite so all 9 weights group under 'Ninter'."""
    name = WEIGHT_NAMES[weight]
    if name == "Regular":
        return "Italic" if italic else "Regular"
    return name + (" Italic" if italic else "")


def set_names(font: TTFont, weight: int, italic: bool, cfg: dict) -> None:
    family, subfamily = family_subfamily(weight, italic)
    typo_sub = typographic_subfamily(weight, italic)
    version = cfg["version"]
    full = f"Ninter {typo_sub}"
    ps = "Ninter-" + typo_sub.replace(" ", "")
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
    # Typographic (WWS) family/subfamily: ties every weight to one "Ninter".
    s(16, "Ninter")
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
    inter_path = os.path.join(tmpdir, f"inter_{tag}.ttf")
    noto_path = os.path.join(tmpdir, f"noto_{tag}.ttf")
    prepare_inter(weight, italic, cfg, inter_path)
    prepare_noto(weight, italic, cfg, noto_path)

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

    out_name = "Ninter-" + tag + ".ttf"
    out_path = os.path.join(OUT, out_name)
    merged.save(out_path)
    return out_name


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
    ap.add_argument("--no-subset", action="store_true", help="Keep unused glyphs (faster, larger)")
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
    print(f"Ninter build | slant={cfg['slant_angle']} deg  "
          f"inter_yshift={cfg['inter_yshift']}  inter_scale={cfg['inter_scale']}  "
          f"subset={cfg['subset']}")
    print(f"  inter weight map (Noto->Inter): {wmap}")
    print(f"  cjk_tighten(palt)={cfg.get('cjk_tighten',1.0)}  cjk_tracking={cfg.get('cjk_tracking',0)}")
    tmpdir = tempfile.mkdtemp(prefix="ninter_")
    try:
        for weight in cfg["weights"]:
            for italic in styles:
                out = build_face(weight, italic, cfg, tmpdir)
                sz = os.path.getsize(os.path.join(OUT, out)) // 1024
                print(f"  built {out:32s} {sz:>6d} KB")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"Done -> {OUT}")


if __name__ == "__main__":
    main()
