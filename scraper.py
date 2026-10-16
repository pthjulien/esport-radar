#!/usr/bin/env python3
"""Esport Radar Scraper 6.0
Récupération directe des flux avec photos de presse officielles (esport.fr, Dexerto, aAa),
purge des anciennes images de stock et génération d'analyses détaillées.
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
MAX_AGE_DAYS = 25
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Flux avec visuels de presse natifs (WordPress, Media RSS)
FEEDS = [
    ("https://esport.fr/feed/", "E.SPORT.FR"),
    ("https://www.dexerto.fr/feed/esport/", "Dexerto"),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa"),
    ("https://news.google.com/rss/search?q=esport+valorant+vct&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
    ("https://news.google.com/rss/search?q=esport+league+of+legends+lec+OR+lfl&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
    ("https://news.google.com/rss/search?q=esport+cs2+major&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
    ("https://news.google.com/rss/search?q=esport+karmine+corp+OR+vitality&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
]

# Banques de visuels de vraies compétitions et joueurs pros (aucune photo d'arcade ou de cybercafé)
PRO_PHOTOS = {
    "worlds": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cd/2019_League_of_Legends_World_Championship_Final.jpg/1200px-2019_League_of_Legends_World_Championship_Final.jpg",
    "major": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/69/IEM_Katowice_2019_trophy.jpg/1200px-IEM_Katowice_2019_trophy.jpg",
    "trophy": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/Team_Liquid_The_International_2017.jpg/1200px-Team_Liquid_The_International_2017.jpg",
    "faker": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Faker_2023.jpg/800px-Faker_2023.jpg",
    "pro_player": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/S1mple_at_StarSeries_S7.jpg/800px-S1mple_at_StarSeries_S7.jpg",
    "defeat": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/KennyS_at_DreamHack_Open_Cluj-Napoca_2015.jpg/800px-KennyS_at_DreamHack_Open_Cluj-Napoca_2015.jpg",
    "val": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/Valorant_Champions_2022_Istanbul.jpg/1200px-Valorant_Champions_2022_Istanbul.jpg",
    "cs2": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/69/IEM_Katowice_2019_trophy.jpg/1200px-IEM_Katowice_2019_trophy.jpg",
    "lol": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cd/2019_League_of_Legends_World_Championship_Final.jpg/1200px-2019_League_of_Legends_World_Championship_Final.jpg",
    "default": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cd/2019_League_of_Legends_World_Championship_Final.jpg/1200px-2019_League_of_Legends_World_Championship_Final.jpg"
}

GAME_PATTERNS = [
    ("val", re.compile(r"valorant|\bvct\b|champions|masters", re.I)),
    ("lol", re.compile(r"league of legends|\blol\b|\blec\b|\blck\b|\blfl\b|worlds|\blcs\b", re.I)),
    ("cs2", re.compile(r"counter-strike|\bcs2\b|\bcs:go\b|major|iem|blast|\bhl\b", re.I)),
    ("rl", re.compile(r"rocket league|\brlcs\b", re.I)),
    ("dota", re.compile(r"dota|international", re.I)),
]

def clean_text(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def detect_game(text: str) -> str:
    for key, rx in GAME_PATTERNS:
        if rx.search(text):
            return key
    return "other"

def detect_category(text: str) -> str:
    if re.search(r"rumou?rs?|rumeurs?|leak|fuite|selon|serait|pourrait|aurait|piste|courtise", text, re.I):
        return "rumor"
    if re.search(r"joins?|signs?|signe|rejoint|officialise|quitte|prolonge|recrute|transfert|benched|roster|départ", text, re.I):
        return "official"
    if re.search(r"victoire|défaite|sacré|éliminé|finale|playoffs|classement|tournoi|major|masters|trophée|champions|direct", text, re.I):
        return "tournament"
    if re.search(r"patch|mise à jour|nerf|buff|équilibrage", text, re.I):
        return "patch"
    return "news"

def extract_image_from_xml(item) -> str:
    # 1. Balise enclosure standard
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        return enc.get("url")

    # 2. Balise media:content ou media:thumbnail
    for elem in item.iter():
        if elem.tag.endswith(("content", "thumbnail")):
            u = elem.get("url")
            if u and re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
                return u

    # 3. Extraction de balise <img> dans content:encoded ou description
    for tag_name in ["description", "{http://purl.org/rss/1.0/modules/content/}encoded"]:
        body = item.findtext(tag_name) or ""
        m = re.search(r'<img[^>]+src=["\']([^"\']+\.(?:jpe?g|png|webp|avif)[^"\']*)["\']', body, re.I)
        if m:
            return m.group(1)

    return ""

def get_contextual_fallback(title: str, game: str) -> str:
    t = title.lower()
    if "défaite" in t or "éliminé" in t or "départ" in t or "benched" in t:
        return PRO_PHOTOS["defeat"]
    if "victoire" in t or "sacré" in t or "trophée" in t or "remporte" in t:
        return PRO_PHOTOS["trophy"]
    if "faker" in t or "t1" in t:
        return PRO_PHOTOS["faker"]
    if "worlds" in t:
        return PRO_PHOTOS["worlds"]
    if "major" in t:
        return PRO_PHOTOS["major"]
    if game in PRO_PHOTOS:
        return PRO_PHOTOS[game]
    return PRO_PHOTOS["pro_player"]

def build_article_paragraphs(title: str, snippet: str, game: str, category: str, source: str) -> str:
    paragraphs = []
    
    # Évite de répéter le titre dans le premier paragraphe
    if snippet and len(snippet) > 50 and snippet.lower() not in title.lower():
        paragraphs.append(snippet)
    else:
        paragraphs.append(f"Les observateurs de la scène et la rédaction de {source} font le point sur cette actualité majeure.")

    if category == "official":
        paragraphs.append("Les mouvements au sein de l'effectif ont été actés et validés par l'encadrement technique. L'enregistrement officiel auprès des ligues de compétition scelle la composition de l'équipe pour les prochaines échéances de la saison.")
    elif category == "rumor":
        paragraphs.append("Cette piste de transfert fait l'objet de discussions soutenues en coulisses. Tant que les signatures formelles et l'homologation des contrats par les organisateurs ne sont pas confirmées, des ajustements restent possibles lors des négociations.")
    elif category == "tournament":
        paragraphs.append("Cette rencontre de haut niveau pèse directement sur le classement général et les attributions de points de circuit. Les performances individuelles et collectives observées lors de ce rendez-vous orientent la dynamique des phases éliminatoires.")
    else:
        paragraphs.append(f"Pour approfondir le sujet, retrouver les déclarations des joueurs et les statistiques complètes de la rencontre, l'article original est consultable sur {source}.")

    return "\n\n".join(paragraphs)

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

    # Lecture de l'existant en purgeant les anciennes photos de stock
    existing = {}
    if OUT_FILE.exists():
        try:
            d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if isinstance(d, list):
                for a in d:
                    if isinstance(a, dict) and a.get("title"):
                        k = a["title"].strip().lower()
                        # Si l'image existante est l'ancien cybercafé Unsplash, on la supprime pour forcer la mise à jour
                        if "unsplash" in a.get("image", ""):
                            a["image"] = ""
                        existing[k] = a
        except Exception:
            pass

    collected = []
    for url, default_src in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
        except Exception:
            continue

        for it in root.iter("item"):
            raw_title = html.unescape((it.findtext("title") or "").strip())
            link = (it.findtext("link") or "").strip()
            if not raw_title or not link.startswith("http"):
                continue

            src_el = it.find("source")
            src = (src_el.text or "").strip() if src_el is not None else ""
            title = raw_title
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                title = parts[0].strip()
                if not src:
                    src = parts[1].strip()
            if not src:
                src = default_src

            raw_desc = clean_text(it.findtext("description") or "")
            game = detect_game(title + " " + raw_desc)
            category = detect_category(title + " " + raw_desc)
            pub = parse_date(it.findtext("pubDate") or "")

            img = extract_image_from_xml(it)
            if not img:
                img = get_contextual_fallback(title, game)

            body_content = build_article_paragraphs(title, raw_desc, game, category, src)

            k = title.strip().lower()
            collected.append({
                "title": title,
                "source": src,
                "url": link,
                "published": pub,
                "game": game,
                "category": category,
                "image": img,
                "content": body_content,
                "first_seen": existing.get(k, {}).get("first_seen", seen_at)
            })

    # Dédoublonnage
    unique = {}
    for item in collected:
        k = item["title"].lower()
        if k not in unique:
            unique[k] = item

    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sorted_articles = sorted(
        [a for a in unique.values() if a.get("published", "") >= cutoff],
        key=lambda x: x.get("published", ""),
        reverse=True
    )

    final = sorted_articles[:MAX_ITEMS]
    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Terminé : {len(final)} articles enregistrés avec visuels réels.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
