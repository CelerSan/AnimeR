
import re
import urllib.parse
from typing import List, Dict, Optional

import tor
from link import get_url


# ============================================================================
# FONCTIONS DE PARSING HTML PARTAGÉES
# ============================================================================

def extract_panneaux(html_content: str, panneau_type: str) -> List[Dict]:
    """
    Extrait les panneaux (Anime ou Scan) depuis le HTML d'une page série.

    Utilisé par saison.py via import depuis ce module.

    Args:
        html_content: Contenu HTML de la page
        panneau_type: 'anime' ou 'scan'

    Returns:
        Liste de dicts {nom, url_relative, type}
    """
    panneaux = []
    function_name = f"panneau{'Anime' if panneau_type == 'anime' else 'Scan'}"

    div_patterns = [
        r'<div class="flex flex-wrap overflow-y-hidden[^>]*>.*?<script>(.*?)</script>',
        r'<div class="flex flex-wrap overflow-y-hidden justify-start[^>]*>.*?<script>(.*?)</script>',
    ]

    invalid_names = {
        'nom', 'name', 'exemple', 'example', 'test', 'template',
        'saison', 'season', 'épisode', 'episode', 'chapitre', 'chapter',
        'version', 'vf', 'vostfr', 'vo', 'ost', 'ostfr',
    }
    invalid_urls = {'url', 'lien', 'link', 'example', 'test', 'template'}

    seen: set = set()

    # --- Recherche dans les divs spécifiques ---
    for pattern in div_patterns:
        for script_content in re.findall(pattern, html_content, re.DOTALL):
            panneau_pattern = rf'{function_name}\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)'
            for nom, url_relative in re.findall(panneau_pattern, script_content):
                nom = nom.strip()
                url_relative = url_relative.strip()

                if (
                    nom.lower() in invalid_names
                    or url_relative.lower() in invalid_urls
                    or len(nom) < 3
                    or len(url_relative) < 3
                ):
                    continue

                key = (nom.lower(), url_relative)
                if key in seen:
                    continue
                seen.add(key)
                panneaux.append({'nom': nom, 'url_relative': url_relative, 'type': panneau_type})

    # --- Fallback : recherche globale dans tous les <script> ---
    if not panneaux:
        script_pattern = r'<script[^>]*>(.*?)</script>'
        for script_content in re.findall(script_pattern, html_content, re.DOTALL | re.IGNORECASE):
            if 'function' in script_content or 'document.write' in script_content:
                continue

            panneau_pattern = rf'{function_name}\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)'
            for nom, url_relative in re.findall(panneau_pattern, script_content):
                nom = nom.strip()
                url_relative = url_relative.strip()

                if (
                    nom.lower() in invalid_names
                    or url_relative.lower() in invalid_urls
                    or len(nom) < 4
                    or len(url_relative) < 4
                ):
                    continue

                key = (nom.lower(), url_relative)
                if key in seen:
                    continue
                seen.add(key)
                panneaux.append({'nom': nom, 'url_relative': url_relative, 'type': panneau_type})

    return panneaux


def build_final_url(base_url: str, relative_path: str) -> str:
    """Construit l'URL finale en combinant base et chemin relatif."""
    return f"{base_url.rstrip('/')}/{relative_path.lstrip('/')}"


# ============================================================================
# PARSING DE LA PAGE CATALOGUE
# ============================================================================

def extract_card_data(html_content: str) -> List[Dict]:
    """
    Extrait les données des cartes anime depuis le HTML du catalogue.

    Returns:
        Liste de dicts {link, title, alt_title, type, languages}
    """
    cards = []
    card_pattern = r'<div class="shrink-0 catalog-card card-base">(.*?)</div>\s*</div>\s*</a>\s*</div>'

    for card_html in re.findall(card_pattern, html_content, re.DOTALL):
        link_match = re.search(r'<a href="([^"]+)"', card_html)
        if not link_match:
            continue

        title_match = re.search(r'<h2 class="card-title">([^<]+)</h2>', card_html)
        if not title_match:
            continue

        card: Dict = {
            'link':  link_match.group(1),
            'title': title_match.group(1).strip(),
        }

        alt_match = re.search(r'<p class="alternate-titles">([^<]+)</p>', card_html)
        if alt_match:
            alt = alt_match.group(1).strip()
            card['alt_title'] = alt[:57] + "…" if len(alt) > 60 else alt
        else:
            card['alt_title'] = None

        type_match = re.search(
            r'<span class="info-label">Types</span>\s*<p class="info-value">([^<]+)</p>',
            card_html,
        )
        card['type'] = type_match.group(1).strip() if type_match else "Inconnu"

        lang_match = re.search(
            r'<span class="info-label">Langues</span>\s*<p class="info-value">([^<]+)</p>',
            card_html,
        )
        card['languages'] = lang_match.group(1).strip() if lang_match else "Inconnu"

        cards.append(card)

    return cards


