#!/usr/bin/env python3
"""Build the web distribution of Ninter as npm packages.

Reads the finished fonts in build/ and build/variable/, cuts each one into WOFF2
slices along scripts/web_slices.json, and writes one package per family to dist/web/.
Each package holds two sets of CSS with the same content:

  400.css           relative font URLs, for bundlers and self-hosting
  cdn/400.css       absolute jsDelivr URLs, for a plain <link> tag
  variable.css      the variable font (font-weight 100 to 900), family "<name> Variable"
  cdn/variable.css  the same with jsDelivr URLs

Build the variable fonts first with scripts/build_variable.py.

Requires: pip install fonttools brotli
"""
import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from build import repair_langsys  # noqa: E402

BUILD_DIR = ROOT / "build"
SLICES_PATH = Path(__file__).resolve().parent / "web_slices.json"
REPO_URL = "https://github.com/ykuwai/ninter"
CDN_BASE = "https://cdn.jsdelivr.net/npm"
JSDELIVR_PACKAGE_LIMIT = 150_000_000

WEIGHTS = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
    "ExtraBold": 800,
    "Black": 900,
}
# npm package name -> (file name prefix in build/, CSS family name, one-line use)
PACKAGES = {
    "ninter": ("Ninter", "Ninter", "かなや括弧も全角でそろうファミリーです。字を升目のように並べたいときに使います。ふだんは Ninter P（ninter-p）をおすすめします"),
    "ninter-p": ("NinterP", "Ninter P", "かなや括弧が詰まるファミリーです。ふだんはこちらをおすすめします"),
}
SLICE_URL = re.compile(r'url\("([^"]+)"\)')
VARIABLE_WEIGHT = "100 900"


def variable_sources(build_dir, prefix):
    """CSS style -> variable font made by scripts/build_variable.py."""
    folder = build_dir / "variable"
    return {
        "normal": folder / f"{prefix}Variable.ttf",
        "italic": folder / f"{prefix}Variable-Italic.ttf",
    }


def static_sources(build_dir, prefix, style_name):
    return {
        "normal": build_dir / f"{prefix}-{style_name}.ttf",
        "italic": build_dir / f"{prefix}-{style_name}Italic.ttf",
    }


def parse_unicode_range(text):
    codepoints = set()
    for part in text.split(","):
        first, _, last = part.strip().removeprefix("U+").partition("-")
        codepoints.update(range(int(first, 16), int(last or first, 16) + 1))
    return codepoints


def format_unicode_range(codepoints):
    ordered = sorted(codepoints)
    runs = []
    start = previous = ordered[0]
    for codepoint in ordered[1:]:
        if codepoint != previous + 1:
            runs.append((start, previous))
            start = codepoint
        previous = codepoint
    runs.append((start, previous))
    return ",".join(f"U+{a:X}" if a == b else f"U+{a:X}-{b:X}" for a, b in runs)


def load_slice_table():
    data = json.loads(SLICES_PATH.read_text(encoding="utf-8"))
    return [parse_unicode_range(item) for item in data["slices"]]


def font_codepoints(path):
    font = TTFont(path, lazy=True)
    try:
        return set(font.getBestCmap())
    finally:
        font.close()


def plan_slices(font_path, table):
    """Return [(slice number, codepoints)] covering every codepoint of the font."""
    codepoints = font_codepoints(font_path)
    planned = [(i, part & codepoints) for i, part in enumerate(table) if part & codepoints]
    rest = codepoints - set().union(*table)
    if rest:
        planned.append((len(table), rest))
    return planned


def write_slice(job):
    """Subset one slice. Variable fonts keep fvar, gvar, avar, HVAR and STAT, and
    GPOS FeatureVariations (Ninter's palt and vpal from Bold up) are carried along."""
    font_path, codepoints, out_path = job
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    # Keeps the copyright and license records the OFL asks to travel with the font.
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    # Otherwise a mirrored partner such as U+2283 for U+2282 leaks into the slice.
    options.bidi_closure = False
    font = subset.load_font(str(font_path), options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(codepoints))
    subsetter.subset(font)
    # Subsetting merges identical features, which is what creates the duplicates.
    repair_langsys(font)
    subset.save_font(font, str(out_path), options)
    font.close()


def face_css(family, style, weight, url, codepoints):
    return (
        f'@font-face{{font-family:"{family}";font-style:{style};font-weight:{weight};'
        f'font-display:swap;src:url("{url}") format("woff2");'
        f"unicode-range:{format_unicode_range(codepoints)}}}"
    )


