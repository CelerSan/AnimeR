import os
import sys
import signal
import subprocess
import platform
from typing import Tuple, Optional

from config import ConfigManager

VERSION  = "2.2"
VENV_DIR = ".venv"

REQUIRED_PACKAGES = [
    "requests",
    "beautifulsoup4",
    "img2pdf",
    "PySocks",
    "yt-dlp",
    "rich",
]

# Mapping nom PyPI → nom d'import
_IMPORT_NAMES = {
    "beautifulsoup4": "bs4",
    "PySocks":        "socks",
    "yt-dlp":         "yt_dlp",
}


# ============================================================================
# GESTIONNAIRE DE SIGNAUX
# ============================================================================

def _setup_signal_handler() -> None:
    _first_interrupt = [True]

    def handler(signum, frame):
        if _first_interrupt[0]:
            _first_interrupt[0] = False
            print("\n\n⚠️ Interruption reçue – arrêt propre en cours…")
            ConfigManager.request_shutdown()
        else:
            print("\n⚠️ Deuxième interruption – arrêt forcé")
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handler)


# ============================================================================
# GESTION DE L'ENVIRONNEMENT
# ============================================================================

def is_venv_active() -> bool:
    return hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )


def create_venv() -> bool:
    print(f"\n📦 Création du venv ({VENV_DIR})…")
    try:
        import venv
        venv.create(VENV_DIR, with_pip=True)
        print("✅ Venv créé")
        return True
    except Exception as e:
        print(f"❌ Erreur : {e}")
        return False


def get_venv_python() -> Optional[str]:
    if platform.system() == "Windows":
        path = os.path.join(VENV_DIR, "Scripts", "python.exe")
    else:
        path = os.path.join(VENV_DIR, "bin", "python")
    return path if os.path.exists(path) else None


def activate_venv_and_relaunch() -> None:
    python = get_venv_python()
    if not python:
        print("❌ Python du venv non trouvé")
        return
    print("\n🔄 Relancement dans le venv…")
    os.execv(python, [python] + sys.argv)


def install_dependencies() -> bool:
    """Installe les paquets manquants."""
    missing = []
    for pkg in REQUIRED_PACKAGES:
        name = _IMPORT_NAMES.get(pkg, pkg.replace('-', '_'))
        try:
            __import__(name)
        except ImportError:
            missing.append(pkg)

    if not missing:
        print("✅ Toutes les dépendances sont installées")
        return True

    print(f"\n📦 Installation de {len(missing)} paquet(s) : {', '.join(missing)}")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
            check=True, capture_output=True,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install"] + missing,
            check=True, capture_output=True,
        )
        print("✅ Dépendances installées")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur installation : {e}")
        return False


# ============================================================================
# GESTION TOR
# ============================================================================

def setup_tor(config: ConfigManager) -> Tuple[bool, str]:
    """Prépare et démarre Tor via le binaire embarqué."""
    try:
        import tor as tor_module
    except ImportError:
        return False, "tor.py introuvable"

    if tor_module.is_tor_running_on_port(9050):
        return True, "Tor déjà actif sur le port 9050"

    if not config.is_tor_auto_download():
        binary = tor_module.get_tor_binary_path()
        if not binary:
            return False, "Binaire Tor absent et téléchargement automatique désactivé"

    binary = tor_module.get_tor_binary_path()
    if not binary:
        print("\n📥 Téléchargement du binaire Tor Expert Bundle…")
        if not tor_module.download_tor_binary(verbose=True):
            return False, "Échec du téléchargement du binaire Tor"
        binary = tor_module.get_tor_binary_path()

    if not binary:
        return False, "Binaire Tor introuvable après téléchargement"

    ok = tor_module.start_tor(verbose=True)
    return (True, "Tor démarré (binaire embarqué)") if ok else (False, "Tor n'a pas pu démarrer")


