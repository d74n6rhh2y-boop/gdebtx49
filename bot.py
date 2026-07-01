#!/usr/bin/env python3
"""hexplay pick bot — posts a random game ("pick for me" style) to Telegram, Bluesky, and X.

Fetches games.json from the live site, picks a game (every game is shown once
before any repeats — see bot_state.json), and posts to whichever platforms have
credentials set.

Env (a platform is used only if its vars are present):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL                     (e.g. @hexplay)
  BLUESKY_HANDLE, BLUESKY_APP_PASSWORD                     (handle e.g. hexplay.bsky.social)
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET (paid pay-per-use; optional)
  DRY_RUN=1   -> print posts instead of sending
"""
import os, json, random, sys, tempfile, html, datetime, calendar, urllib.request

HERE        = os.path.dirname(os.path.abspath(__file__))
STATE       = os.path.join(HERE, "bot_state.json")  # post history: cycle through all before repeating
GAMES_URL   = "https://hexplay.games/games.json"
SITE        = "hexplay.games"
SITE_URL    = "https://hexplay.games"
PLAT_LETTER = {"i": "A", "a": "G", "r": "R"}   # App Store / Google Play / Roblox


def fetch_games():
    req = urllib.request.Request(GAMES_URL, headers={"User-Agent": "hexplay-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_posted():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return set(json.load(fh).get("posted", []))
    except Exception:
        return set()


def save_posted(posted):
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump({"posted": sorted(posted)}, fh, ensure_ascii=False, indent=0)


def choose(games, posted):
    """Pick a game not yet posted this cycle. Once every game has been posted,
    start a fresh cycle. Newly added games join the current cycle automatically."""
    pool = [g for g in games if g.get("url")]        # must have a link to share
    titles = {g["title"] for g in pool}
    posted = set(posted) & titles                    # forget games no longer listed
    remaining = [g for g in pool if g["title"] not in posted]
    if not remaining:                                # whole list done -> new cycle
        posted, remaining = set(), pool
    g = random.choice(remaining)
    posted.add(g["title"])
    return g, posted


def image_url(g):
    img = g.get("img")
    if not img:
        return None
    return img if img.startswith("http") else f"{SITE_URL}/{img}"


# ---------- formatting ----------
def plat_letters(g):
    codes = {code for code, _ in g.get("p", [])}
    return "".join(PLAT_LETTER[c] for c in ("i", "a", "r") if c in codes)


def years_str(g):
    ys = sorted({y for _, y in g.get("p", [])})
    return "/".join(str(y) for y in ys)


def meta_line(g):
    base = " ".join(x for x in (plat_letters(g), years_str(g)) if x)
    if g.get("pick"):
        base = (base + " #hexplay").strip()
    return base


def hashtag_lines(g):
    out = []
    for cat in (g.get("gameplay"), g.get("features"), g.get("modes")):
        if cat:
            out.append(" ".join("#" + t.replace(" ", "") for t in cat))
    return out


def telegram_html(g):
    esc = lambda s: html.escape(s, quote=False)
    lines = [f'<b>{esc(g["title"])}</b>']
    m = meta_line(g)
    if m:
        lines.append(esc(m))
    lines += hashtag_lines(g)
    lines += ["", f'// play better \u2022 <a href="{SITE_URL}">{SITE}</a>']
    return "\n".join(lines)


def tweet_x(g):
    lines = [g["title"]]
    m = meta_line(g)
    if m:
        lines.append(m)
    lines += hashtag_lines(g)
    lines += ["", f"// play better \u2022 {SITE}"]
    return "\n".join(lines)


# ---------- senders ----------
def post_telegram(g):
    import requests
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    channel = os.environ["TELEGRAM_CHANNEL"]
    api     = f"https://api.telegram.org/bot{token}"
    cap     = telegram_html(g)
    photo   = image_url(g)
    if photo:
        r = requests.post(f"{api}/sendPhoto",
            data={"chat_id": channel, "photo": photo, "caption": cap, "parse_mode": "HTML"}, timeout=30)
        if r.ok:
            return "telegram: photo sent"
    r = requests.post(f"{api}/sendMessage",
        data={"chat_id": channel, "text": cap, "parse_mode": "HTML", "disable_web_page_preview": "false"}, timeout=30)
    r.raise_for_status()
    return "telegram: text sent"


def post_x(g):
    import tweepy
    k = (os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
         os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])
    client = tweepy.Client(consumer_key=k[0], consumer_secret=k[1],
                           access_token=k[2], access_token_secret=k[3])
    media_ids = None
    url = image_url(g)
    if url:
        try:
            api_v1 = tweepy.API(tweepy.OAuth1UserHandler(*k))
            ext = os.path.splitext(url.split("?")[0])[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                ext = ".jpg"
            req = urllib.request.Request(url, headers={"User-Agent": "hexplay-bot"})
            with urllib.request.urlopen(req, timeout=30) as r, \
                 tempfile.NamedTemporaryFile(suffix=ext) as fh:   # auto-deleted
                fh.write(r.read())
                fh.flush()
                media_ids = [api_v1.media_upload(fh.name).media_id]
        except Exception as e:
            print(f"x: media skipped ({e})")
            media_ids = None
    client.create_tweet(text=tweet_x(g), media_ids=media_ids)
    return "x: tweeted" + (" with image" if media_ids else "")


def _bsky_richtext(g):
    """Same layout as the other platforms, with clickable link + hashtags (facets)."""
    from atproto import client_utils
    tb = client_utils.TextBuilder()
    tb.text(g["title"] + "\n")
    meta = " ".join(x for x in (plat_letters(g), years_str(g)) if x)
    tb.text(meta)
    if g.get("pick"):
        tb.text(" ").tag("#hexplay", "hexplay")
    tb.text("\n")
    for cat in (g.get("gameplay"), g.get("features"), g.get("modes")):
        if cat:
            for i, t in enumerate(cat):
                tag = t.replace(" ", "")
                (tb.text(" ") if i else tb).tag("#" + tag, tag)
            tb.text("\n")
    tb.text("\n// play better \u2022 ").link(SITE, SITE_URL)
    return tb


def post_bluesky(g):
    from atproto import Client
    client = Client()
    client.login(os.environ["BLUESKY_HANDLE"], os.environ["BLUESKY_APP_PASSWORD"])
    rt = _bsky_richtext(g)
    url = image_url(g)
    if url:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hexplay-bot"})
            with urllib.request.urlopen(req, timeout=30) as r:
                img = r.read()
            if img and len(img) <= 976_000:                 # Bluesky blob limit ~1MB
                client.send_image(text=rt, image=img, image_alt=g["title"])
                return "bluesky: image posted"
            print("bluesky: image too large, posting text only")
        except Exception as e:
            print(f"bluesky: image skipped ({e})")
    client.send_post(text=rt)
    return "bluesky: posted"


# ---------- main ----------
def is_rest_day(d):
    """No post on the 5th/10th/15th/20th/25th/30th. February has no 30th, so its
    last day (28 or 29) stands in for it."""
    if d.day in (5, 10, 15, 20, 25, 30):
        return True
    return d.month == 2 and d.day == calendar.monthrange(d.year, 2)[1]


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    if os.environ.get("EVENT") == "schedule":          # rest days apply to the schedule only
        today = datetime.date.today()                  # runner is UTC (cron fires 17:00 UTC)
        if is_rest_day(today):
            print(f"{today} is a rest day (5/10/15/20/25/30) — no post")
            return
    games = fetch_games()
    posted = load_posted()
    g, posted = choose(games, posted)
    total = sum(1 for x in games if x.get("url"))
    print(f"picked: {g['title']}  ({len(posted)}/{total} this cycle)")

    if dry:
        print("\n--- TELEGRAM (HTML) ---\n" + telegram_html(g))
        print("\n--- X ---\n" + tweet_x(g))
        print("\n--- BLUESKY ---\n" + _bsky_richtext(g).build_text())
        print(f"\nimage: {image_url(g)}")
        return                                  # dry run: do not consume the game

    targets = []
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHANNEL"):
        targets.append(post_telegram)
    if all(os.environ.get(v) for v in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")):
        targets.append(post_x)
    if os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD"):
        targets.append(post_bluesky)
    if not targets:
        sys.exit("no credentials set for any platform")

    posted_ok = failed = False
    for send in targets:
        try:
            print(send(g))
            posted_ok = True
        except Exception as e:
            failed = True
            print(f"ERROR in {send.__name__}: {e}")
    if posted_ok:
        save_posted(posted)                     # mark consumed only if something went out
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