def package_readme(package, family, use, version):
    return f"""# {family} Web Font

{family} は、Noto Sans JP と Inter を合わせて作った、斜体に対応した日本語フォントです。Thin から Black まで 9 つの太さをすべて斜体つきで使えます。{use}。

## CDN で使う

```html
<link rel="stylesheet" href="{CDN_BASE}/{package}@{version}/cdn/400.css">
```

```css
body {{ font-family: "{family}", sans-serif; }}
```

太さごとに `100.css` から `900.css` があり、どれにも通常の字形と斜体が入っています。ページで使う文字の分だけ読み込まれるので、斜体を使わなければ斜体のファイルは届きません。

複数の太さを 1 行で読み込むこともできます。

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/combine/npm/{package}@{version}/cdn/400.css,npm/{package}@{version}/cdn/700.css">
```

## 太さを自由に選ぶ（可変フォント）

`variable.css` を読み込むと、100 から 900 までのどの太さでも使えます。450 のような中間の太さも選べて、太さを少しずつ変える動きにも向きます。ファミリー名は「{family} Variable」です。通常の字形と斜体が入っています。

```html
<link rel="stylesheet" href="{CDN_BASE}/{package}@{version}/cdn/variable.css">
```

```css
body {{ font-family: "{family} Variable", sans-serif; font-weight: 450; }}
```

npm で入れたときは `import "{package}/variable.css";` で読み込みます。

太さを 2 つか 3 つしか使わないなら、太さごとの CSS のほうが届くファイルは小さくなります。

## npm で使う

```bash
npm install {package}
```

```js
import "{package}/400.css";
```

## ライセンス

SIL Open Font License 1.1 です。詳しくは LICENSE と [リポジトリ]({REPO_URL}) を見てください。
"""


def package_json(package, family, version):
    return {
        "name": package,
        "version": version,
        "description": f"{family} web font. Noto Sans JP and Inter with true italics for Japanese, 9 weights and a variable font (wght 100-900).",
        "license": "OFL-1.1",
        "homepage": REPO_URL,
        "repository": {"type": "git", "url": f"git+{REPO_URL}.git"},
        "bugs": {"url": f"{REPO_URL}/issues"},
        "style": "all.css",
        "sideEffects": ["*.css"],
        "keywords": ["font", "webfont", "japanese", "italic", "woff2", "variable-font", "noto-sans-jp", "inter"],
    }


def write_css(package_dir, version, name, family, weight, entries):
    """Write <name>.css (relative URLs) and cdn/<name>.css (jsDelivr URLs)."""
    cdn_prefix = f"{CDN_BASE}/{package_dir.name}@{version}/"
    relative = [face_css(family, s, weight, f"./{u}", c) for s, u, c in entries]
    cdn = [face_css(family, s, weight, cdn_prefix + u, c) for s, u, c in entries]
    (package_dir / f"{name}.css").write_text("\n".join(relative) + "\n", encoding="utf-8")
    (package_dir / "cdn" / f"{name}.css").write_text("\n".join(cdn) + "\n", encoding="utf-8")
    return relative, cdn


def plan_face(sources, table, package_dir, folder, jobs):
    """Queue the slices of one face; return its CSS entries."""
    entries = []
    for css_style, font_path in sources.items():
        slice_dir = package_dir / "w" / css_style / folder
        slice_dir.mkdir(parents=True)
        for number, codepoints in plan_slices(font_path, table):
            name = f"{number:03d}.woff2"
            jobs.append((font_path, codepoints, slice_dir / name))
            entries.append((css_style, f"w/{css_style}/{folder}/{name}", codepoints))
    return entries


