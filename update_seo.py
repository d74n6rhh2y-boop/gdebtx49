#!/usr/bin/env python3
"""Sync all SEO surfaces in index.html (and sitemap.xml) from games.json.

What it touches, and nothing else:
  1. The <script type="application/ld+json"> block in index.html — the
     ItemList of VideoGame entries is rebuilt from games.json (name, url,
     genre, gamePlatform, datePublished, image) and the WebSite node's
     dateModified is set to today.
  2. The crawlable <noscript> catalog between <!--GAMES:START--> and
     <!--GAMES:END--> in index.html.
  3. The homepage <lastmod> in sitemap.xml.

Everything else (markup, CSS, JS, base64 assets) is left byte-for-byte
unchanged. Running twice in a row makes no further changes.
"""
import datetime
import html
import json
import re
import sys

GAMES_FILE = "games.json"
HTML_FILE = "index.html"
SITEMAP_FILE = "sitemap.xml"
SITE = "https://hexplay.games/"

PLATFORM = {"i": "iOS", "a": "Android", "r": "Roblox"}

LD_RE = re.compile(r'(<script type="application/ld\+json">)(.*?)(</script>)', re.S)
NOSCRIPT_RE = re.compile(r'(<!--GAMES:START-->)(.*?)(<!--GAMES:END-->)', re.S)


def years(game):
    return [p[1] for p in game.get("p", []) if len(p) > 1 and isinstance(p[1], int)]


def platforms(game):
    seen, out = set(), []
    for p in game.get("p", []):
        name = PLATFORM.get(p[0])
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def image_url(game):
    img = game.get("img")
    if not img:
        return None
    return img if str(img).startswith("http") else SITE + str(img)


def videogame(game):
    item = {"@type": "VideoGame", "name": game["title"], "url": game["url"]}
    genre = game.get("gameplay") or []
    if genre:
        item["genre"] = genre
    plats = platforms(game)
    if plats:
        item["gamePlatform"] = plats
    ys = years(game)
    if ys:
        item["datePublished"] = str(min(ys))
    img = image_url(game)
    if img:
        item["image"] = img
    return item


def noscript_list(games):
    rows = []
    for g in games:
        url = html.escape(g["url"], quote=True)
        title = html.escape(g["title"])
        meta = ", ".join(platforms(g))
        ys = years(g)
        if ys:
            meta += (" · " if meta else "") + str(min(ys))
        genre = g.get("gameplay") or []
        if genre:
            meta += " · " + html.escape(", ".join(genre))
        rows.append(
            f'<li><a href="{url}" rel="noopener">{title}</a>'
            + (f" — {meta}" if meta else "")
            + "</li>"
        )
    return "".join(rows)


def main() -> int:
    today = datetime.date.today().isoformat()
    with open(GAMES_FILE, encoding="utf-8") as f:
        games = json.load(f)
    with open(HTML_FILE, encoding="utf-8") as f:
        html_src = f.read()

    changed = False

    # 1. JSON-LD ------------------------------------------------------------
    m = LD_RE.search(html_src)
    if not m:
        print("No JSON-LD block in index.html — aborting.")
        return 1
    try:
        ld = json.loads(m.group(2))
    except json.JSONDecodeError as e:
        print(f"JSON-LD is not valid JSON, aborting: {e}")
        return 1
    if not isinstance(ld, list):
        print("JSON-LD is not a list, aborting.")
        return 1

    for node in ld:
        if isinstance(node, dict) and node.get("@type") == "WebSite":
            node["dateModified"] = today
            node.setdefault("inLanguage", "en")

    item_list = next(
        (o for o in ld if isinstance(o, dict) and o.get("@type") == "ItemList"), None
    )
    if item_list is None:
        print("No ItemList node in JSON-LD — aborting.")
        return 1
    item_list["numberOfItems"] = len(games)
    item_list["itemListElement"] = [
        {"@type": "ListItem", "position": i + 1, "item": videogame(g)}
        for i, g in enumerate(games)
    ]

    new_ld = json.dumps(ld, ensure_ascii=False, separators=(",", ":"))
    if new_ld != m.group(2):
        html_src = html_src[: m.start(2)] + new_ld + html_src[m.end(2):]
        json.loads(LD_RE.search(html_src).group(2))  # re-validate
        changed = True

    # 2. noscript catalog ---------------------------------------------------
    nm = NOSCRIPT_RE.search(html_src)
    if nm:
        new_rows = noscript_list(games)
        if new_rows != nm.group(2):
            html_src = (
                html_src[: nm.start(2)] + new_rows + html_src[nm.end(2):]
            )
            changed = True
    else:
        print("No <!--GAMES:START/END--> markers — skipping noscript list.")

    if changed:
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(html_src)
        print(f"index.html SEO updated: {len(games)} games.")
    else:
        print("index.html SEO already up to date.")

    # 3. sitemap homepage lastmod ------------------------------------------
    try:
        with open(SITEMAP_FILE, encoding="utf-8") as f:
            sm = f.read()
    except FileNotFoundError:
        print("sitemap.xml not found — skipping.")
        return 0

    def bump(match):
        return match.group(1) + today + match.group(3)

    sm2 = re.sub(
        r"(<loc>https://hexplay\.games/</loc>\s*<lastmod>)(.*?)(</lastmod>)",
        bump,
        sm,
        count=1,
        flags=re.S,
    )
    if sm2 != sm:
        with open(SITEMAP_FILE, "w", encoding="utf-8") as f:
            f.write(sm2)
        print(f"sitemap.xml homepage lastmod set to {today}.")
    else:
        print("sitemap.xml already up to date.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
