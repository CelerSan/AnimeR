from typing import Optional, Tuple

import tor
# extract_panneaux et build_final_url vivent dans catalogue.py (source unique)
from catalogue import extract_panneaux, build_final_url


# ============================================================================
# SÉLECTION DE SAISON / SCAN
# ============================================================================

def process_anime_selection(
    anime_url: str,
    available_languages: str,
    base_url: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Affiche les saisons/scans disponibles, demande un choix à l'utilisateur,
    puis délègue la sélection de langue à langue.py.

    langue.py retourne uniquement une URL ; c'est ici que le téléchargement
    est déclenché, garantissant que langue.py n'importe jamais downloader.

    Args:
        anime_url:           URL de la page série (ex. .../catalogue/snk/)
        available_languages: Chaîne de langues annoncée (ex. "VOSTFR, VF")
        base_url:            Non utilisé, conservé pour compatibilité

    Returns:
        (url_finale, langues) ou (None, None) si annulé
    """
    print(f"\n🎬 SÉLECTION DES SAISONS/SCANS")
    print("=" * 50)
    print(f"📺 URL : {anime_url}")
    print(f"🌐 Langues : {available_languages}")
    print("⏳ Chargement…")

    response = tor.tor_get(anime_url, max_attempts=10, timeout=20, verbose=True)
    if not response:
        print("❌ Impossible de récupérer la page")
        return None, None

    # Extraction des panneaux (depuis catalogue.py)
    panneaux_anime = extract_panneaux(response.text, 'anime')
    panneaux_scan  = extract_panneaux(response.text, 'scan')
    all_panneaux   = panneaux_anime + panneaux_scan

    if not all_panneaux:
        print("❌ Aucun contenu disponible")
        return None, None

    # Affichage
    print(f"\n🎯 {len(all_panneaux)} version(s) disponible(s) :")
    if panneaux_anime:
        print(f"   🎬 Anime : {len(panneaux_anime)}")
    if panneaux_scan:
        print(f"   📚 Scans : {len(panneaux_scan)}")
    print("=" * 50)

    for idx, panneau in enumerate(all_panneaux, 1):
        icon = "🎬" if panneau['type'] == 'anime' else "📚"
        print(f"{idx}. {icon} {panneau['nom']}")

    # Sélection interactive
    while True:
        try:
            choice = input(f"\n👉 Choix (1-{len(all_panneaux)} ou Entrée pour annuler) : ").strip()

            if not choice:
                print("↩️ Retour")
                return None, None

            choice_idx = int(choice) - 1

            if 0 <= choice_idx < len(all_panneaux):
                selected   = all_panneaux[choice_idx]
                final_url  = build_final_url(anime_url, selected['url_relative'])
                type_label = "Anime" if selected['type'] == 'anime' else "Scan"

                print(f"\n✅ {type_label} sélectionné : {selected['nom']}")

                # langue.py retourne une URL ; downloader est appelé ICI
                _delegate_to_language_then_download(final_url, available_languages)

                return final_url, available_languages

            else:
                print(f"❌ Choix invalide (1-{len(all_panneaux)})")

        except ValueError:
            print("❌ Entrez un nombre valide")
        except KeyboardInterrupt:
            print("\n↩️ Annulé")
            return None, None


# ============================================================================
# DÉLÉGATION LANGUE → TÉLÉCHARGEMENT
# ============================================================================

def _delegate_to_language_then_download(url: str, available_languages: str) -> None:
    """
    Appelle langue.process_language_selection (qui retourne une URL)
    puis déclenche downloader.process_download sur cette URL.

    Centralise la chaîne : saison → langue → downloader,
    en maintenant langue.py libre de toute dépendance vers downloader.
    """
    try:
        import langue
        selected_url = langue.process_language_selection(url, available_languages)
    except ImportError:
        print("⚠️ langue.py non trouvé")
        return
    except Exception as e:
        print(f"❌ Erreur langue : {e}")
        return

    if not selected_url:
        return

    try:
        import downloader
        print(f"\n📥 Lancement du téléchargement…")
        print("=" * 50)
        downloader.process_download(selected_url)
    except ImportError:
        print("❌ downloader.py non trouvé")
    except Exception as e:
        print(f"❌ Erreur downloader : {e}")
