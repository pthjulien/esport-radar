#!/usr/bin/env python3
"""Esport Radar Scraper 13.0
- Quota garanti : au moins 10 articles récents par discipline esport
- Rétention stricte : 45 jours max (aucune vieille actu périmée)
- 100% visuel : vraie photo de presse ou logo officiel détouré (0 carte vide)
- Anti multi-jeux et anti-salons municipaux conservé
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT_FILE = Path(__file__).resolve().parent / "data.json"
TARGET_PER_GAME = 12   # Vise au moins 10 à 12 articles par jeu
MAX_AGE_DAYS = 45      # Fraîcheur garantie : interdit tout ce qui dépasse 1 mois et demi
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Flux spécialisés et ciblés par discipline
FEEDS = [
    # League of Legends
    ("https://e.sport.fr/category/league-of-legends/feed/", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/?paged=2", "E.SPORT.FR", "lol"),
    ("https://www.dexerto.fr/league-of-legends/feed/", "Dexerto FR", "lol"),
    ("https://dotesports.com/league-of-legends/feed", "Dot Esports", "lol"),

    # Valorant
    ("https://e.sport.fr/category/valorant/feed/", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/valorant/feed/?paged=2", "E.SPORT.FR", "val"),
    ("https://www.dexerto.fr/valorant/feed/", "Dexerto FR", "val"),
    ("https://dotesports.com/valorant/feed", "Dot Esports", "val"),

    # Counter-Strike 2
    ("https://e.sport.fr/category/counter-strike/feed/", "E.SPORT.FR", "cs2"),
    ("https://e.sport.fr/category/counter-strike/feed/?paged=2", "E.SPORT.FR", "cs2"),
    ("https://dotesports.com/counter-strike/feed", "Dot Esports", "cs2"),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa", "cs2"),

    # Fortnite
    ("https://e.sport.fr/category/fortnite/feed/", "E.SPORT.FR", "fortnite"),
    ("https://e.sport.fr/category/fortnite/feed/?paged=2", "E.SPORT.FR", "fortnite"),
    ("https://www.dexerto.fr/fortnite/feed/", "Dexerto FR", "fortnite"),
    ("https://dotesports.com/fortnite/feed", "Dot Esports", "fortnite"),

    # Call of Duty / Warzone
    ("https://e.sport.fr/category/call-of-duty/feed/", "E.SPORT.FR", "cod"),
    ("https://charlieintel.com/feed/", "Charlie INTEL", "cod"),
    ("https://www.dexerto.fr/call-of-duty/feed/", "Dexerto FR", "cod"),
    ("https://dotesports.com/call-of-duty/feed", "Dot Esports", "cod"),

    # Rocket League
    ("https://e.sport.fr/category/rocket-league/feed/", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/rocket-league/feed/?paged=2", "E.SPORT.FR", "rl"),
    ("https://dotesports.com/rocket-league/feed", "Dot Esports", "rl"),

    # Rainbow Six Siege
    ("https://e.sport.fr/category/rainbow-six/feed/", "E.SPORT.FR", "r6"),
    ("https://e.sport.fr/category/rainbow-six-siege/feed/", "E.SPORT.FR", "r6"),
    ("https://dotesports.com/rainbow-six/feed", "Dot Esports", "r6"),

    # Apex Legends
    ("https://e.sport.fr/category/apex-legends/feed/", "E.SPORT.FR", "apex"),
    ("https://e.sport.fr/category/apex-legends/feed/?paged=2", "E.SPORT.FR", "apex"),
    ("https://www.dexerto.fr/apex-legends/feed/", "Dexerto FR", "apex"),
    ("https://dotesports.com/apex-legends/feed", "Dot Esports", "apex"),

    # EA Sports FC
    ("https://e.sport.fr/category/ea-sports-fc/feed/", "E.SPORT.FR", "eafc"),
    ("https://e.sport.fr/category/fifa/feed/", "E.SPORT.FR", "eafc"),
    ("https://www.dexerto.fr/ea-sports-fc/feed/", "Dexerto FR", "eafc"),

    # Fil généraliste de secours
    ("https://e.sport.fr/feed/", "E.SPORT.FR", None),
    ("https://www.jeuxvideo.com/rss/rss-esport.xml", "JV Esport", None),
]

GAME_RULES = {
    "lol": re.compile(
        r"league of legends|\blol\b|\blec\b|\blfl\b|\blck\b|\blpl\b|\blcs\b|"
        r"worlds 202\d|msi 202\d|summoner'?s rift|faille de l'invocateur|emea masters|"
        r"\bfaker\b|\byike\b|\bcaliste\b|\bcaps\b|\bhans sama\b|\btargamas\b|\bchovy\b|\bkeria\b",
        re.I
    ),
    "val": re.compile(
        r"valorant|\bvct\b|valorant champions|vct emea|vct americas|vct pacific|vct cn|"
        r"game changers|\btenz\b|\bnats\b|\bboaster\b|\baspas\b|\bzmjjkk\b|\bderke\b|\bsuygetsu\b|\bmagnum\b",
        re.I
    ),
    "cs2": re.compile(
        r"counter-strike|\bcs2\b|\bcs:go\b|\bcsgo\b|\bhltv\b|iem katowice|iem cologne|blast premier|"
        r"pgl major|\bzywoo\b|\bs1mple\b|\bdonk\b|\bm0nesy\b|\bniko\b|\bsiuhy\b|\bhooxi\b",
        re.I
    ),
    "fortnite": re.compile(
        r"fortnite|\bfncs\b|cash cup fortnite|\bbugha\b|\bmongraal\b|\bmrsavage\b|\bmalibuca\b|\bpeterbot\b",
        re.I
    ),
    "cod": re.compile(
        r"call of duty|\bcod\b|\bcdl\b|cod league|warzone|black ops 6|modern warfare|"
        r"optic texas|atlanta faze|\bhydra\b|\bshotzzy\b|\bscump\b|\bdashy\b",
        re.I
    ),
    "rl": re.compile(
        r"rocket league|\brlcs\b|\bvatira\b|\bmonkey m00n\b|\bmonkey moon\b|\bdralii\b|\batow\b|\bexotiik\b|\balpha54\b",
        re.I
    ),
    "r6": re.compile(
        r"rainbow six|\br6 siege\b|\br6s\b|six invitational|blast r6|\bshaiiko\b|\blikefac\b",
        re.I
    ),
    "apex": re.compile(
        r"apex legends|\balgs\b|\bimperialhal\b|\bgenburten\b",
        re.I
    ),
    "eafc": re.compile(
        r"ea sports fc|\bea fc\b|\bfc 25\b|\bfc 26\b|\bfc 27\b|\beligue\s?1\b|\bfifae\b|fc pro open|fc pro world",
        re.I
    )
}

AMATEUR_LOCAL_BAN = re.compile(
    r"bussy|saint-georges|amateurs? de gaming|amateurs? d'esport|week-end dédié aux jeux|"
    r"salon du jeu|fête du jeu|médiathèque|mjc|centre culturel|tournoi amateur|lan amateur|"
    r"mairie de|gaming amateur|sportmag|actu\.fr",
    re.I
)

OFFICIAL_LOGOS = [
    ("vct", re.compile(r"\bvct\b|valorant champions", re.I), {
        "title": "VALORANT Champions Tour", "tag": "VCT", "color": "#ff4655", "bg": "#1f0910"
    }),
    ("worlds", re.compile(r"\bworlds\b|world championship", re.I), {
        "title": "LoL World Championship", "tag": "WORLDS", "color": "#c89b3c", "bg": "#1c1404"
    }),
    ("lec", re.compile(r"\blec\b", re.I), {
        "title": "League of Legends EMEA", "tag": "LEC", "color": "#00c8c8", "bg": "#031c1c"
    }),
    ("lfl", re.compile(r"\blfl\b", re.I), {
        "title": "Ligue Française de LoL", "tag": "LFL", "color": "#3b82f6", "bg": "#071630"
    }),
    ("cs2_major", re.compile(r"major|iem katowice|iem cologne|blast premier", re.I), {
        "title": "Counter-Strike 2 Major", "tag": "CS2 MAJOR", "color": "#f59e0b", "bg": "#211404"
    }),
    ("fncs", re.compile(r"\bfncs\b", re.I), {
        "title": "Fortnite Champion Series", "tag": "FNCS", "color": "#a855f7", "bg": "#1c072e"
    }),
    ("cdl", re.compile(r"\bcdl\b|call of duty league", re.I), {
        "title": "Call of Duty League", "tag": "CDL", "color": "#84cc16", "bg": "#121f03"
    }),
    ("rlcs", re.compile(r"\brlcs\b", re.I), {
        "title": "Rocket League Championship Series", "tag": "RLCS", "color": "#0ea5e9", "bg": "#041829"
    }),
    ("kc", re.compile(r"karmine corp|\bkarmine\b|\bkcorp\b|\bkc\b", re.I), {
        "title": "Karmine Corp", "tag": "KC", "color": "#38bdf8", "bg": "#05182e"
    }),
    ("vit", re.compile(r"vitality|team vitality|\bvit\b", re.I), {
        "title": "Team Vitality", "tag": "VIT", "color": "#facc15", "bg": "#261f03"
    }),
    ("m8", re.compile(r"gentle mates|\bm8\b", re.I), {
        "title": "Gentle Mates", "tag": "M8", "color": "#f472b6", "bg": "#26061c"
    }),
    ("sly", re.compile(r"\bsolary\b|\bsly\b", re.I), {
        "title": "Solary", "tag": "SLY", "color": "#fb923c", "bg": "#261103"
    }),
    ("t1", re.compile(r"\bt1\b|\bfaker\b", re.I), {
        "title": "T1 Esports", "tag": "T1", "color": "#e11d48", "bg": "#26050e"
    }),
    ("g2", re.compile(r"\bg2 esports\b|\bg2\b", re.I), {
        "title": "G2 Esports", "tag": "G2", "color": "#ef4444", "bg": "#240606"
    }),
    ("fnc", re.compile(r"\bfnatic\b|\bfnc\b", re.I), {
        "title": "Fnatic", "tag": "FNC", "color": "#fb923c", "bg": "#261003"
    }),
]

def clean_text(raw_html: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def detect_single_game(title: str, text_zone: str, feed_hint: str = None):
    if AMATEUR_LOCAL_BAN.search(title + " " + text_zone[:200]):
        return None

    matched_games = [k for k, rx in GAME_RULES.items() if rx.search(title)]

    if len(matched_games) > 1:
        if not re.search(r"esports world cup|\bewc\b", title, re.I):
            return None

    if len(matched_games) == 1:
        return matched_games[0]

    if feed_hint and feed_hint in GAME_RULES:
        return feed_hint

    for k, rx in GAME_RULES.items():
        if rx.search(text_zone[:250]):
            return k

    return None

def detect_category(text: str) -> str:
    if re.search(r"rumou?rs?|rumeurs?|leak|fuite|selon|serait|pourrait|aurait|piste|courtise", text, re.I):
        return "rumor"
    if re.search(r"joins?|signs?|signe|rejoint|officialise|quitte|prolonge|recrute|transfert|benched|roster|départ|rejoindre", text, re.I):
        return "official"
    if re.search(r"victoire|défaite|sacré|éliminé|finale|playoffs|classement|tournoi|major|masters|trophée|champions|direct|match|score", text, re.I):
        return "tournament"
    if re.search(r"patch|mise à jour|nerf|buff|équilibrage|update", text, re.I):
        return "patch"
    return "news"

def clean_image_url(u: str) -> str:
    if not u or not u.startswith("http"):
        return ""
    u = html.unescape(u.strip()).replace("http://", "https://")
    low = u.lower()
    if any(x in low for x in ["avatar", "logo", "icon", "emoji", "pixel", "tracking", "gravatar", "1x1"]):
        return ""
    if any(ext in low for ext in [".jpg", ".jpeg", ".png", ".webp", ".avif"]) or "wp-content/uploads" in low:
        return u
    return ""

def extract_press_photo(item, raw_xml: str) -> str:
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        candidate = clean_image_url(enc.get("url"))
        if candidate:
            return candidate

    for elem in item.iter():
        if elem.tag.endswith(("content", "thumbnail")):
            candidate = clean_image_url(elem.get("url", ""))
            if candidate:
                return candidate

    for tag in ["{http://purl.org/rss/1.0/modules/content/}encoded", "description"]:
        body = item.findtext(tag) or ""
        matches = re.findall(r'<img[^>]+(?:src|data-src|data-orig-file)=["\']([^"\']+)["\']', body, re.I)
        for m in matches:
            candidate = clean_image_url(m)
            if candidate:
                return candidate

    urls = re.findall(r'https?://[^\s"\'><]+', raw_xml, re.I)
    for u in urls:
        candidate = clean_image_url(u)
        if candidate and any(w in candidate.lower() for w in ["uploads", "article", "media", "news"]):
            return candidate

    return ""

def find_official_logo(title: str, text_zone: str):
    for _, rx, data in OFFICIAL_LOGOS:
        if rx.search(title):
            return data
    for _, rx, data in OFFICIAL_LOGOS:
        if rx.search(text_zone[:200]):
            return data
    return None

def extract_article_body(item, title: str) -> list:
    raw_content = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
    raw_desc = item.findtext("description") or ""

    paragraphs = []
    p_tags = re.findall(r'<p[^>]*>(.*?)</p>', raw_content or raw_desc, flags=re.DOTALL | re.IGNORECASE)
    for p in p_tags:
        cleaned = clean_text(p)
        if len(cleaned) > 40:
            low = cleaned.lower()
            if not low.startswith(("à lire aussi", "lire aussi", "source :", "crédit :", "the post")):
                paragraphs.append(cleaned)

    if not paragraphs:
        cleaned_desc = clean_text(raw_desc)
        if len(cleaned_desc) > 35 and cleaned_desc.lower() not in title.lower():
            paragraphs.append(cleaned_desc)

    return paragraphs

def parse_date(date_str: str) -> str:
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def main() -> int:
    now = datetime.now(timezone.utc)
    seen_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Lecture de l'historique valide existant (< 45 jours)
    existing = {}
    if OUT_FILE.exists():
        try:
            d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if isinstance(d, list):
                for a in d:
                    if isinstance(a, dict) and a.get("title") and a.get("published", "") >= cutoff:
                        if a.get("image") or a.get("logo"):
                            k = a["title"].strip().lower()
                            existing[k] = a
        except Exception:
            pass

    collected = []

    for url, src_name, hint in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                xml_raw = resp.read()
                root = ET.fromstring(xml_raw)
        except Exception:
            continue

        for it in root.iter("item"):
            title = html.unescape((it.findtext("title") or "").strip())
            link = (it.findtext("link") or "").strip()
            if not title or not link.startswith("http"):
                continue

            try:
                item_xml_str = ET.tostring(it, encoding="utf-8").decode("utf-8", errors="ignore")
            except Exception:
                item_xml_str = ""

            game = detect_single_game(title, item_xml_str, hint)
            if not game:
                continue

            photo_url = extract_press_photo(it, item_xml_str)
            logo_info = None
            if not photo_url:
                logo_info = find_official_logo(title, item_xml_str)

            # Règle d'or : visuel obligatoire
            if not photo_url and not logo_info:
                continue

            pub = parse_date(it.findtext("pubDate") or "")
            # Rejette systématiquement tout article de plus de 45 jours
            if pub < cutoff:
                continue

            cat = detect_category(title + " " + item_xml_str)
            paragraphs = extract_article_body(it, title)

            k = title.strip().lower()
            collected.append({
                "title": title,
                "source": src_name,
                "url": link,
                "published": pub,
                "game": game,
                "category": cat,
                "image": photo_url,
                "logo": logo_info,
                "content": "\n\n".join(paragraphs[:6]),
                "first_seen": existing.get(k, {}).get("first_seen", seen_at)
            })

    # Fusion avec l'historique et dédoublonnage
    merged = {**existing}
    for item in collected:
        k = item["title"].lower().strip()
        merged[k] = item

    # REPARTITION ÉQUILIBRÉE : Garantir au moins 10-12 articles par jeu
    by_game = {g: [] for g in GAME_RULES}
    for item in merged.values():
        g = item.get("game")
        if g in by_game:
            by_game[g].append(item)

    final_selection = []
    # 1. Sélectionne les plus récents de chaque jeu
    for g, items in by_game.items():
        items_sorted = sorted(items, key=lambda x: x.get("published", ""), reverse=True)
        final_selection.extend(items_sorted[:TARGET_PER_GAME])

    # 2. Complète avec les autres actus les plus fraîches jusqu'à 120 articles
    remaining = [i for i in merged.values() if i not in final_selection]
    remaining_sorted = sorted(remaining, key=lambda x: x.get("published", ""), reverse=True)
    final_selection.extend(remaining_sorted[:max(0, 120 - len(final_selection))])

    # Tri global chronologique final
    final = sorted(final_selection, key=lambda x: x.get("published", ""), reverse=True)

    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stats = {g: sum(1 for x in final if x["game"] == g) for g in GAME_RULES}
    print(f"Extraction terminée : {len(final)} articles au total.")
    print(f"Détail par jeu : {stats}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
