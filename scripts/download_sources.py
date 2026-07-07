#!/usr/bin/env python3
"""Download the OFL source fonts (Inter Roman/Italic, Noto Sans JP) into ./sources."""
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")

FILES = {
    "Inter[opsz,wght].ttf":
        "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
    "Inter-Italic[opsz,wght].ttf":
        "https://github.com/google/fonts/raw/main/ofl/inter/Inter-Italic%5Bopsz,wght%5D.ttf",
    "NotoSansJP[wght].ttf":
        "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf",
}


def main() -> None:
    os.makedirs(SRC, exist_ok=True)
    for name, url in FILES.items():
        dest = os.path.join(SRC, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            print(f"  have {name}")
            continue
        print(f"  downloading {name} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"    -> {os.path.getsize(dest)//1024} KB")
    print("Sources ready in ./sources")


if __name__ == "__main__":
    main()
