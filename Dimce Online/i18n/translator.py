import json
import streamlit as st
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"

# Ordre d'affichage dans le sélecteur
LANGUES = {
    "fr": "🇫🇷 Français",
    "en": "🇬🇧 English",
    "nl": "🇳🇱 Nederlands",
    "de": "🇩🇪 Deutsch",
    "es": "🇪🇸 Español",
}
DEFAUT = "fr"


@st.cache_data
def _traductions(langue: str) -> dict:
    fichier = LOCALES_DIR / f"{langue}.json"
    if not fichier.exists():
        fichier = LOCALES_DIR / f"{DEFAUT}.json"
    with open(fichier, "r", encoding="utf-8") as f:
        return json.load(f)


def langue_courante() -> str:
    return st.session_state.get("langue", DEFAUT)


def t(cle: str, **kwargs) -> str:
    """Traduit une clé. Retourne la clé si absente (visible en dev)."""
    texte = _traductions(langue_courante()).get(cle, cle)
    return texte.format(**kwargs) if kwargs else texte