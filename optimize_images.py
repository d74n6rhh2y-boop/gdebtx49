#!/usr/bin/env python3
"""Make every card image small and local, and self-host the two web fonts.

Images: every `img` in games.json (external URL or local file) is converted
to WebP, max width 720px, quality 72, saved into img/ and games.json is
rewritten to point at the local .webp. Originals (jpeg/png >WebP) are
deleted once replaced. Idempotent: already-optimized .webp files are kept.

Fonts (--fonts): downloads Unbounded 600/800 + Space Mono 400/700 latin
WOFF2 from Google Fonts into fonts/ so the site never depends on
fonts.googleapis.com at runtime.

Run in GitHub Actions after fetch_images.py (network required for external
images/fonts). Locally it still optimizes whatever is on disk and skips
downloads that fail.
"""
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(HERE, "games.json")
IMG_DIR = os.path.join(HERE, "img")
FONT_DIR = os.path.join(HERE, "fonts")

MAX_W = 960          # 3x card width - retina headroom, no visible loss
QUALITY = 82
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
TIMEOUT = 20
LOCAL_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


def slug(title):
    s = re.sub(r"[^\w\s-]", "", title, flags=re.U).strip().lower()
    return re.sub(r"[\s_]+", " ", s) or "game"


def to_webp(data, dst):
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGB")
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    im.save(dst, "WEBP", quality=QUALITY, method=6)
    return os.path.getsize(dst)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def local_path(img_field):
    """img/foo%20bar.jpeg -> absolute path, or None if not a local ref."""
    if not img_field or img_field.startswith("http"):
        return None
    rel = urllib.parse.unquote(img_field)
    p = os.path.join(HERE, rel)
    return p if os.path.isfile(p) else None


def optimized(path):
    """Already a small-enough webp?"""
    if not path.lower().endswith(".webp"):
        return False
    try:
        with Image.open(path) as im:
            return im.width <= MAX_W
    except Exception:
        return False


def main():
    with open(GAMES, encoding="utf-8") as f:
        games = json.load(f)
    os.makedirs(IMG_DIR, exist_ok=True)

    changed = converted = downloaded = failed = 0
    for g in games:
        img = g.get("img")
        if not img:
            continue
        src_local = local_path(img)

        stem = slug(g["title"])
        dst = os.path.join(IMG_DIR, stem + ".webp")
        rel = "img/" + urllib.parse.quote(stem + ".webp")

        if src_local and optimized(src_local):
            # already fine — just enforce the lowercase slug name
            if os.path.abspath(src_local) != os.path.abspath(dst):
                os.replace(src_local, dst)
            if g["img"] != rel:
                g["img"] = rel
                changed += 1
            continue

        try:
            if src_local:
                data = open(src_local, "rb").read()
            else:
                data = fetch(img)
                downloaded += 1
        except Exception as e:
            print(f"skip ({e.__class__.__name__}): {g['title']}")
            failed += 1
            continue

        try:
            size = to_webp(data, dst)
        except Exception as e:
            print(f"convert failed ({e}): {g['title']}")
            failed += 1
            continue

        converted += 1
        if src_local and os.path.abspath(src_local) != os.path.abspath(dst):
            os.remove(src_local)                     # replaced by the .webp
        if g["img"] != rel:
            g["img"] = rel
            changed += 1
        print(f"{size // 1024:>4} KB  {g['title']}")

    if changed:
        with open(GAMES, "w", encoding="utf-8") as f:
            f.write("[\n" + ",\n".join(
                json.dumps(x, separators=(",", ":"), ensure_ascii=False)
                for x in games) + "\n]")
    print(f"converted {converted} (downloaded {downloaded}, failed {failed}), "
          f"games.json paths updated: {changed}")


FONTS = {
    "unbounded-600.woff2": "family=Unbounded:wght@600",
    "unbounded-800.woff2": "family=Unbounded:wght@800",
    "space-mono-400.woff2": "family=Space+Mono:wght@400",
    "space-mono-700.woff2": "family=Space+Mono:wght@700",
}


def get_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    for fname, fam in FONTS.items():
        dst = os.path.join(FONT_DIR, fname)
        if os.path.exists(dst):
            continue
        css = fetch(f"https://fonts.googleapis.com/css2?{fam}&display=swap").decode()
        # last latin block in the css2 payload is the plain-latin subset
        urls = re.findall(r"src: url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css)
        if not urls:
            print(f"no woff2 url for {fname}")
            continue
        open(dst, "wb").write(fetch(urls[-1]))
        print(f"fonts/{fname}  {os.path.getsize(dst) // 1024} KB")


if __name__ == "__main__":
    if "--fonts" in sys.argv:
        get_fonts()
    if "--fonts-only" not in sys.argv:
        main()
