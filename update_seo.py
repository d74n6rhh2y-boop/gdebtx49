#!/usr/bin/env python3
"""Sync the JSON-LD VideoGame list in index.html with games.json.

Only the <script type="application/ld+json"> block is touched. The rest of
index.html (markup, CSS, JS, base64 assets) is left byte-for-byte unchanged.
"""
import json
import re
import sys

GAMES_FILE = "games.json"
HTML_FILE = "index.html"
LD_RE = re.compile(
    r'(<script type="application/ld\+json">)(.*?)(</script>)', re.S
)


def main() -> int:
    with open(GAMES_FILE, encoding="utf-8") as f:
        games = json.load(f)

    with open(HTML_FILE, encoding="utf-8") as f:
        html = f.read()

    m = LD_RE.search(html)
    if not m:
        print("No JSON-LD block found in index.html — nothing to do.")
        return 0

    try:
        ld = json.loads(m.group(2))
    except json.JSONDecodeError as e:
        print(f"JSON-LD is not valid JSON, aborting: {e}")
        return 1

    # ld is expected to be a list of schema objects (WebSite, FAQPage, ItemList)
    if not isinstance(ld, list):
        print("JSON-LD is not a list, aborting.")
        return 1

    item_list = next(
        (o for o in ld if isinstance(o, dict) and o.get("@type") == "ItemList"),
        None,
    )
    if item_list is None:
        print("No ItemList object in JSON-LD — nothing to do.")
        return 0

    item_list["numberOfItems"] = len(games)
    item_list["itemListElement"] = [
        {
            "@type": "ListItem",
            "position": i + 1,
            "item": {"@type": "VideoGame", "name": g["title"], "url": g["url"]},
        }
        for i, g in enumerate(games)
    ]

    new_ld = json.dumps(ld, ensure_ascii=False, separators=(",", ":"))
    if new_ld == m.group(2):
        print("SEO list already up to date.")
        return 0

    new_html = html[: m.start(2)] + new_ld + html[m.end(2):]

    # safety: make sure result still parses
    json.loads(LD_RE.search(new_html).group(2))

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"SEO list updated: {len(games)} games.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