def check_tor_status() -> Tuple[bool, str]:
    """Vérifie rapidement si Tor écoute sur les ports SOCKS et Control."""
    try:
        import tor as tor_module
        if tor_module.is_tor_running_on_port(9050):
            label = "Tor actif (SOCKS + ControlPort)" if tor_module.is_tor_running_on_port(9051) \
                    else "Tor actif (SOCKS – rotation IP désactivée)"
            return True, label
        return False, "Tor inactif"
    except ImportError:
        return False, "tor.py introuvable"


def get_tor_binary_info() -> str:
    try:
        import tor as tor_module
        binary = tor_module.get_tor_binary_path()
        if binary:
            return f"Binaire : {binary} ({binary.stat().st_size // 1024} Ko)"
        return "Binaire : absent"
    except Exception:
        return "Binaire : information indisponible"


# ============================================================================
# VÉRIFICATION SYSTÈME
# ============================================================================

def check_system() -> None:
    print("\n" + "=" * 60)
    print("🔍 VÉRIFICATION DES PRÉREQUIS")
    print("=" * 60)

    # Python
    py = sys.version_info
    print(f"\n1️⃣  Python {py.major}.{py.minor}.{py.micro}")
    if py.major < 3 or (py.major == 3 and py.minor < 7):
        print("   ❌ Python 3.7+ requis")
    else:
        print("   ✅ OK")

    # Venv
    print(f"\n2️⃣  Environnement virtuel")
    print(f"   {'✅ Actif' if is_venv_active() else '⚠️ Non actif (recommandé)'}")

    # Dépendances
    print(f"\n3️⃣  Dépendances Python")
    for pkg in REQUIRED_PACKAGES:
        name = _IMPORT_NAMES.get(pkg, pkg.replace('-', '_'))
        try:
            __import__(name)
            print(f"   ✅ {pkg}")
        except ImportError:
            print(f"   ❌ {pkg}")

    # Tor
    print(f"\n4️⃣  Tor")
    try:
        import tor as tor_module
        binary = tor_module.get_tor_binary_path()
        print(f"   {'✅ Binaire présent : ' + str(binary) if binary else '⚠️ Binaire absent (téléchargé au 1er lancement)'}")
        if tor_module.is_tor_running_on_port(9050):
            print("   ✅ Service actif sur le port 9050")
        else:
            print("   ℹ️ Service inactif (démarrera automatiquement)")
    except ImportError:
        print("   ❌ tor.py introuvable")

    # yt-dlp
    print(f"\n5️⃣  yt-dlp")
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, timeout=5)
        if result.returncode == 0:
            print(f"   ✅ Version {result.stdout.decode().strip()}")
        else:
            print("   ❌ Non fonctionnel")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("   ❌ Non installé")

    print("\n" + "=" * 60)


# ============================================================================
# MENUS
# ============================================================================

def show_main_menu() -> None:
    print("\n" + "=" * 60)
    print(f"🎬 AnimeR v{VERSION}")
    print("=" * 60)
    print("""
1. 🔍 Rechercher un anime
2. 📥 Télécharger depuis une URL
3. 📋 Téléchargement batch (liste .txt)
4. ⚙️  Configuration
5. 🔧 Vérifier les prérequis
6. 📚 Aide
7. 🚪 Quitter
""")


