#!/usr/bin/env python3
"""
Fill / refresh games.json `img` fields with each game's best preview art.

QUALITY MODE (full re-pass):
  - Re-checks EVERY game (not only empty ones).
  - Rejects junk: favicons, .ico, apple-touch-icon, logo192, data:-URIs,
    svg, tiny/placeholder icons, parastorage/flaticon stubs.
  - Cascade of real preview art: og:image -> twitter:image -> image_src
  - Keeps an existing img ONLY if it already looks like real art.

Run via GitHub Actions; rewrites games.json in place.
"""
import json
import os
import re
import urllib.request
import urllib.parse
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(HERE, "games.json")

UA = "Mozilla/5.0 (compatible; hexplay-bot/1.1; +https://hexplay.games)"
TIMEOUT = 15

BAD_SUBSTR = (
    "favicon", "apple-touch", "apple_touch", "/ico/", "icon-",
    "logo192", "logo180", "-icon", "_icon", "pfavico", "flaticon",
    "parastorage", "krone.ico", "/favicons/", "webclip", "pwa-icon",
    "android-chrome", "mstile", "safari-pinned", "logo.png",
)
BAD_EXT = (".ico", ".svg")


def is_bad_img(u):
    if not u:
        return True
    s = u.lower().strip()
    if s.startswith("data:"):
        return True
    path = urllib.parse.urlparse(s).path
    for ext in BAD_EXT:
        if path.endswith(ext):
            return True
    for sub in BAD_SUBSTR:
        if sub in s:
            return True
    m = re.search(r"(\d{2,4})x(\d{2,4})", s)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if max(w, h) < 200:
            return True
    if re.search(r"/(16|32|48|57|64|72|96|120|128|180|192)(\b|/|$)", path):
        return True
    return False


def looks_like_art(u):
    return bool(u) and not is_bad_img(u)


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og = None
        self.tw = None
        self.img_src = None
        self.og_secure = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            content = a.get("content")
            if not content:
                return
            if prop == "og:image" and not self.og:
                self.og = content
            elif prop == "og:image:secure_url" and not self.og_secure:
                self.og_secure = content
            elif prop in ("twitter:image", "twitter:image:src") and not self.tw:
                self.tw = content
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            href = a.get("href")
            if not href:
                return
            if "image_src" in rel and not self.img_src:
                self.img_src = href


def absolutize(base, url):
    if not url:
        return None
    return urllib.parse.urljoin(base, url)


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            return None
        raw = r.read(600_000)
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return None


def best_image(url):
    try:
        html = fetch_html(url)
    except Exception as e:
        print(f"   fetch fail: {e}")
        return None
    if not html:
        return None
    p = MetaParser()
    try:
        p.feed(html)
    except Exception:
        pass
    for cand in (p.og, p.og_secure, p.tw, p.img_src):
        if cand:
            full = absolutize(url, cand)
            if looks_like_art(full):
                return full
    return None


def main():
    games = json.load(open(GAMES, encoding="utf-8"))
    refreshed = 0
    kept = 0
    failed = []
    for i, g in enumerate(games, 1):
        url = g.get("url")
        cur = g.get("img")
        title = g.get("title", "?")

        if cur and looks_like_art(cur):
            kept += 1
            continue

        if not url:
            if cur:
                g.pop("img", None)
            failed.append(title)
            continue

        print(f"[{i}/{len(games)}] {title}"
              + ("  (replacing junk)" if cur else ""))
        img = best_image(url)
        if img:
            g["img"] = img
            refreshed += 1
            print(f"   -> {img[:90]}")
        else:
            g.pop("img", None)
            failed.append(title)
            print("   -> none (cleared)")

    json.dump(games, open(GAMES, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"\nDone. Kept good: {kept}. Refreshed: {refreshed}. "
          f"No art: {len(failed)}.")
    if failed:
        print("No art for:", ", ".join(failed[:60]),
              ("..." if len(failed) > 60 else ""))


if __name__ == "__main__":
    main()
