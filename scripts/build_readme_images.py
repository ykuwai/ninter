#!/usr/bin/env python3
"""Draw the README images as SVG from the finished fonts in build/.

Text becomes outlines, so an image looks the same without the font installed.
Backgrounds stay transparent and each SVG carries its own light and dark
colors, which lets it follow the color scheme of the page around it.

Requires: pip install fonttools uharfbuzz
"""
import math
from pathlib import Path

import uharfbuzz as hb
from fontTools.misc.transform import Transform
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
OUT_DIR = ROOT / "docs" / "images"

WIDTH = 1600
MARGIN = 72
FAUX_ITALIC_DEGREES = 18  # about what Word and PowerPoint apply with Ctrl+I

STYLE = (
    "<style>.ink{fill:#1c1816}.sub{fill:#776d67}.a{stop-color:#9e2a2b}.b{stop-color:#c8553d}"
    "@media (prefers-color-scheme:dark){.ink{fill:#f6f2ef}.sub{fill:#a2968f}"
    ".a{stop-color:#e58a7f}.b{stop-color:#f0ae86}}</style>"
)
GRADIENT = (
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
    '<stop class="a" offset="0"/><stop class="b" offset="1"/></linearGradient></defs>'
)


def number(value):
    return f"{value:.1f}".rstrip("0").rstrip(".")


class Face:
    _loaded = {}

    def __new__(cls, name):
        if name not in cls._loaded:
            face = super().__new__(cls)
            path = BUILD_DIR / f"{name}.ttf"
            font = TTFont(path)
            face.glyphs = font.getGlyphSet()
            face.order = font.getGlyphOrder()
            face.upem = font["head"].unitsPerEm
            face.shaper = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
            cls._loaded[name] = face
        return cls._loaded[name]

    def shape(self, text):
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(self.shaper, buffer)
        return buffer.glyph_infos, buffer.glyph_positions

    def width(self, text, size):
        _, positions = self.shape(text)
        return sum(p.x_advance for p in positions) * size / self.upem

    def outline(self, text, size, x, y, skew=0.0):
        scale = size / self.upem
        pen = SVGPathPen(self.glyphs, ntos=number)
        infos, positions = self.shape(text)
        cursor = 0
        for info, position in zip(infos, positions):
            matrix = Transform(
                scale, 0, scale * skew, -scale,
                x + (cursor + position.x_offset) * scale,
                y - position.y_offset * scale,
            )
            self.glyphs[self.order[info.codepoint]].draw(TransformPen(pen, matrix))
            cursor += position.x_advance
        return pen.getCommands()


class Canvas:
    def __init__(self, label, height):
        self.label = label
        self.height = height
        self.items = []

    def text(self, face, content, size, x, y, css="ink", skew=0.0):
        path = Face(face).outline(content, size, x, y, skew)
        fill = 'fill="url(#g)"' if css == "grad" else f'class="{css}"'
        self.items.append(f'<path {fill} d="{path}"/>')

    def centered(self, face, content, size, center, y, css="ink"):
        self.text(face, content, size, center - Face(face).width(content, size) / 2, y, css)

    def save(self, name):
        defs = GRADIENT if any('url(#g)' in item for item in self.items) else ""
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {self.height}" '
            f'role="img" aria-label="{self.label}">{STYLE}{defs}{"".join(self.items)}</svg>\n'
        )
        (OUT_DIR / name).write_text(svg, encoding="utf-8")
        print(f"{name}: {len(svg) / 1000:.0f} KB")


def hero():
    canvas = Canvas("Ninter 斜体に対応した日本語フォント", 500)
    canvas.centered("NinterP-BlackItalic", "Ninter", 340, WIDTH / 2, 310, "grad")
    canvas.centered("NinterP-BoldItalic", "斜体に対応した日本語フォント", 68, WIDTH / 2, 450)
    canvas.save("hero.svg")


def compare():
    canvas = Canvas("疑似イタリックと Ninter の斜体の比較", 250)
    skew = math.tan(math.radians(FAUX_ITALIC_DEGREES))
    left, right = MARGIN, WIDTH / 2 + 28
    canvas.text("NinterP-Medium", "疑似イタリック", 28, left, 52, "sub")
    canvas.text("NinterP-Bold", "日本語の斜体", 116, left, 200, "sub", skew=skew)
    canvas.text("NinterP-Medium", "Ninter の斜体", 28, right, 52, "sub")
    canvas.text("NinterP-BoldItalic", "日本語の斜体", 116, right, 200, "grad")
    canvas.save("compare.svg")


def weights():
    canvas = Canvas("Thin から Black まで 9 つの太さの斜体", 170)
    names = ["Thin", "ExtraLight", "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"]
    column = (WIDTH - 2 * MARGIN) / len(names)
    for index, name in enumerate(names):
        center = MARGIN + column * (index + 0.5)
        canvas.centered(f"NinterP-{name}Italic", "斜体", 72, center, 86)
        canvas.centered("NinterP-Regular", str((index + 1) * 100), 22, center, 146, "sub")
    canvas.save("weights.svg")


if __name__ == "__main__":
    hero()
    compare()
    weights()
