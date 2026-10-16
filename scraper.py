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
