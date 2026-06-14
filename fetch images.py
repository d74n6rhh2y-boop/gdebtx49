#!/usr/bin/env python3
"""
Fill games.json `img` fields by pulling each game's official preview image
from its site (same source Telegram uses for link previews).

Cascade per game:
  og:image  ->  twitter:image  ->  apple-touch-icon / icon  ->  (leave empty)

Run via GitHub Actions; it rewrites games.json in place.
Only games missing a usable img are fetched, so re-runs are cheap.
"""
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(HERE, "games.json")

UA = ("Mozilla/5.0 (compatible; hexplay-bot/1.0; +https://hexplay.games)")
TIMEOUT = 15
MIN_ICON = 180          # ignore icons smaller than this (px) when used as fallback


class MetaParser(HTMLParser):
    """Collect candidate image URLs from <meta> and <link> tags."""
    def __init__(self):
        super().__init__()
        self.og = None
        self.tw = None
        self.apple = None
        self.icon = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            content = a.get("content")
            if not content:
                return
            if prop == "og:image" and not self.og:
                self.og = content
            elif prop in ("twitter:image", "twitter:image:src") and not self.tw:
                self.tw = content
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            href = a.get("href")
            if not href:
                return
            if "apple-touch-icon" in rel and not self.apple:
                self.apple = href
            elif rel in ("icon", "shortcut icon") and not self.icon:
                self.icon = href


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
        raw = r.read(400_000)  # first ~400KB is plenty for <head>
    # decode best-effort
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return None


def best_image(url):
    """Return the best preview image URL for a game's official site."""
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
    # cascade: og -> twitter -> apple-touch -> icon
    for cand in (p.og, p.tw, p.apple, p.icon):
        if cand:
            return absolutize(url, cand)
    return None


def main():
    games = json.load(open(GAMES, encoding="utf-8"))
    updated = 0
    failed = []
    for i, g in enumerate(games, 1):
        if g.get("img"):
            continue  # already has one
        url = g.get("url")
        if not url:
            continue
        print(f"[{i}/{len(games)}] {g['title']}")
        img = best_image(url)
        if img:
            g["img"] = img
            updated += 1
            print(f"   -> {img[:90]}")
        else:
            failed.append(g["title"])
            print("   -> none")

    json.dump(games, open(GAMES, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"\nDone. Added images: {updated}. No image: {len(failed)}.")
    if failed:
        print("Without image:", ", ".join(failed[:40]),
              ("..." if len(failed) > 40 else ""))


if __name__ == "__main__":
    main()
