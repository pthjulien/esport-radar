#!/usr/bin/env python3
"""Esport Radar Scraper 9.0 — Architecture Waterfall (3 Niveaux) & Tri Strict
- Niveau 1 : Vraie photo de presse HD (via API WordPress JSON & Media RSS)
- Niveau 2 : Identité visuelle officielle d'Équipe ou de Tournoi (KC, Vitality, M8, T1, Worlds, VCT...)
- Niveau 3 : Carte éditoriale "Flash Info / Dépêche" sans image artificielle
- Filtrage strict : 12 disciplines esportives. Tout article hors-sujet est rejeté.
"""
import concurrent.futures
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
MAX_AGE_DAYS = 10
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# 1. APIs WordPress REST (Récupèrent jusqu'à 30 articles complets d'un coup avec vraie photo HD)
WP_APIS = [
    ("https://e.sport.fr/wp-json/wp/v2/posts?_embed&per_page=40", "E.SPORT.FR", None),
    ("https://www.eclypsia.com/wp-json/wp/v2/posts?_embed&per_page=25", "Eclypsia", None),
    ("https://dotesports.com/wp-json/wp/v2/posts?_embed&per_page=30", "Dot Esports", None),
    ("https://esportsinsider.com/wp-json/wp/v2/posts?_embed&per_page=25", "Esports Insider", None),
    ("https://charlieintel.com/wp-json/wp/v2/posts?_embed&per_page=25", "Charlie INTEL", None),
]

