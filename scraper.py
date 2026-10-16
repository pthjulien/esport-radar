#!/usr/bin/env python3
"""Esport Radar Scraper 18.0
- 6 disciplines majeures exclusives : LoL, Valorant, CS2, Fortnite, CoD, Rocket League
- Réseau de sources spécialisées (HLTV, VLR, Charlie INTEL, Dot Esports, Fortnite Insider, Dexerto, E.SPORT.FR, aAa, Inven)
- Vrais logos HD intégrés (KC, Vitality, M8, G2, Fnatic, T1, 100T, LOUD, VCT, Worlds, LEC, LFL, CS2, FNCS, RLCS)
- Zéro fausse image HTML, zéro guide SEO, zéro amateur
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
MAX_ITEMS = 150
MAX_AGE_DAYS = 40
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Flux spécialisés uniquement sur les 6 disciplines conservées
FEEDS = [
    # 1. LEAGUE OF LEGENDS
    ("https://www.invenglobal.com/feed/atom", "Inven Global", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/?paged=2", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/?paged=3", "E.SPORT.FR", "lol"),
    ("https://www.dexerto.fr/league-of-legends/feed/", "Dexerto FR", "lol"),
    ("https://dotesports.com/league-of-legends/feed", "Dot Esports", "lol"),

    # 2. VALORANT
    ("https://vlr.gg/rss", "VLR.gg", "val"),
    ("https://e.sport.fr/category/valorant/feed/", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/valorant/feed/?paged=2", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/valorant/feed/?paged=3", "E.SPORT.FR", "val"),
    ("https://www.dexerto.fr/valorant/feed/", "Dexerto FR", "val"),
    ("https://dotesports.com/valorant/feed", "Dot Esports", "val"),

    # 3. COUNTER-STRIKE 2
    ("https://www.hltv.org/rss/news", "HLTV", "cs2"),
    ("https://www.dust2.us/rss", "Dust2", "cs2"),
    ("https://e.sport.fr/category/counter-strike/feed/", "E.SPORT.FR", "cs2"),
    ("https://e.sport.fr/category/counter-strike/feed/?paged=2", "E.SPORT.FR", "cs2"),
    ("https://dotesports.com/counter-strike/feed", "Dot Esports", "cs2"),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa", "cs2"),

    # 4. FORTNITE & FNCS
    ("https://fortniteinsider.com/feed/", "Fortnite Insider", "fortnite"),
    ("https://e.sport.fr/category/fortnite/feed/", "E.SPORT.FR", "fortnite"),
    ("https://e.sport.fr/category/fortnite/feed/?paged=2", "E.SPORT.FR", "fortnite"),
    ("https://www.dexerto.fr/fortnite/feed/", "Dexerto FR", "fortnite"),
    ("https://dotesports.com/fortnite/feed", "Dot Esports", "fortnite"),

    # 5. CALL OF DUTY & WARZONE
    ("https://charlieintel.com/feed/", "Charlie INTEL", "cod"),
    ("https://e.sport.fr/category/call-of-duty/feed/", "E.SPORT.FR", "cod"),
    ("https://e.sport.fr/category/call-of-duty/feed/?paged=2", "E.SPORT.FR", "cod"),
    ("https://www.dexerto.fr/call-of-duty/feed/", "Dexerto FR", "cod"),
    ("https://dotesports.com/call-of-duty/feed", "Dot Esports", "cod"),

    # 6. ROCKET LEAGUE
    ("https://e.sport.fr/category/rocket-league/feed/", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/rocket-league/feed/?paged=2", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/rocket-league/feed/?paged=3", "E.SPORT.FR", "rl"),
    ("https://dotesports.com/rocket-league/feed", "Dot Esports", "rl"),

    # GÉNÉRALISTES D'APPUI
    ("https://e.sport.fr/feed/", "E.SPORT.FR", None),
    ("https://e.sport.fr/feed/?paged=2", "E.SPORT.FR", None),
    ("https://esports.gg/feed/", "Esports.gg", None),
    ("https://www.jeuxvideo.com/rss/rss-esport.xml", "JV Esport", None),
]

GAME_RULES = {
    "lol": re.compile(
        r"league of legends|\blol\b|\blec\b|\blfl\b|\blck\b|\blpl\b|\blcs\b|"
        r"worlds 202\d|msi 202\d|summoner'?s rift|faille de l'invocateur|emea masters|"
        r"\bfaker\b|\byike\b|\bcaliste\b|\bcaps\b|\bhans sama\b|\btargamas\b|\bchovy\b|\bkeria\b|\bwooloo\b",
        re.I
    ),
    "val": re.compile(
        r"valorant|\bvct\b|valorant champions|vct emea|vct americas|vct pacific|vct cn|"
        r"game changers|\btenz\b|\bnats\b|\bboaster\b|\baspas\b|\bzmjjkk\b|\bderke\b|\bsuygetsu\b|\bmagnum\b|\banonimotum\b",
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
        r"rocket league|\brlcs\b|\bvatira\b|\bmonkey m00n\b|\bmonkey moon\b|\bdralii\b|\batow\b|\bexotiik\b|\balpha54\b|\bshiftrle\b",
        re.I
    )
}

GUIDE_AND_AMATEUR_BAN = re.compile(
    r"tier list|best loadout|meilleure classe|comment débloquer|how to unlock|code promo|"
    r"dce solution|sbc solution|wonderkids|guide complet|emplacement des|carte au trésor|"
    r"bussy|saint-georges|amateurs? de gaming|amateurs? d'esport|week-end dédié aux jeux|"
    r"salon du jeu|fête du jeu|médiathèque|mjc|centre culturel|tournoi amateur|lan amateur|"
    r"mairie de|gaming amateur|sportmag|actu\.fr",
    re.I
)

OFFICIAL_LOGOS = [
    ("vct", re.compile(r"\bvct\b|valorant champions|shanghai|masters", re.I), {
        "title": "VALORANT Champions Tour", "tag": "VCT", "color": "#ff4655", "bg": "#330a13",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/Valorant_Champions_Tour_logo.svg/512px-Valorant_Champions_Tour_logo.svg.png"
    }),
    ("worlds", re.compile(r"\bworlds\b|world championship", re.I), {
        "title": "LoL World Championship", "tag": "WORLDS", "color": "#c89b3c", "bg": "#2e2104",
        "icon": "https://upload.wikimedia.org/wikipedia/en/thumb/e/ed/League_of_Legends_World_Championship_logo.svg/512px-League_of_Legends_World_Championship_logo.svg.png"
    }),
    ("lec", re.compile(r"\blec\b", re.I), {
        "title": "League of Legends EMEA", "tag": "LEC", "color": "#00c8c8", "bg": "#022929",
        "icon": "https://upload.wikimedia.org/wikipedia/en/thumb/7/77/League_of_Legends_EMEA_Championship_logo.svg/512px-League_of_Legends_EMEA_Championship_logo.svg.png"
    }),
    ("lfl", re.compile(r"\blfl\b", re.I), {
        "title": "Ligue Française de LoL", "tag": "LFL", "color": "#3b82f6", "bg": "#091e42",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Ligue_Fran%C3%A7aise_de_League_of_Legends_logo.svg/512px-Ligue_Fran%C3%A7aise_de_League_of_Legends_logo.svg.png"
    }),
    ("cs2_major", re.compile(r"major|iem katowice|iem cologne|blast premier", re.I), {
        "title": "Counter-Strike 2 Major", "tag": "CS2", "color": "#f59e0b", "bg": "#331f03",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/Counter-Strike_2_logo.svg/512px-Counter-Strike_2_logo.svg.png"
    }),
    ("fncs", re.compile(r"\bfncs\b", re.I), {
        "title": "Fortnite Champion Series", "tag": "FNCS", "color": "#a855f7", "bg": "#2b0847",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0e/Fortnite_logo.svg/512px-Fortnite_logo.svg.png"
    }),
    ("rlcs", re.compile(r"\brlcs\b", re.I), {
        "title": "Rocket League Championship", "tag": "RLCS", "color": "#0ea5e9", "bg": "#04243d",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Rocket_League_logo.svg/512px-Rocket_League_logo.svg.png"
    }),
    ("kc", re.compile(r"karmine corp|\bkarmine\b|\bkcorp\b|\bkc\b", re.I), {
        "title": "Karmine Corp", "tag": "KC", "color": "#38bdf8", "bg": "#082142",
        "icon": "https://upload.wikimedia.org/wikipedia/fr/thumb/c/c9/Karmine_Corp_logo.svg/512px-Karmine_Corp_logo.svg.png"
    }),
    ("vit", re.compile(r"vitality|team vitality|\bvit\b", re.I), {
        "title": "Team Vitality", "tag": "VIT", "color": "#facc15", "bg": "#3b3002",
        "icon": "https://upload.wikimedia.org/wikipedia/fr/thumb/5/52/Team_Vitality_2020_Logo.svg/512px-Team_Vitality_2020_Logo.svg.png"
    }),
    ("m8", re.compile(r"gentle mates|\bm8\b", re.I), {
        "title": "Gentle Mates", "tag": "M8", "color": "#f472b6", "bg": "#3d082b",
        "icon": "https://upload.wikimedia.org/wikipedia/fr/thumb/d/d4/Gentle_Mates_logo.svg/512px-Gentle_Mates_logo.svg.png"
    }),
    ("sly", re.compile(r"\bsolary\b|\bsly\b", re.I), {
        "title": "Solary", "tag": "SLY", "color": "#fb923c", "bg": "#3b1602",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/36/Solary_logo.svg/512px-Solary_logo.svg.png"
    }),
    ("g2", re.compile(r"\bg2 esports\b|\bg2\b", re.I), {
        "title": "G2 Esports", "tag": "G2", "color": "#ef4444", "bg": "#380606",
        "icon": "https://upload.wikimedia.org/wikipedia/en/thumb/1/12/G2_Esports_logo.svg/512px-G2_Esports_logo.svg.png"
    }),
    ("fnc", re.compile(r"\bfnatic\b|\bfnc\b", re.I), {
        "title": "Fnatic", "tag": "FNC", "color": "#fb923c", "bg": "#3b1602",
        "icon": "https://upload.wikimedia.org/wikipedia/en/thumb/4/43/Fnatic_logo.svg/512px-Fnatic_logo.svg.png"
    }),
    ("100t", re.compile(r"100 thieves|\b100t\b", re.I), {
        "title": "100 Thieves", "tag": "100T", "color": "#ef4444", "bg": "#330808",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/100_Thieves_logo.svg/512px-100_Thieves_logo.svg.png"
    }),
    ("t1", re.compile(r"\bt1\b|\bfaker\b", re.I), {
        "title": "T1 Esports", "tag": "T1", "color": "#e11d48", "bg": "#360511",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/T1_logo.svg/512px-T1_logo.svg.png"
    }),
    ("loud", re.compile(r"\bloud\b", re.I), {
        "title": "LOUD Esports", "tag": "LOUD", "color": "#22c55e", "bg": "#062b11",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/02/LOUD_logo.svg/512px-LOUD_logo.svg.png"
    }),
]

def clean_text(raw_html: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def detect_single_game(title: str, text_zone: str, feed_hint: str = None):
    if GUIDE_AND_AMATEUR_BAN.search(title + " " + text_zone[:200]):
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
    
    if any(p in low for p in ["/forums/", "/thread/", "/news/", "/article/", ".html", ".php"]):
        path_only = low.split("?")[0]
        if not any(path_only.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".avif"]):
            return ""

    path_only = low.split("?")[0]
    is_img_ext = any(path_only.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".avif"])
    has_img_path = any(p in low for p in ["/uploads/", "/wp-content/uploads/", "/images/", "hltv.org/img/"])

    if is_img_ext or has_img_path:
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
        if candidate and any(w in candidate.lower() for w in ["uploads", "media", "hltv.org/img"]):
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

    existing = {}
    if OUT_FILE.exists():
        try:
            d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if isinstance(d, list):
                for a in d:
                    # Ne conserve dans l'historique que les 6 jeux retenus
                    if isinstance(a, dict) and a.get("title") and a.get("game") in GAME_RULES and a.get("published", "") >= cutoff:
                        img = a.get("image", "")
                        if img and not clean_image_url(img):
                            a["image"] = ""
                            if not a.get("logo"):
                                a["logo"] = find_official_logo(a["title"], a.get("content", ""))
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

            if not photo_url and not logo_info:
                continue

            pub = parse_date(it.findtext("pubDate") or "")
            if pub < cutoff:
                continue

            paragraphs = extract_article_body(it, title)

            k = title.strip().lower()
            collected.append({
                "title": title,
                "source": src_name,
                "url": link,
                "published": pub,
                "game": game,
                "category": detect_category(title + " " + item_xml_str),
                "image": photo_url,
                "logo": logo_info,
                "content": "\n\n".join(paragraphs[:6]),
                "first_seen": existing.get(k, {}).get("first_seen", seen_at)
            })

    merged = {**existing}
    for item in collected:
        k = item["title"].lower().strip()
        merged[k] = item

    # Répartition équilibrée sur les 6 jeux
    by_game = {g: [] for g in GAME_RULES}
    for item in merged.values():
        g = item.get("game")
        if g in by_game:
            by_game[g].append(item)

    final_selection = []
    for g, items in by_game.items():
        items_sorted = sorted(items, key=lambda x: x.get("published", ""), reverse=True)
        final_selection.extend(items_sorted[:18])

    remaining = [i for i in merged.values() if i not in final_selection]
    remaining_sorted = sorted(remaining, key=lambda x: x.get("published", ""), reverse=True)
    final_selection.extend(remaining_sorted[:max(0, MAX_ITEMS - len(final_selection))])

    final = sorted(final_selection, key=lambda x: x.get("published", ""), reverse=True)

    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stats = {g: sum(1 for x in final if x["game"] == g) for g in GAME_RULES}
    print(f"Terminé : {len(final)} articles enregistrés sur les 6 disciplines.")
    print(f"Détail par jeu : {stats}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