def show_config_menu(config: ConfigManager) -> None:
    while True:
        if ConfigManager.should_stop():
            break

        print("\n" + "=" * 60)
        print("⚙️  CONFIGURATION")
        print("=" * 60)

        dl_dir   = config.get("directories", "download_base") or "(par défaut : ./AnimeRT)"
        tor_ok, tor_msg = check_tor_status()
        auto_dl  = config.is_tor_auto_download()

        print(f"\n📂 Répertoire  : {dl_dir}")
        print(f"🌐 Tor         : {'✅' if tor_ok else '❌'} {tor_msg}")
        print(f"📥 Auto-DL Tor : {'✅ Activé' if auto_dl else '❌ Désactivé'}")
        print(f"   {get_tor_binary_info()}")
        print(f"📥 Threads     : {config.get_max_threads()}")
        min_d, max_d = config.get_scan_delays()
        print(f"📚 Scans délai : {min_d}-{max_d}s")

        print("\n1. Changer le répertoire")
        print("2. Télécharger/mettre à jour le binaire Tor")
        print("3. Activer/désactiver le téléchargement auto de Tor")
        print("4. Paramètres téléchargements")
        print("5. Réinitialiser la configuration")
        print("6. Retour")

        choice = input("\n👉 Choix : ").strip()

        if choice == '1':
            new_dir = input("Nouveau répertoire : ").strip()
            config.set("directories", "download_base", value=new_dir)
            config.save()
            print("✅ Mis à jour")

        elif choice == '2':
            try:
                import tor as tor_module
                print("\n📥 Téléchargement du binaire Tor…")
                binary = tor_module.get_tor_binary_path()
                if binary and binary.exists():
                    binary.unlink()
                    print("   Ancien binaire supprimé")
                if tor_module.download_tor_binary(verbose=True):
                    print("✅ Binaire Tor mis à jour")
                else:
                    print("❌ Échec du téléchargement")
            except ImportError:
                print("❌ tor.py introuvable")

        elif choice == '3':
            config.set("tor", "auto_download_binary", value=not auto_dl)
            config.save()
            print(f"✅ Téléchargement automatique {'activé' if not auto_dl else 'désactivé'}")

        elif choice == '4':
            t = input(f"Threads [{config.get_max_threads()}] : ").strip()
            if t.isdigit():
                config.set("downloads", "max_threads", value=int(t))
                config.save()
                print("✅ Mis à jour")

        elif choice == '5':
            if input("⚠️ Réinitialiser ? (o/n) : ").lower() == 'o':
                config.reset()

        elif choice == '6':
            break


def show_help() -> None:
    print("\n" + "=" * 60)
    print("📚 AIDE")
    print("=" * 60)
    print(f"""
🎬 AnimeR v{VERSION} – Guide rapide

RECHERCHE :
  Nom → Saison → Langue → Téléchargement

URL DIRECTE :
  📺 .../catalogue/serie/saison1/vostfr/
  🎥 .../catalogue/serie/film/vf/
  📚 .../catalogue/serie/scan/vf/

TÉLÉCHARGEMENT BATCH :
  Format : [URL] / [Episodes]
  Exemples :
    [https://…/saison1/vf/]  / [1-3]
    [https://…/scan/vf/]     / [13]
    [https://…/saison2/vf/]  / [all]
    [https://…/saison1/vf/]  / [1,5,10-12]

TOR :
  Binaire auto-téléchargé depuis torproject.org
  Stocké dans : ./tor_bin/
  SOCKS5 : 127.0.0.1:9050   Control : 127.0.0.1:9051

TYPES :
  📚 Scans  → via Tor
  🎬 Vidéos → connexion directe (yt-dlp)

STRUCTURE :
  AnimeRT/
    └─ Série/
       ├─ Saison_1/VF/
       ├─ Films/VOSTFR/
       └─ Scans/VF/
""")
    input("\n↩️ Entrée pour continuer…")


# ============================================================================
# APPELS AUX MODULES
# ============================================================================

def call_catalogue() -> None:
    try:
        import catalogue
        catalogue.search_anime_sama()
    except ImportError:
        print("❌ catalogue.py non trouvé")
    except Exception as e:
        print(f"❌ Erreur : {e}")


def call_downloader(url: str) -> None:
    try:
        import downloader
        downloader.process_download(url)
    except ImportError:
        print("❌ downloader.py non trouvé")
    except Exception as e:
        print(f"❌ Erreur : {e}")


