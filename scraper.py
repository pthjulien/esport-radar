#!/usr/bin/env python3
"""Esport Radar Scraper — Tri Strict & Vraies Photos
- 9 disciplines esport exclusives (LoL, Valorant, CS2, Fortnite, CoD, RL, R6, Apex, EA FC)
- Rejet automatique de tout article sans vraie photo de presse
- Rejet automatique de tout article hors-sujet
- Cumul d'historique sur 14 jours pour garantir un volume de 50+ articles
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
MAX_ITEMS = 120
MAX_AGE_DAYS = 14
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# Flux spécialisés fournissant les photos officielles de presse
FEEDS = [
    # E.SPORT.FR (Flux général + catégories dédiées)
    ("https://e.sport.fr/feed/", "E.SPORT.FR", None),
    ("https://e.sport.fr/category/league-of-legends/feed/", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/valorant/feed/", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/counter-strike/feed/", "E.SPORT.FR", "cs2"),
    ("https://e.sport.fr/category/fortnite/feed/", "E.SPORT.FR", "fortnite"),
    ("https://e.sport.fr/category/call-of-duty/feed/", "E.SPORT.FR", "cod"),
    ("https://e.sport.fr/category/rocket-league/feed/", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/apex-legends/feed/", "E.SPORT.FR", "apex"),
    
    # Médias spécialisés complémentaires avec photos HD
    ("https://www.dexerto.fr/feed/esport/", "Dexerto FR", None),
    ("https://charlieintel.com/feed/", "Charlie INTEL", "cod"),
    ("https://dotesports.com/feed", "Dot Esports", None),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa", None),
    ("https://www.jeuxvideo.com/rss/rss-esport.xml", "JV Esport", None),
]

# Règles strictes par discipline : chaque jeu a son vocabulaire exclusif
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

# Sujets à éliminer d'office (non-esport, promotions, guides)
BAN_KEYWORDS = re.compile(
    r"code promo|bon plan|soldes|forfait mobile|série tv|film netflix|anime|manga|"
    r"carte graphique|processeur|setup|guide d'achat|gta 6|playstation 5|xbox series",
    re.I
)

def clean_text(raw_html: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def detect_game_strict(title: str, text_zone: str, feed_hint: str = None):
    """Détecte le jeu avec certitude. Retourne None si hors-sujet."""
    if BAN_KEYWORDS.search(title):
        return None

    scores = {k: 0 for k in GAME_RULES}

    # 1. Analyse prioritaire du titre (+10 pts)
    for k, rx in GAME_RULES.items():
        if rx.search(title):
            scores[k] += 10

    # 2. Analyse du début de description (+3 pts)
    for k, rx in GAME_RULES.items():
        if rx.search(text_zone[:250]):
            scores[k] += 3

    # 3. Indice du flux dédié (+4 pts si aucun conflit)
    if feed_hint and feed_hint in scores:
        scores[feed_hint] += 4

    best = max(scores, key=scores.get)
    # Si le score est nul, l'article n'appartient à aucun de nos jeux esport -> on l'élimine
    if scores[best] <= 0:
        return None
    return best

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

def extract_real_press_image(item, raw_item_xml: str) -> str:
    """Extrait uniquement les vraies photos de presse en haute définition."""
    # 1. Enclosure
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        u = enc.get("url").strip()
        if re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
            return u.replace("http://", "https://")

    # 2. Media content / thumbnail
    for elem in item.iter():
        if elem.tag.endswith(("content", "thumbnail")):
            u = elem.get("url", "").strip()
            if u and re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
                return u.replace("http://", "https://")

    # 3. Première balise <img> dans le corps d'article
    for tag in ["{http://purl.org/rss/1.0/modules/content/}encoded", "description"]:
        body = item.findtext(tag) or ""
        m = re.search(r'<img[^>]+src=["\']([^"\']+\.(?:jpe?g|png|webp|avif)[^"\']*)["\']', body, re.I)
        if m:
            img = m.group(1).replace("http://", "https://")
            low = img.lower()
            if not any(x in low for x in ["avatar", "logo", "icon", "emoji", "pixel", "tracking"]):
                return img

    # 4. Scan du bloc XML
    matches = re.findall(r'https?://[^\s"\'><]+\.(?:jpe?g|png|webp|avif)[^\s"\'><]*', raw_item_xml, re.I)
    for m in matches:
        low = m.lower()
        if not any(x in low for x in ["avatar", "logo", "icon", "emoji", "pixel", "tracking", "unsplash", "wikimedia"]):
            return m.replace("http://", "https://")

    return ""

def extract_article_body(item, title: str) -> list:
    """Extrait les vrais paragraphes journalistiques écrits par la rédaction."""
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

    # 1. Récupération de l'historique valide existant (pour cumuler et conserver du volume)
    existing = {}
    if OUT_FILE.exists():
        try:
            d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if isinstance(d, list):
                for a in d:
                    if isinstance(a, dict) and a.get("title") and a.get("image") and a.get("published", "") >= cutoff:
                        # On ne garde que les articles avec une vraie image (pas d'unsplash/wikimedia)
                        if "unsplash" not in a["image"] and "wikimedia" not in a["image"]:
                            k = a["title"].strip().lower()
                            existing[k] = a
        except Exception:
            pass

    collected = []

    # 2. Moissonnage de tous les flux
    for url, src_name, hint in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
            with urllib.request.urlopen(req, timeout=10) as resp:
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

            # FILTRE 1 : L'article DOIT avoir une vraie photo de presse
            img = extract_real_press_image(it, item_xml_str)
            if not img:
                continue

            # FILTRE 2 : L'article DOIT correspondre strictement à l'un de nos jeux
            game = detect_game_strict(title, item_xml_str, hint)
            if not game:
                continue

            cat = detect_category(title + " " + item_xml_str)
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
                "category": cat,
                "image": img,
                "content": "\n\n".join(paragraphs[:6]),
                "first_seen": existing.get(k, {}).get("first_seen", seen_at)
            })

    # 3. Fusion des nouveaux articles avec l'historique
    merged = {**existing}
    for item in collected:
        k = item["title"].lower().strip()
        merged[k] = item

    # 4. Tri chronologique
    sorted_items = sorted(
        merged.values(),
        key=lambda x: x.get("published", ""),
        reverse=True
    )

    final = sorted_items[:MAX_ITEMS]
    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extraction terminée : {len(final)} articles réels avec vraies photos et jeux validés.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