# 2. Flux RSS spécialisés (Médias avec photos + Dépêches rapides par jeu)
RSS_FEEDS = [
    ("https://e.sport.fr/feed/", "E.SPORT.FR", None),
    ("https://e.sport.fr/category/league-of-legends/feed/", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/valorant/feed/", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/counter-strike/feed/", "E.SPORT.FR", "cs2"),
    ("https://e.sport.fr/category/fortnite/feed/", "E.SPORT.FR", "fortnite"),
    ("https://e.sport.fr/category/call-of-duty/feed/", "E.SPORT.FR", "cod"),
    ("https://e.sport.fr/category/rocket-league/feed/", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/apex-legends/feed/", "E.SPORT.FR", "apex"),
    ("https://www.dexerto.fr/feed/esport/", "Dexerto FR", None),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa", None),
    ("https://www.jeuxvideo.com/rss/rss-esport.xml", "JV Esport", None),
    # Flux de dépêches ciblés par jeu (utiliseront le Niveau 2 Entité ou Niveau 3 Dépêche si pas de photo)
    ("https://news.google.com/rss/search?q=esport+\"league+of+legends\"+OR+LEC+OR+LFL+OR+LCK&hl=fr&gl=FR&ceid=FR:fr", "Google News", "lol"),
    ("https://news.google.com/rss/search?q=esport+valorant+OR+VCT&hl=fr&gl=FR&ceid=FR:fr", "Google News", "val"),
    ("https://news.google.com/rss/search?q=esport+\"counter-strike\"+OR+CS2+OR+HLTV&hl=fr&gl=FR&ceid=FR:fr", "Google News", "cs2"),
    ("https://news.google.com/rss/search?q=esport+fortnite+OR+FNCS&hl=fr&gl=FR&ceid=FR:fr", "Google News", "fortnite"),
    ("https://news.google.com/rss/search?q=esport+\"call+of+duty\"+OR+CDL+OR+warzone&hl=fr&gl=FR&ceid=FR:fr", "Google News", "cod"),
    ("https://news.google.com/rss/search?q=esport+\"rocket+league\"+OR+RLCS&hl=fr&gl=FR&ceid=FR:fr", "Google News", "rl"),
    ("https://news.google.com/rss/search?q=esport+\"rainbow+six\"+OR+\"r6+siege\"+OR+\"six+invitational\"&hl=fr&gl=FR&ceid=FR:fr", "Google News", "r6"),
    ("https://news.google.com/rss/search?q=esport+\"street+fighter+6\"+OR+\"tekken+8\"+OR+EVO+OR+glutonny&hl=fr&gl=FR&ceid=FR:fr", "Google News", "fgc"),
    ("https://news.google.com/rss/search?q=esport+\"ea+sports+fc\"+OR+eLigue1+OR+\"fc+26\"+OR+\"fc+27\"&hl=fr&gl=FR&ceid=FR:fr", "Google News", "eafc"),
]

IGNORED_DOMAINS = ["flashscore", "sofascore", "livescore", "matchendirect", "scorebing", "betclic", "winamax", "unibet"]

# Règles strictes et sans ambiguïté pour chaque jeu
GAME_RULES = {
    "lol": re.compile(
        r"league of legends|\blol\b|\blec\b|\blfl\b|\blck\b|\blpl\b|\blcs\b|\blta\b|"
        r"worlds 202\d|msi 202\d|summoner's rift|faille de l'invocateur|emea masters|"
        r"\bfaker\b|\byike\b|\bcaliste\b|\bcaps\b|\bhans sama\b|\btargamas\b|\bcanna\b|\bchovy\b|\bkeria\b",
        re.I
    ),
    "val": re.compile(
        r"valorant|\bvct\b|valorant champions|vct emea|vct americas|vct pacific|vct cn|"
        r"game changers|\btenz\b|\bnats\b|\bboaster\b|\baspas\b|\bzmjjkk\b|\bchronicle\b|\bderke\b|\bsuygetsu\b|\bmagnum\b",
        re.I
    ),
    "cs2": re.compile(
        r"counter-strike|\bcs2\b|\bcs:go\b|\bcsgo\b|\bhltv\b|iem katowice|iem cologne|iem rio|iem dallas|"
        r"esl pro league|pgl major|blast premier|\bzywoo\b|\bs1mple\b|\bdonk\b|\bm0nesy\b|\bapex\b.*vitality|\bniko\b|\bropz\b|\bsiuhy\b|\bhooxi\b",
        re.I
    ),
    "fortnite": re.compile(
        r"fortnite|\bfncs\b|cash cup|unreal ranked|\bbugha\b|\bmongraal\b|\bmrsavage\b|\bmalibuca\b|\bmerstach\b|\bpeterbot\b",
        re.I
    ),
    "cod": re.compile(
        r"call of duty|\bcod\b|\bcdl\b|cod league|warzone|black ops 6|black ops 7|modern warfare|"
        r"optic texas|atlanta faze|la thieves|\bhydra\b|\bshotzzy\b|\bscrap\b|\bscump\b|\bdashy\b",
        re.I
    ),
    "rl": re.compile(
        r"rocket league|\brlcs\b|\bvatira\b|\bmonkey m00n\b|\bmonkey moon\b|\bdralii\b|\batow\b|\bexotiik\b|\bradosin\b|\balpha54\b|\bjuicy\b",
        re.I
    ),
    "r6": re.compile(
        r"rainbow six|\br6 siege\b|\br6s\b|six invitational|blast r6|siege x|\bshaiiko\b|\blikefac\b|\bbriD\b|\byuzus\b",
        re.I
    ),
    "apex": re.compile(
        r"apex legends|\balgs\b|\bimperialhal\b|\bgenburten\b|\bzer0\b.*apex",
        re.I
    ),
    "eafc": re.compile(
        r"ea sports fc|\bea fc\b|\bfc 25\b|\bfc 26\b|\bfc 27\b|\beligue\s?1\b|futchamps|fc pro|\bverjgang\b|\btekkez\b|\brocky\b.*fifa",
        re.I
    ),
    "fgc": re.compile(
        r"street fighter|\bsf6\b|tekken 8|\btekken\b|\bevo 202\d\b|guilty gear|super smash bros|smash ultimate|mortal kombat|"
        r"\bglutonny\b|\bluffy\b|\bkayane\b|\barslan ash\b|\bmenaRD\b|\bpunk\b.*sf6|\bsonicfox\b",
        re.I
    ),
    "ow2": re.compile(
        r"overwatch|\bow2\b|\bowcs\b|overwatch champions series",
        re.I
    ),
    "dota": re.compile(
        r"dota 2|\bdota\b|the international 202\d|\bti1[345]\b|riyadh masters dota",
        re.I
    ),
}

# Sujets non-esport à bannir même si un mot-clé est proche
NON_ESPORT_BAN = re.compile(
    r"code promo|bon plan|soldes amazon|black friday|forfait mobile|film netflix|série tv|"
    r"astrologie|horoscope|recette de cuisine|voiture électrique|crypto|bitcoin|casino en ligne",
    re.I
)

# Dictionnaire d'Entités Officielles (Niveau 2 : Équipes & Grands Circuits)
ENTITIES = [
    ("kc", re.compile(r"karmine corp|\bkarmine\b|\bkcorp\b|\bkc\b", re.I), {
        "code": "KC", "name": "Karmine Corp", "sub": "Blue Wall • Structure Esport", "color": "#38bdf8", "bg": "linear-gradient(135deg, #071936 0%, #090d16 100%)"
    }),
    ("vit", re.compile(r"vitality|team vitality|\bvit\b", re.I), {
        "code": "VIT", "name": "Team Vitality", "sub": "V for Victory • Structure Esport", "color": "#facc15", "bg": "linear-gradient(135deg, #2b2205 0%, #090d16 100%)"
    }),
    ("m8", re.compile(r"gentle mates|\bm8\b|gentlemates", re.I), {
        "code": "M8", "name": "Gentle Mates", "sub": "Structure Esport Officielle", "color": "#f472b6", "bg": "linear-gradient(135deg, #2d0e24 0%, #090d16 100%)"
    }),
    ("sly", re.compile(r"\bsolary\b|\bsly\b", re.I), {
        "code": "SLY", "name": "Solary", "sub": "Team d'Amis • Structure Esport", "color": "#fb923c", "bg": "linear-gradient(135deg, #2e1605 0%, #090d16 100%)"
    }),
    ("bds", re.compile(r"team bds|\bbds\b", re.I), {
        "code": "BDS", "name": "Team BDS", "sub": "Challenge The Game • Structure Esport", "color": "#22d3ee", "bg": "linear-gradient(135deg, #072235 0%, #090d16 100%)"
    }),
    ("jl", re.compile(r"\bjoblife\b", re.I), {
        "code": "JL", "name": "Joblife", "sub": "Structure Esport Officielle", "color": "#34d399", "bg": "linear-gradient(135deg, #06291f 0%, #090d16 100%)"
    }),
    ("g2", re.compile(r"\bg2 esports\b|\bg2\b", re.I), {
        "code": "G2", "name": "G2 Esports", "sub": "G2 Army • Structure Internationale", "color": "#f87171", "bg": "linear-gradient(135deg, #2d0a0e 0%, #090d16 100%)"
    }),
    ("fnc", re.compile(r"\bfnatic\b|\bfnc\b", re.I), {
        "code": "FNC", "name": "Fnatic", "sub": "Always Fnatic • Structure Internationale", "color": "#fb923c", "bg": "linear-gradient(135deg, #2e1304 0%, #090d16 100%)"
    }),
    ("t1", re.compile(r"\bt1\b|\bfaker\b", re.I), {
        "code": "T1", "name": "T1 Esports", "sub": "LCK & International Dynasty", "color": "#e11d48", "bg": "linear-gradient(135deg, #2e0711 0%, #090d16 100%)"
    }),
    ("tl", re.compile(r"team liquid|\bliquid\b", re.I), {
        "code": "TL", "name": "Team Liquid", "sub": "Structure Internationale", "color": "#60a5fa", "bg": "linear-gradient(135deg, #0b1c38 0%, #090d16 100%)"
    }),
    ("c9", re.compile(r"cloud9|\bc9\b", re.I), {
        "code": "C9", "name": "Cloud9", "sub": "Structure Nord-Américaine", "color": "#38bdf8", "bg": "linear-gradient(135deg, #072238 0%, #090d16 100%)"
    }),
    ("100t", re.compile(r"100 thieves|\b100t\b", re.I), {
        "code": "100T", "name": "100 Thieves", "sub": "Structure Nord-Américaine", "color": "#ef4444", "bg": "linear-gradient(135deg, #2b0808 0%, #090d16 100%)"
    }),
    ("navi", re.compile(r"natus vincere|\bnavi\b", re.I), {
        "code": "NAVI", "name": "Natus Vincere", "sub": "Born to Win • Structure Esport", "color": "#facc15", "bg": "linear-gradient(135deg, #292404 0%, #090d16 100%)"
    }),
    ("faze", re.compile(r"faze clan|\bfaze\b", re.I), {
        "code": "FAZE", "name": "FaZe Clan", "sub": "FaZe Up • Structure Internationale", "color": "#ef4444", "bg": "linear-gradient(135deg, #2b0707 0%, #090d16 100%)"
    }),
    ("worlds", re.compile(r"\bworlds\b|world championship", re.I), {
        "code": "WORLDS", "name": "League of Legends Worlds", "sub": "Championnat du Monde Officiel", "color": "#eab308", "bg": "linear-gradient(135deg, #1f1705 0%, #090d16 100%)"
    }),
    ("vct", re.compile(r"\bvct\b|valorant champions", re.I), {
        "code": "VCT", "name": "Valorant Champions Tour", "sub": "Circuit Officiel Riot Games", "color": "#f43f5e", "bg": "linear-gradient(135deg, #2b0912 0%, #090d16 100%)"
    }),
    ("rlcs", re.compile(r"\brlcs\b", re.I), {
        "code": "RLCS", "name": "Rocket League Championship Series", "sub": "Circuit Mondial Officiel", "color": "#0ea5e9", "bg": "linear-gradient(135deg, #071f33 0%, #090d16 100%)"
    }),
    ("fncs", re.compile(r"\bfncs\b", re.I), {
        "code": "FNCS", "name": "Fortnite Champion Series", "sub": "Circuit Compétitif Epic Games", "color": "#a855f7", "bg": "linear-gradient(135deg, #210936 0%, #090d16 100%)"
    }),
    ("cdl", re.compile(r"\bcdl\b|call of duty league", re.I), {
        "code": "CDL", "name": "Call of Duty League", "sub": "Circuit Franchise Officiel", "color": "#84cc16", "bg": "linear-gradient(135deg, #172606 0%, #090d16 100%)"
    }),
]

def clean_text(raw_html: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def detect_game_strict(title: str, categories_str: str, lead_text: str, feed_hint: str = None):
    """Attribue le jeu avec précision en priorisant le Titre et les Catégories.
    Retourne None si l'article ne correspond à aucun de nos 12 jeux esport.
    """
    if NON_ESPORT_BAN.search(title):
        return None

    scores = {k: 0 for k in GAME_RULES}

    # 1. Analyse du titre et des catégories (Poids fort : +12 points)
    header_zone = f"{title} {categories_str}"
    for game_key, rx in GAME_RULES.items():
        matches = rx.findall(header_zone)
        if matches:
            scores[game_key] += 12 * len(matches)

    # 2. Analyse du premier paragraphe court (Poids modéré : +3 points)
    short_lead = (lead_text or "")[:280]
    for game_key, rx in GAME_RULES.items():
        if rx.search(short_lead):
            scores[game_key] += 3

    # 3. Indice de flux dédié (Poids d'appoint : +5 points uniquement si aucun autre jeu n'est dans le titre)
    if feed_hint and feed_hint in scores:
        scores[feed_hint] += 5

    best_game = max(scores, key=scores.get)
    if scores[best_game] <= 0:
        return None
    return best_game

def detect_category(title: str, lead: str) -> str:
    txt = f"{title} {lead[:200]}"
    if re.search(r"rumou?rs?|rumeurs?|leak|fuite|selon|serait|pourrait|aurait|piste|courtise|en discussion", txt, re.I):
        return "rumor"
    if re.search(r"joins?|signs?|signe|rejoint|officialise|quitte|prolonge|recrute|transfert|benched|roster|départ|rejoindre|mercato", txt, re.I):
        return "official"
    if re.search(r"victoire|défaite|sacré|éliminé|finale|playoffs|classement|tournoi|major|masters|trophée|champions|direct|match|score|qualifi", txt, re.I):
        return "tournament"
    if re.search(r"patch|mise à jour|nerf|buff|équilibrage|update|hotfix", txt, re.I):
        return "patch"
    return "news"

def detect_entity(title: str, lead: str):
    """Détecte une équipe ou compétition officielle pour le Niveau 2."""
    for _, rx, info in ENTITIES:
        if rx.search(title):
            return info
    for _, rx, info in ENTITIES:
        if rx.search(lead[:200]):
            return info
    return None

def is_valid_press_photo(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    low = url.lower()
    banned = ["unsplash", "wikimedia", "avatar", "logo", "icon", "emoji", "pixel", "tracking", "gstatic", "googleusercontent", "1x1", "blank"]
    if any(b in low for b in banned):
        return False
    return bool(re.search(r"\.(jpe?g|png|webp|avif)", low))

def fetch_wp_api(entry):
    url, src_name, hint = entry
    results = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            posts = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if not isinstance(posts, list):
            return results

        for post in posts:
            title = clean_text(post.get("title", {}).get("rendered", ""))
            link = post.get("link", "")
            if not title or not link:
                continue

            # Date
            pub_raw = post.get("date_gmt") or post.get("date") or ""
            pub = pub_raw[:19] + "Z" if len(pub_raw) >= 19 else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Image & Catégories depuis _embedded
            img = ""
            cats = []
            embedded = post.get("_embedded", {})
            media_list = embedded.get("wp:featuredmedia", [])
            if isinstance(media_list, list) and media_list:
                img_candidate = media_list[0].get("source_url", "")
                if is_valid_press_photo(img_candidate):
                    img = img_candidate.replace("http://", "https://")

            terms = embedded.get("wp:term", [])
            for term_group in terms:
                if isinstance(term_group, list):
                    for t in term_group:
                        if isinstance(t, dict) and t.get("name"):
                            cats.append(t.get("name"))

            # Paragraphes de l'article
            raw_html = post.get("content", {}).get("rendered", "") or post.get("excerpt", {}).get("rendered", "")
            p_tags = re.findall(r'<p[^>]*>(.*?)</p>', raw_html, flags=re.DOTALL | re.IGNORECASE)
            paragraphs = []
            for p in p_tags:
                c = clean_text(p)
                if len(c) > 40 and not c.lower().startswith(("à lire aussi", "lire aussi", "source :", "crédit :", "the post")):
                    paragraphs.append(c)

            if not img:
                m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html, re.I)
                if m and is_valid_press_photo(m.group(1)):
                    img = m.group(1).replace("http://", "https://")

            lead = paragraphs[0] if paragraphs else clean_text(post.get("excerpt", {}).get("rendered", ""))
            if not paragraphs and lead:
                paragraphs = [lead]

            game = detect_game_strict(title, " ".join(cats), lead, hint)
            if not game:
                continue

            cat = detect_category(title, lead)
            ent = detect_entity(title, lead)
            tier = "photo" if img else ("entity" if ent else "dispatch")

            results.append({
                "title": title,
                "source": src_name,
                "url": link,
                "published": pub,
                "game": game,
                "category": cat,
                "tier": tier,
                "image": img,
                "entity": ent,
                "content": "\n\n".join(paragraphs[:8])
            })
    except Exception:
        pass
    return results

def fetch_rss_feed(entry):
    url, default_src, hint = entry
    results = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_raw = resp.read()
            root = ET.fromstring(xml_raw)
    except Exception:
        return results

    for it in root.iter("item"):
        raw_title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        if not raw_title or not link.startswith("http"):
            continue

        src_el = it.find("source")
        src = (src_el.text or "").strip() if src_el is not None else ""
        title = raw_title
        if " - " in raw_title and default_src == "Google News":
            parts = raw_title.rsplit(" - ", 1)
            title = parts[0].strip()
            if not src:
                src = parts[1].strip()
        if not src:
            src = default_src

        if any(bad in (src + " " + link).lower() for bad in IGNORED_DOMAINS):
            continue

        # Catégories XML
        cats = [clean_text(c.text or "") for c in it.findall("category") if c.text]

        # Contenu & Paragraphes
        raw_encoded = it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
        raw_desc = it.findtext("description") or ""
        p_tags = re.findall(r'<p[^>]*>(.*?)</p>', raw_encoded or raw_desc, flags=re.DOTALL | re.IGNORECASE)
        paragraphs = []
        for p in p_tags:
            c = clean_text(p)
            if len(c) > 40 and c.lower() not in title.lower() and not c.lower().startswith(("à lire aussi", "lire aussi", "the post")):
                paragraphs.append(c)

        if not paragraphs:
            desc_clean = clean_text(raw_desc)
            if len(desc_clean) > 35 and desc_clean.lower() not in title.lower():
                paragraphs.append(desc_clean)

        lead = paragraphs[0] if paragraphs else ""

        # Détection stricte du jeu
        game = detect_game_strict(title, " ".join(cats), lead, hint)
        if not game:
            continue

        # Extraction Photo (Niveau 1) — jamais sur Google News qui met un logo Google
        img = ""
        if default_src != "Google News":
            enc = it.find("enclosure")
            if enc is not None and is_valid_press_photo(enc.get("url", "")):
                img = enc.get("url").strip().replace("http://", "https://")
            if not img:
                for elem in item_iter_media(it):
                    if is_valid_press_photo(elem):
                        img = elem.replace("http://", "https://")
                        break
            if not img:
                m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_encoded or raw_desc, re.I)
                if m and is_valid_press_photo(m.group(1)):
                    img = m.group(1).replace("http://", "https://")

        try:
            dt = parsedate_to_datetime(it.findtext("pubDate") or "")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            pub = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pub = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cat = detect_category(title, lead)
        ent = detect_entity(title, lead)
        tier = "photo" if img else ("entity" if ent else "dispatch")

        results.append({
            "title": title,
            "source": src,
            "url": link,
            "published": pub,
            "game": game,
            "category": cat,
            "tier": tier,
            "image": img,
            "entity": ent,
            "content": "\n\n".join(paragraphs[:8])
        })

    return results

def item_iter_media(item):
    urls = []
    for elem in item.iter():
        if elem.tag.endswith(("content", "thumbnail")):
            u = elem.get("url", "").strip()
            if u:
                urls.append(u)
    return urls

def normalize_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:65]