def call_batch_downloader() -> None:
    try:
        import batch_downloader

        print("\n" + "=" * 60)
        print("📋 TÉLÉCHARGEMENT BATCH")
        print("=" * 60)
        print("""
1. Créer un fichier exemple (downloads.txt)
2. Traiter un fichier existant
3. Retour
""")
        choice = input("👉 Choix : ").strip()

        if choice == '1':
            filename = input("\nNom du fichier [downloads.txt] : ").strip() or "downloads.txt"
            if batch_downloader.create_example_file(filename):
                print(f"\n💡 Éditez {filename} puis utilisez l'option 2")

        elif choice == '2':
            filename = input("\nFichier à traiter : ").strip()
            if not filename:
                print("❌ Nom de fichier requis")
                return
            if not os.path.exists(filename):
                print(f"❌ Fichier non trouvé : {filename}")
                return
            batch_downloader.process_batch_file(filename)

    except ImportError:
        print("❌ batch_downloader.py non trouvé")
    except Exception as e:
        print(f"❌ Erreur : {e}")


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    _setup_signal_handler()

    print("\n" + "=" * 60)
    print(f"🎬 AnimeR v{VERSION}")
    print("=" * 60)

    # Venv
    if not is_venv_active() and os.path.exists(VENV_DIR):
        if input(f"Activer le venv {VENV_DIR} ? (o/n) : ").lower() == 'o':
            activate_venv_and_relaunch()
            return
    elif not is_venv_active() and not os.path.exists(VENV_DIR):
        if input("Créer un venv ? (o/n) : ").lower() == 'o':
            if create_venv():
                activate_venv_and_relaunch()
                return

    # Configuration (instance partagée sur tout le cycle de vie)
    config = ConfigManager()

    # Dépendances
    if not install_dependencies():
        if input("\n⚠️ Continuer sans toutes les dépendances ? (o/n) : ").lower() != 'o':
            return

    # Tor
    print("\n🌐 Initialisation de Tor…")
    tor_ok, tor_msg = setup_tor(config)
    print(f"   {'✅' if tor_ok else '❌'} {tor_msg}")

    if not tor_ok:
        print("\n1. Réessayer (téléchargement binaire Tor)")
        print("2. Continuer sans Tor (vidéos uniquement, scans indisponibles)")
        print("3. Quitter")
        choice = input("\n👉 Choix : ").strip()
        if choice == '1':
            tor_ok, tor_msg = setup_tor(config)
            print(f"{'✅' if tor_ok else '❌'} {tor_msg}")
        elif choice == '3':
            return

    # Boucle principale
    while not ConfigManager.should_stop():
        try:
            show_main_menu()
            choice = input("👉 Choix : ").strip()

            if choice == '1':
                call_catalogue()

            elif choice == '2':
                print("\n💡 Exemples d'URL :")
                print("   📚 .../catalogue/serie/scan/vf/")
                print("   🎬 .../catalogue/serie/saison1/vostfr/")
                url = input("\n🔗 URL : ").strip()
                if url:
                    call_downloader(url)

            elif choice == '3':
                call_batch_downloader()

            elif choice == '4':
                show_config_menu(config)

            elif choice == '5':
                check_system()
                input("\n↩️ Entrée pour continuer…")

            elif choice == '6':
                show_help()

            elif choice == '7':
                print("\n👋 Au revoir !")
                break

            else:
                print("❌ Choix invalide")

            # Réinitialiser le flag après traitement propre
            ConfigManager.reset_shutdown()

        except KeyboardInterrupt:
            # Ctrl+C entre deux opérations → on propose de quitter
            ConfigManager.reset_shutdown()
            if input("\n\n⚠️ Quitter ? (o/n) : ").lower() == 'o':
                print("👋 Au revoir !")
                break

        except Exception as e:
            print(f"\n❌ Erreur : {e}")
            input("\n↩️ Entrée pour continuer…")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Programme interrompu")
    except Exception as e:
        print(f"\n❌ Erreur fatale : {e}")
        import traceback
        traceback.print_exc()
