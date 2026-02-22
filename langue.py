import re
from typing import List, Dict, Optional

import tor

# ============================================================================
# CONFIGURATION DES LANGUES
# ============================================================================

LANGUAGES: Dict[str, Dict] = {
    "vostfr": {"name": "VOSTFR", "full": "Version Originale Sous-Titrée Français", "flag": "🇯🇵🇫🇷"},
    "vf":     {"name": "VF",     "full": "Version Française",                       "flag": "🇫🇷"},
    "vf1":    {"name": "VF1",    "full": "Version Française 1",                     "flag": "🇫🇷"},
    "vf2":    {"name": "VF2",    "full": "Version Française 2",                     "flag": "🇫🇷"},
    "va":     {"name": "VA",     "full": "Version Anglaise",                        "flag": "🇬🇧"},
    "vj":     {"name": "VJ",     "full": "Version Japonaise",                       "flag": "🇯🇵"},
    "vcn":    {"name": "VCN",    "full": "Version Chinoise",                        "flag": "🇨🇳"},
    "vkr":    {"name": "VKR",    "full": "Version Coréenne",                        "flag": "🇰🇷"},
    "vqc":    {"name": "VQC",    "full": "Version Québécoise",                      "flag": "🇨🇦"},
    "var":    {"name": "VAR",    "full": "Version Arabe",                           "flag": "🇸🇦"},
}

LANGUAGE_ORDER: List[str] = [
    "vostfr", "vf", "vf1", "vf2", "va", "vj", "vcn", "vkr", "vqc", "var"
]


# ============================================================================
# HELPERS URL
# ============================================================================

def build_language_url(base_url: str, lang_code: str) -> str:
    """Construit l'URL pour une langue donnée."""
    base = base_url.rstrip('/')
    # Remplacer la langue existante si présente
    for lang in LANGUAGE_ORDER:
        if base.endswith(f"/{lang}"):
            base = base[: -len(lang) - 1]
            break
    return f"{base}/{lang_code}/"


def extract_current_language(url: str) -> Optional[str]:
    """Extrait le code de langue depuis l'URL (ex. '/vostfr/' → 'vostfr')."""
    url_lower = url.lower().rstrip('/')
    for lang_code in LANGUAGE_ORDER:
        if url_lower.endswith(f"/{lang_code}"):
            return lang_code
    return None


# ============================================================================
# VÉRIFICATION ET DÉTECTION
# ============================================================================

def _check_language_exists(url: str) -> bool:
    """
    Vérifie si une URL de langue répond (HTTP 2xx/3xx) via Tor.
    Utilise tor.tor_get avec max_attempts=1 pour une vérification rapide.
    """
    response = tor.tor_get(url, max_attempts=1, timeout=10, verbose=False)
    return response is not None and 200 <= response.status_code < 400


def detect_available_languages(base_url: str, verbose: bool = True) -> List[Dict]:
    """
    Sonde chaque langue via Tor (requêtes HEAD-like via tor_get)
    et retourne la liste des langues disponibles.

    Returns:
        Liste de dicts {code, name, full_name, flag, url, is_active}
    """
    available: List[Dict] = []
    current_lang = extract_current_language(base_url)

    if verbose:
        print(f"\n🔍 Vérification des langues disponibles…")
        if current_lang:
            print(f"   📍 Langue actuelle : {LANGUAGES[current_lang]['name']}")

    for idx, lang_code in enumerate(LANGUAGE_ORDER, 1):
        lang_info = LANGUAGES[lang_code]
        lang_url  = build_language_url(base_url, lang_code)

        if verbose:
            print(f"   [{idx}/{len(LANGUAGE_ORDER)}] {lang_info['name']}…", end=" ", flush=True)

        if _check_language_exists(lang_url):
            if verbose:
                print("✅")
            available.append({
                "code":      lang_code,
                "name":      lang_info["name"],
                "full_name": lang_info["full"],
                "flag":      lang_info["flag"],
                "url":       lang_url,
                "is_active": lang_code == current_lang,
            })
        else:
            if verbose:
                print("❌")

    return available


# ============================================================================
# MENU INTERACTIF
# ============================================================================

def display_language_menu(languages: List[Dict]) -> Optional[str]:
    """
    Affiche le menu de sélection de langue et retourne l'URL choisie.

    Returns:
        URL de la langue sélectionnée, ou None si annulé.
    """
    if not languages:
        print("\n❌ Aucune langue disponible")
        return None

    print(f"\n🌍 {len(languages)} langue(s) disponible(s) :")
    print("=" * 60)

    for idx, lang in enumerate(languages, 1):
        active = " ✅ [ACTUELLE]" if lang["is_active"] else ""
        print(f"  {idx}. {lang['flag']} {lang['name']:<8} – {lang['full_name']}{active}")

    print("\n" + "=" * 60)

    while True:
        try:
            choice = input(f"👉 Choix (1-{len(languages)} ou Entrée pour annuler) : ").strip()

            if not choice:
                print("↩️ Retour")
                return None

            choice_idx = int(choice) - 1

            if 0 <= choice_idx < len(languages):
                selected = languages[choice_idx]

                if selected["is_active"]:
                    if input(f"\n⚠️ Déjà sur {selected['name']}. Continuer ? (o/n) : ").lower() != 'o':
                        continue

                print(f"\n✅ Langue : {selected['flag']} {selected['name']}")
                return selected["url"]

            else:
                print(f"❌ Choix invalide (1-{len(languages)})")

        except ValueError:
            print("❌ Entrez un nombre valide")
        except KeyboardInterrupt:
            print("\n↩️ Annulé")
            return None


# ============================================================================
# POINT D'ENTRÉE PUBLIC
# ============================================================================

def process_language_selection(
    anime_url: str,
    available_languages: Optional[str] = None,
) -> Optional[str]:
    """
    Détecte les langues disponibles via Tor et affiche le menu de sélection.

    NE déclenche PAS le téléchargement — retourne uniquement l'URL sélectionnée.
    C'est l'appelant (saison.py) qui appelle downloader après ce retour.

    Args:
        anime_url:           URL de la saison/scan (sans code langue)
        available_languages: Langues annoncées par le catalogue (informatif)

    Returns:
        URL complète avec langue (ex. .../saison1/vostfr/) ou None si annulé.
    """
    print(f"\n🌍 SÉLECTION DE LANGUE")
    print("=" * 50)
    print(f"📺 URL : {anime_url}")

    if available_languages:
        print(f"📋 Langues annoncées : {available_languages}")

    print("\n⏳ Vérification via Tor…")
    languages = detect_available_languages(anime_url, verbose=True)

    if not languages:
        print("\n❌ Aucune langue détectée")
        print("💡 Vérifiez : Tor est actif, l'URL est correcte, le site est accessible")
        return None

    print(f"\n✅ {len(languages)} langue(s) disponible(s)")
    return display_language_menu(languages)