def main() -> int:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_collected = []

    # Exécution parallèle rapide (moins de 6 secondes pour toutes les sources)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        wp_futures = [executor.submit(fetch_wp_api, entry) for entry in WP_APIS]
        rss_futures = [executor.submit(fetch_rss_feed, entry) for entry in RSS_FEEDS]

        for f in concurrent.futures.as_completed(wp_futures + rss_futures):
            try:
                all_collected.extend(f.result())
            except Exception:
                pass

    # Dédoublonnage intelligent : si un même article existe avec photo et sans photo, le Niveau 1 (photo) gagne
    tier_priority = {"photo": 3, "entity": 2, "dispatch": 1}
    unique = {}
    for item in all_collected:
        if item.get("published", "") < cutoff:
            continue
        k = normalize_key(item["title"])
        if not k:
            continue
        if k not in unique:
            unique[k] = item
        else:
            old = unique[k]
            if tier_priority.get(item["tier"], 0) > tier_priority.get(old["tier"], 0):
                unique[k] = item
            elif len(item.get("content", "")) > len(old.get("content", "")):
                old["content"] = item["content"]

    sorted_items = sorted(
        unique.values(),
        key=lambda x: x.get("published", ""),
        reverse=True
    )

    final = sorted_items[:MAX_ITEMS]
    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    
    c_photo = sum(1 for x in final if x["tier"] == "photo")
    c_ent = sum(1 for x in final if x["tier"] == "entity")
    c_disp = sum(1 for x in final if x["tier"] == "dispatch")
    print(f"Terminé : {len(final)} articles vérifiés (Niveau 1 Photos: {c_photo} | Niveau 2 Entités: {c_ent} | Niveau 3 Dépêches: {c_disp}).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
