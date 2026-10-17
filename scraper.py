#!/usr/bin/env python3
"""Esport Radar Scraper 26.0
- Dédoublonnage d'événements : Détection d'affiche (match clash) et similarité lexicale
- Hiérarchie de tri stricte : Patch > Rumeur > Transfert officiel > Tournoi/Match > Autre
- Nettoyage automatique des crossovers et cosmétiques hors des transferts
- 6 disciplines majeures (LoL, Valorant, CS2, Fortnite, CoD, Rocket League)
- Conservation du meilleur article en cas de doublon (priorité à la photo HD)
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT_FILE = Path(__file__).resolve().parent / "data.json"
MAX_ITEMS = 240
MAX_AGE_DAYS = 40
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

FEEDS = [
    # 1. LEAGUE OF LEGENDS
    ("https://www.invenglobal.com/feed/atom", "Inven Global", "lol"),
    ("https://dotesports.com/league-of-legends/feed", "Dot Esports", "lol"),
    ("https://esports.gg/feed/", "Esports.gg", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/?paged=2", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/?paged=3", "E.SPORT.FR", "lol"),
    ("https://e.sport.fr/category/league-of-legends/feed/?paged=4", "E.SPORT.FR", "lol"),
    ("https://www.dexerto.fr/league-of-legends/feed/", "Dexerto FR", "lol"),
    ("https://www.dexerto.com/league-of-legends/feed/", "Dexerto US", "lol"),
    ("https://blix.gg/feed/", "BLIX", "lol"),

    # 2. VALORANT
    ("https://vlr.gg/rss", "VLR.gg", "val"),
    ("https://dotesports.com/valorant/feed", "Dot Esports", "val"),
    ("https://e.sport.fr/category/valorant/feed/", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/valorant/feed/?paged=2", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/valorant/feed/?paged=3", "E.SPORT.FR", "val"),
    ("https://e.sport.fr/category/valorant/feed/?paged=4", "E.SPORT.FR", "val"),
    ("https://www.dexerto.fr/valorant/feed/", "Dexerto FR", "val"),
    ("https://www.dexerto.com/valorant/feed/", "Dexerto US", "val"),
    ("https://www.talkesport.com/feed/", "TalkEsport", "val"),

    # 3. COUNTER-STRIKE 2
    ("https://www.hltv.org/rss/news", "HLTV", "cs2"),
    ("https://www.dust2.us/rss", "Dust2", "cs2"),
    ("https://pley.gg/feed", "Pley.gg", "cs2"),
    ("https://www.fragster.com/feed/", "Fragster", "cs2"),
    ("https://dotesports.com/counter-strike/feed", "Dot Esports", "cs2"),
    ("https://e.sport.fr/category/counter-strike/feed/", "E.SPORT.FR", "cs2"),
    ("https://e.sport.fr/category/counter-strike/feed/?paged=2", "E.SPORT.FR", "cs2"),
    ("https://e.sport.fr/category/counter-strike/feed/?paged=3", "E.SPORT.FR", "cs2"),
    ("https://www.dexerto.com/csgo/feed/", "Dexerto CS2", "cs2"),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa", "cs2"),

    # 4. FORTNITE & FNCS
    ("https://fortniteinsider.com/feed/", "Fortnite Insider", "fortnite"),
    ("https://dotesports.com/fortnite/feed", "Dot Esports", "fortnite"),
    ("https://e.sport.fr/category/fortnite/feed/", "E.SPORT.FR", "fortnite"),
    ("https://e.sport.fr/category/fortnite/feed/?paged=2", "E.SPORT.FR", "fortnite"),
    ("https://e.sport.fr/category/fortnite/feed/?paged=3", "E.SPORT.FR", "fortnite"),
    ("https://www.dexerto.fr/fortnite/feed/", "Dexerto FR", "fortnite"),
    ("https://www.dexerto.com/fortnite/feed/", "Dexerto US", "fortnite"),
    ("https://www.ggrecon.com/rss/", "GGRecon", "fortnite"),

    # 5. CALL OF DUTY & WARZONE
    ("https://charlieintel.com/feed/", "Charlie INTEL", "cod"),
    ("https://charlieintel.com/category/call-of-duty/feed/", "Charlie INTEL CoD", "cod"),
    ("https://dotesports.com/call-of-duty/feed", "Dot Esports", "cod"),
    ("https://e.sport.fr/category/call-of-duty/feed/", "E.SPORT.FR", "cod"),
    ("https://e.sport.fr/category/call-of-duty/feed/?paged=2", "E.SPORT.FR", "cod"),
    ("https://e.sport.fr/category/call-of-duty/feed/?paged=3", "E.SPORT.FR", "cod"),
    ("https://www.dexerto.fr/call-of-duty/feed/", "Dexerto FR", "cod"),
    ("https://www.dexerto.com/call-of-duty/feed/", "Dexerto US", "cod"),
    ("https://www.theloadout.com/feed", "The Loadout", "cod"),

    # 6. ROCKET LEAGUE
    ("https://rocket-league.com/news/rss", "RL Garage", "rl"),
    ("https://dotesports.com/rocket-league/feed", "Dot Esports", "rl"),
    ("https://e.sport.fr/category/rocket-league/feed/", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/rocket-league/feed/?paged=2", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/rocket-league/feed/?paged=3", "E.SPORT.FR", "rl"),
    ("https://e.sport.fr/category/rocket-league/feed/?paged=4", "E.SPORT.FR", "rl"),

    # HUBS GÉNÉRALISTES
    ("https://esportsinsider.com/feed", "Esports Insider", None),
    ("https://e.sport.fr/feed/", "E.SPORT.FR", None),
    ("https://e.sport.fr/feed/?paged=2", "E.SPORT.FR", None),
    ("https://e.sport.fr/feed/?paged=3", "E.SPORT.FR", None),
]

GAME_RULES = {
    "lol": re.compile(
        r"league of legends|\blol\b|\blec\b|\blfl\b|\blck\b|\blpl\b|\blcs\b|"
        r"worlds 202\d|mondiaux 202\d|msi 202\d|summoner'?s rift|faille de l'invocateur|emea masters|"
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

# Exclusion stricte des contenus hors-sujet
FLUFF_AND_AMATEUR_BAN = re.compile(
    r"tier list|best loadout|meilleure classe|comment débloquer|how to unlock|code promo|"
    r"dce solution|sbc solution|wonderkids|guide complet|emplacement des|carte au trésor|"
    r"skin leak|item shop|boutique du|twitch ban|streamer drama|onlyfans|"
    r"bussy|saint-georges|amateurs? de gaming|amateurs? d'esport|week-end dédié aux jeux|"
    r"salon du jeu|fête du jeu|médiathèque|mjc|centre culturel|tournoi amateur|lan amateur|"
    r"mairie de|gaming amateur|sportmag|actu\.fr",
    re.I
)

# Structures esport pour détecter les affiches de match
TRACKED_TEAMS = [
    (1, re.compile(r"\bkcorp\b|\bkarmine corp\b|\bkc\b", re.I)),
    (2, re.compile(r"\bvitality\b|\bvit\b", re.I)),
    (3, re.compile(r"\bgentle mates\b|\bm8\b", re.I)),
    (4, re.compile(r"\bsolary\b|\bsly\b", re.I)),
    (5, re.compile(r"\bg2\b|\bg2 esports\b", re.I)),
    (6, re.compile(r"\bfnatic\b|\bfnc\b", re.I)),
    (7, re.compile(r"\bcloud9\b|\bc9\b", re.I)),
    (8, re.compile(r"\bfuria\b", re.I)),
    (9, re.compile(r"\bt1\b", re.I)),
    (10, re.compile(r"\bloud\b", re.I)),
    (11, re.compile(r"\b100 thieves\b|\b100t\b", re.I)),
    (12, re.compile(r"\bnavi\b|\bnatus vincere\b", re.I)),
    (13, re.compile(r"\bfaze\b|\bfaze clan\b", re.I)),
    (14, re.compile(r"\boptic\b|\boptic texas\b", re.I)),
    (15, re.compile(r"\bteam liquid\b|\bliquid\b", re.I)),
    (16, re.compile(r"\bbds\b|\bteam bds\b", re.I)),
    (17, re.compile(r"\bmouz\b", re.I)),
    (18, re.compile(r"\bfalcons\b|\bteam falcons\b", re.I)),
    (19, re.compile(r"\bastralis\b", re.I)),
    (20, re.compile(r"\bheroic\b", re.I)),
    (21, re.compile(r"\bspirit\b|\bteam spirit\b", re.I)),
    (22, re.compile(r"\bvirtus\.?pro\b|\bvp\b", re.I)),
    (23, re.compile(r"\bgen\.?g\b", re.I)),
    (24, re.compile(r"\bsentinels\b|\bsen\b", re.I)),
    (25, re.compile(r"\bblg\b|\bbilibili gaming\b", re.I)),
    (26, re.compile(r"\bweibo\b|\bwbg\b", re.I)),
    (27, re.compile(r"\bheretics\b|\bteam heretics\b", re.I)),
    (28, re.compile(r"\bjoblife\b|\bjl\b", re.I)),
    (29, re.compile(r"\baurora\b", re.I)),
    (30, re.compile(r"\b9z\b|\b9z team\b", re.I)),
    (31, re.compile(r"\bmvk\b|\bmvk esports\b", re.I)),
]

SPECIFIC_IDENTITIES = [
    ("100t", re.compile(r"100 thieves|\b100t\b", re.I), {
        "title": "100 Thieves", "tag": "100T", "color": "#ef4444", "bg": "#3d0606"
    }),
    ("kc", re.compile(r"karmine corp|\bkarmine\b|\bkcorp\b|\bkc\b", re.I), {
        "title": "Karmine Corp", "tag": "KC", "color": "#38bdf8", "bg": "#082142"
    }),
    ("vit", re.compile(r"vitality|team vitality|\bvit\b", re.I), {
        "title": "Team Vitality", "tag": "VIT", "color": "#facc15", "bg": "#3d3002"
    }),
    ("m8", re.compile(r"gentle mates|\bm8\b", re.I), {
        "title": "Gentle Mates", "tag": "M8", "color": "#f472b6", "bg": "#3d082b"
    }),
    ("loud", re.compile(r"\bloud\b", re.I), {
        "title": "LOUD Esports", "tag": "LOUD", "color": "#22c55e", "bg": "#062e12"
    }),
    ("g2", re.compile(r"\bg2 esports\b|\bg2\b", re.I), {
        "title": "G2 Esports", "tag": "G2", "color": "#ef4444", "bg": "#380606"
    }),
    ("fnc", re.compile(r"\bfnatic\b|\bfnc\b", re.I), {
        "title": "Fnatic", "tag": "FNC", "color": "#fb923c", "bg": "#3d1602"
    }),
    ("t1", re.compile(r"\bt1\b|\bfaker\b", re.I), {
        "title": "T1 Esports", "tag": "T1", "color": "#e11d48", "bg": "#3b0511"
    }),
    ("navi", re.compile(r"\bnavi\b|natus vincere", re.I), {
        "title": "Natus Vincere", "tag": "NAVI", "color": "#facc15", "bg": "#3b3002"
    }),
    ("c9", re.compile(r"cloud9|\bc9\b", re.I), {
        "title": "Cloud9", "tag": "C9", "color": "#0ea5e9", "bg": "#032442"
    }),
    ("furia", re.compile(r"\bfuria\b", re.I), {
        "title": "FURIA Esports", "tag": "FURIA", "color": "#cbd5e1", "bg": "#1e293b"
    }),
]

GAME_CIRCUIT_FALLBACKS = {
    "lol": { "title": "League of Legends Pro", "tag": "LOL", "color": "#c89b3c", "bg": "#2e2104" },
    "val": { "title": "VALORANT Champions Tour", "tag": "VCT", "color": "#ff4655", "bg": "#3d0a14" },
    "cs2": { "title": "Counter-Strike 2", "tag": "CS2", "color": "#f59e0b", "bg": "#382003" },
    "fortnite": { "title": "Fortnite Champion Series", "tag": "FNCS", "color": "#a855f7", "bg": "#2e084d" },
    "cod": { "title": "Call of Duty League", "tag": "CDL", "color": "#84cc16", "bg": "#1b2e04" },
    "rl": { "title": "Rocket League Championship", "tag": "RLCS", "color": "#0ea5e9", "bg": "#04243d" }
}

STOP_WORDS = {
    "les", "des", "pour", "sur", "dans", "avec", "sans", "sous", "par", "qui", "que", "quoi", "dont",
    "est", "sont", "ont", "fait", "font", "vers", "une", "the", "and", "for", "with", "from", "this",
    "that", "after", "over", "into", "direct", "live", "match", "matchs", "score", "scores", "face",
    "contre", "against", "tout", "tous", "plus", "bien", "game", "jeux", "esport", "esports", "en"
}

def clean_text(raw_html: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def normalize_url(url: str) -> str:
    u = re.sub(r'https?://(www\.)?', '', url.strip().lower())
    return u.split('?')[0].rstrip('/')

def get_title_tokens(title: str) -> set:
    words = re.findall(r'\b[a-zA-Z0-9\u00C0-\u017F]{3,}\b', title.lower())
    return {w for w in words if w not in STOP_WORDS}

def extract_teams_ids(title: str) -> set:
    found = set()
    for tid, rx in TRACKED_TEAMS:
        if rx.search(title):
            found.add(tid)
    return found

def are_articles_duplicate(item_a: dict, item_b: dict) -> bool:
    """Détecte si deux articles traitent exactement du même événement sportif."""
    if item_a.get("game") != item_b.get("game"):
        return False

    # Proximité temporelle (moins de 48 heures d'écart)
    try:
        t1 = datetime.fromisoformat(item_a["published"].replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(item_b["published"].replace("Z", "+00:00"))
        if abs((t1 - t2).total_seconds()) > 48 * 3600:
            return False
    except Exception:
        pass

    # 1. Détection d'affiche de match (les 2 mêmes équipes impliquées)
    teams_a = extract_teams_ids(item_a["title"])
    teams_b = extract_teams_ids(item_b["title"])
    if len(teams_a) >= 2 and len(teams_b) >= 2:
        if len(teams_a.intersection(teams_b)) >= 2:
            return True

    # 2. Similarité lexicale sur les mots-clés forts
    tok_a = get_title_tokens(item_a["title"])
    tok_b = get_title_tokens(item_b["title"])
    if not tok_a or not tok_b:
        return False

    common = tok_a.intersection(tok_b)
    union = tok_a.union(tok_b)
    jaccard = len(common) / len(union) if union else 0

    # Au moins 3 termes forts partagés ou score de similarité > 45%
    if len(common) >= 3 and jaccard >= 0.35:
        return True
    if jaccard >= 0.48:
        return True

    return False

def detect_single_game(title: str, text_zone: str, feed_hint: str = None):
    if FLUFF_AND_AMATEUR_BAN.search(title + " " + text_zone[:200]):
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

def detect_category_strict(title: str, body: str) -> str:
    """Hiérarchie de classification étanche."""
    t = title.lower()
    first_p = body.split("\n\n")[0].lower() if body else ""

    # Niveau 1 : Crossovers, bundles, cosmétiques -> "Autre" systématique
    if re.search(r"\b(crossover|crossovers|collab|collaboration|skins?|bundle|bundles|cosmetics?|item shop|boutique|battle pass|passe de combat|anime|concert)\b", t):
        return "news"

    # Niveau 2 : Patchs et correctifs
    if re.search(r"\b(patch|patchs|notes de patch|patch notes|hotfix|nerf|buff|nerfs|buffs|mise à jour|mises à jour|équilibrage|weapon balancing)\b", t):
        if not re.search(r"\broster\b|\btransfert\b", t):
            return "patch"

    # Niveau 3 : Rumeurs mercato et bruits de couloir
    if re.search(r"\b(rumou?rs?|rumeurs?|leaks?|fuite|fuites|selon|serait|pourrait|aurait|piste|courtise|viserait|exploring options|targets?|in talks|verbally agree|sources?:|report:|prépare un roster)\b", t):
        return "rumor"

    # Niveau 4 : Transferts officiels et changements d'effectif stricts
    if re.search(r"\b(signs? with|signe chez|signe avec|rejoint l'équipe|rejoint le roster|officially signed?|officially joins?|officialise|officialisent|quitte|quittent|leaves? team|parted ways|parting ways|benched|banc de touche|bench|roster move|transfert officiel|free agent|released from|steps down|stepped down|stand-in|substitute)\b", t):
        return "official"
    if re.search(r"\b(signe|signent|rejoint|rejoignent|joins?|leaves?|prolonge|prolongent|recrute|recrutent|départ|départs)\b", t):
        if not re.search(r"\b(demi-finale|finale|quarts?|playoffs?|bracket|main event|champions|next round|trophée)\b", t):
            return "official"

    # Niveau 5 : Tournois, résultats de matchs et compétitions
    if re.search(r"\b(victoire|défaite|gagne|battent|bat|vainqueur|sacré|éliminé|éliminée|élimination|finale|finales|semifinals?|demi-finales?|quarts?|playoffs?|classement|tournoi|tournois|tournament|tournaments|major|majors|masters|trophée|match|matchs|score|scores|\bvs\b|sweep|advance|advances|beat|beats|win over|takes? down|took down|qualifi\w*|bracket|brackets|standings|group stage|phase de poules|direct|live|en direct|affront\w*|champions)\b", t):
        return "tournament"

    # Détection de secours dans le lead
    if re.search(r"\b(advance to semifinals|secured victory|took down|eliminated from|defeated|punches ticket|won against|en direct pour suivre le match)\b", first_p):
        return "tournament"
    if re.search(r"\b(sources tell|reportedly|according to sources|exploring options)\b", first_p):
        return "rumor"
    if re.search(r"\b(officially announced the signing|parted ways with|announced departure|signed a contract)\b", first_p):
        return "official"

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

def get_visual_identity(title: str, text_zone: str, game: str):
    for _, rx, data in SPECIFIC_IDENTITIES:
        if rx.search(title) or rx.search(text_zone[:200]):
            return data
    return GAME_CIRCUIT_FALLBACKS.get(game, { "title": "Esport Compétitif", "tag": "ESPORT", "color": "#38bdf8", "bg": "#0e1e38" })

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
                    if isinstance(a, dict) and a.get("title") and a.get("game") in GAME_RULES and a.get("published", "") >= cutoff:
                        if FLUFF_AND_AMATEUR_BAN.search(a["title"]):
                            continue
                        img = a.get("image", "")
                        if img and not clean_image_url(img):
                            a["image"] = ""
                        a["category"] = detect_category_strict(a["title"], a.get("content", ""))
                        if not a.get("image"):
                            a["logo"] = get_visual_identity(a["title"], a.get("content", ""), a["game"])
                        ukey = normalize_url(a.get("url", a["title"]))
                        existing[ukey] = a
        except Exception:
            pass

    raw_collected = []

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
                logo_info = get_visual_identity(title, item_xml_str, game)

            pub = parse_date(it.findtext("pubDate") or "")
            if pub < cutoff:
                continue

            paragraphs = extract_article_body(it, title)
            content_text = "\n\n".join(paragraphs[:6])

            ukey = normalize_url(link)
            raw_collected.append({
                "title": title,
                "source": src_name,
                "url": link,
                "published": pub,
                "game": game,
                "category": detect_category_strict(title, content_text),
                "image": photo_url,
                "logo": logo_info,
                "content": content_text,
                "first_seen": existing.get(ukey, {}).get("first_seen", seen_at)
            })

    # Fusion initiale par URL
    merged_by_url = {**existing}
    for item in raw_collected:
        ukey = normalize_url(item["url"])
        merged_by_url[ukey] = item

    # DÉDOUBLONNAGE D'ÉVÉNEMENT (MATCH CLASH & SIMILARITÉ)
    all_articles = sorted(merged_by_url.values(), key=lambda x: x.get("published", ""), reverse=True)
    deduped = []

    for candidate in all_articles:
        match_found = False
        for idx, existing_item in enumerate(deduped):
            if are_articles_duplicate(candidate, existing_item):
                match_found = True
                # Arbitrage : on privilégie l'article avec une vraie photo HD
                cand_has_img = bool(candidate.get("image"))
                exist_has_img = bool(existing_item.get("image"))
                if cand_has_img and not exist_has_img:
                    deduped[idx] = candidate
                elif cand_has_img == exist_has_img:
                    # En cas d'égalité sur la photo, on garde le résumé le plus riche
                    if len(candidate.get("content", "")) > len(existing_item.get("content", "")):
                        deduped[idx] = candidate
                break
        if not match_found:
            deduped.append(candidate)

    # Répartition équilibrée par jeu
    by_game = {g: [] for g in GAME_RULES}
    for item in deduped:
        g = item.get("game")
        if g in by_game:
            by_game[g].append(item)

    final_selection = []
    for g, items in by_game.items():
        items_sorted = sorted(items, key=lambda x: x.get("published", ""), reverse=True)
        final_selection.extend(items_sorted[:32])

    remaining = [i for i in deduped if i not in final_selection]
    remaining_sorted = sorted(remaining, key=lambda x: x.get("published", ""), reverse=True)
    final_selection.extend(remaining_sorted[:max(0, MAX_ITEMS - len(final_selection))])

    final = sorted(final_selection, key=lambda x: x.get("published", ""), reverse=True)

    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stats = {g: sum(1 for x in final if x["game"] == g) for g in GAME_RULES}
    print(f"Extraction terminée : {len(final)} articles uniques et qualifiés enregistrés.")
    print(f"Détail par jeu : {stats}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