def get_total_pages(html_content: str) -> int:
    """Extrait le nombre total de pages de pagination."""
    pagination_match = re.search(
        r'<div id="list_pagination">(.*?)</div>', html_content, re.DOTALL
    )
    if not pagination_match:
        return 1

    page_numbers = [
        int(m.group(1))
        for link in re.findall(r'<a [^>]*href="[^"]*page=\d+[^"]*"[^>]*>', pagination_match.group(1))
        if (m := re.search(r'page=(\d+)', link))
    ]
    return max(page_numbers) if page_numbers else 1


# ============================================================================
# RECHERCHE PRINCIPALE
# ============================================================================

def search_anime_sama() -> None:
    """Boucle de recherche interactive dans le catalogue."""
    from config import ConfigManager  # import local pour éviter un cycle au niveau module

    base_url = get_url()

    print("🌐 Vérification de Tor…")
    if not tor.ensure_tor(verbose=True):
        print("❌ Impossible de démarrer Tor.")

    while True:
        if ConfigManager.should_stop():
            break

        print("\n" + "=" * 50)
        print("🔍 RECHERCHE ANIME")
        print("=" * 50)

        anime_name = input("🎬 Nom de l'anime : ").strip()
        if not anime_name:
            print("❌ Le nom ne peut pas être vide")
            continue

        print("\n📋 Type :")
        print("  1. Anime")
        print("  2. Film")
        print("  3. Scan")
        print("  4. Tous")
        type_choice = input("👉 Choix : ").strip()

        encoded_search = urllib.parse.quote(anime_name.lower())
        type_param = {
            "1": "type%5B%5D=Anime",
            "2": "type%5B%5D=Film",
            "3": "type%5B%5D=Scans",
            "4": "",
        }.get(type_choice, "")

        search_url = f"{base_url}/catalogue/?"
        if type_param:
            search_url += f"{type_param}&"
        search_url += f"search={encoded_search}"

        print("\n⏳ Recherche en cours…")
        response = tor.tor_get(search_url, max_attempts=10, verbose=True, auto_start=True)

        if not response:
            print("\n❌ Aucun résultat")
            input("\n↩️ Entrée pour nouvelle recherche…")
            continue

        total_pages = get_total_pages(response.text)
        all_cards = extract_card_data(response.text)

        if total_pages > 1:
            print(f"📄 Récupération de {total_pages} page(s)…")
            for page_num in range(2, total_pages + 1):
                page_url = f"{search_url}&page={page_num}"
                page_response = tor.tor_get(page_url, max_attempts=5, verbose=False, auto_start=False)
                if page_response:
                    all_cards.extend(extract_card_data(page_response.text))

        if not all_cards:
            print("\n❌ Aucun résultat")
            input("\n↩️ Entrée pour nouvelle recherche…")
            continue

        print(f"\n✅ {len(all_cards)} résultat(s) :\n")
        for idx, card in enumerate(all_cards, 1):
            print(f"{idx}. {card['title']}")
            if card['alt_title']:
                print(f"   ├── {card['alt_title']}")
            print(f"   ├── {card['type']}")
            print(f"   └── {card['languages']}")
            print()

        # --- Sélection ---
        while True:
            try:
                choice = input("👉 Choix (Entrée pour annuler) : ").strip()
                if not choice:
                    print("↩️ Nouvelle recherche")
                    break

                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(all_cards):
                    selected = all_cards[choice_idx]
                    import saison
                    saison.process_anime_selection(
                        selected['link'],
                        selected['languages'],
                        base_url,
                    )
                    return
                else:
                    print(f"❌ Choix invalide (1-{len(all_cards)})")

            except ValueError:
                print("❌ Entrez un nombre valide")
            except KeyboardInterrupt:
                print("\n↩️ Nouvelle recherche")
                break