def build_package(package, prefix, family, use, version, table, out_root, pool, build_dir,
                  with_static=True):
    package_dir = out_root / package
    if package_dir.exists():
        shutil.rmtree(package_dir)
    (package_dir / "cdn").mkdir(parents=True)

    jobs = []
    faces = {}
    if with_static:
        for style_name, weight in WEIGHTS.items():
            faces[weight] = plan_face(static_sources(build_dir, prefix, style_name), table,
                                      package_dir, str(weight), jobs)
    variable = plan_face(variable_sources(build_dir, prefix), table, package_dir, "variable", jobs)
    # Variable slices take longest; start them first so they don't trail at the end.
    jobs.sort(key=lambda job: "variable" not in job[2].parts)
    list(pool.map(write_slice, jobs, chunksize=4))

    relative_all, cdn_all = [], []
    for weight, entries in faces.items():
        relative, cdn = write_css(package_dir, version, str(weight), family, weight, entries)
        relative_all += relative
        cdn_all += cdn
    if with_static:
        (package_dir / "all.css").write_text("\n".join(relative_all) + "\n", encoding="utf-8")
        (package_dir / "cdn" / "all.css").write_text("\n".join(cdn_all) + "\n", encoding="utf-8")
    write_css(package_dir, version, "variable", f"{family} Variable", VARIABLE_WEIGHT, variable)

    shutil.copyfile(ROOT / "LICENSE", package_dir / "LICENSE")
    (package_dir / "README.md").write_text(
        package_readme(package, family, use, version), encoding="utf-8"
    )
    (package_dir / "package.json").write_text(
        json.dumps(package_json(package, family, version), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return package_dir


def verify_css(args):
    """Read one CSS file back from disk and compare it with the source fonts."""
    package_dir, css_name, sources = args
    css = (package_dir / f"{css_name}.css").read_text(encoding="utf-8")
    declared = {"normal": set(), "italic": set()}
    problems = []
    for line in css.splitlines():
        style = re.search(r"font-style:(\w+)", line).group(1)
        relative = SLICE_URL.search(line).group(1)
        expected = parse_unicode_range(re.search(r"unicode-range:([^}]+)", line).group(1))
        slice_path = package_dir / relative
        if not slice_path.is_file():
            problems.append(f"missing {relative}")
            continue
        actual = font_codepoints(slice_path)
        if actual != expected:
            problems.append(f"{relative} holds {len(actual)} codepoints, CSS says {len(expected)}")
        if declared[style] & expected:
            problems.append(f"{relative} overlaps another slice")
        declared[style] |= expected
    for style, source_path in sources.items():
        source = font_codepoints(source_path)
        if declared[style] != source:
            problems.append(f"{source_path.name}: CSS covers {len(declared[style])} of {len(source)}")
    return problems


def report(package_dir, pool, prefix, build_dir, with_static=True):
    jobs = [(package_dir, "variable", variable_sources(build_dir, prefix))]
    if with_static:
        jobs += [(package_dir, str(weight), static_sources(build_dir, prefix, name))
                 for name, weight in WEIGHTS.items()]
    problems = [p for result in pool.map(verify_css, jobs) for p in result]
    files = [p for p in package_dir.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    slices = [p for p in files if p.suffix == ".woff2"]
    variable = [p for p in slices if "variable" in p.parts]
    print(
        f"{package_dir.name}: {len(slices)} slices, {len(files)} files, {total / 1e6:.1f} MB "
        f"(variable {sum(p.stat().st_size for p in variable) / 1e6:.1f} MB), "
        f"largest slice {max(p.stat().st_size for p in slices) / 1e3:.0f} KB"
    )
    if total > JSDELIVR_PACKAGE_LIMIT:
        problems.append(f"{total / 1e6:.1f} MB is over the jsDelivr package limit")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    return not problems


def default_version():
    config = json.loads((ROOT / "ninter.config.json").read_text(encoding="utf-8"))
    major, minor = config["version"].split(".")
    return f"{int(major)}.{int(minor)}.0"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=default_version(), help="npm version (default: from ninter.config.json)")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "web", help="output folder")
    parser.add_argument("--build-dir", type=Path, default=BUILD_DIR,
                        help="folder with the TTFs and variable/ (default: build)")
    parser.add_argument("--skip-static", action="store_true",
                        help="only the variable font, to iterate faster (not for publishing)")
    args = parser.parse_args()

    with_static = not args.skip_static
    missing = [p for prefix, _, _ in PACKAGES.values()
               for p in variable_sources(args.build_dir, prefix).values() if not p.is_file()]
    if missing:
        raise SystemExit("Missing variable fonts, run scripts/build_variable.py first:\n  "
                         + "\n  ".join(str(p) for p in missing))

    table = load_slice_table()
    ok = True
    with ProcessPoolExecutor() as pool:
        for package, (prefix, family, use) in PACKAGES.items():
            package_dir = build_package(package, prefix, family, use, args.version, table,
                                        args.out, pool, args.build_dir, with_static)
            ok = report(package_dir, pool, prefix, args.build_dir, with_static) and ok
    if not ok:
        raise SystemExit("Web build finished with problems, see above.")
    print(f"Ready to publish version {args.version} from {args.out}")


if __name__ == "__main__":
    main()
