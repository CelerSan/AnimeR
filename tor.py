import requests
import socket
import time
import random
import os
import sys
import platform
import subprocess
import tarfile
import zipfile
import shutil
import threading
import atexit
from typing import Optional
from pathlib import Path

# ============================================================================
# CONFIGURATION PROXY
# ============================================================================

PROXIES = {
    "http":  "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive"
}

# ============================================================================
# BINAIRE TOR : URLS ET CHEMINS
# ============================================================================

TOR_BIN_DIR = Path(__file__).parent / "tor_bin"

TOR_VERSION = "14.0.3"

# URLs officielles dist.torproject.org par plateforme
# Format : { (system, machine): (url, archive_type, chemin_binaire_dans_archive) }
TOR_DOWNLOAD_URLS = {
    ("Linux",   "x86_64"): (
        f"https://archive.torproject.org/tor-package-archive/torbrowser/{TOR_VERSION}/tor-expert-bundle-linux-x86_64-{TOR_VERSION}.tar.gz",
        "tar.gz",
        "tor/tor"
    ),
    ("Linux",   "aarch64"): (
        f"https://archive.torproject.org/tor-package-archive/torbrowser/{TOR_VERSION}/tor-expert-bundle-linux-aarch64-{TOR_VERSION}.tar.gz",
        "tar.gz",
        "tor/tor"
    ),
    ("Darwin",  "x86_64"): (
        f"https://archive.torproject.org/tor-package-archive/torbrowser/{TOR_VERSION}/tor-expert-bundle-macos-x86_64-{TOR_VERSION}.tar.gz",
        "tar.gz",
        "tor/tor"
    ),
    ("Darwin",  "arm64"): (
        f"https://archive.torproject.org/tor-package-archive/torbrowser/{TOR_VERSION}/tor-expert-bundle-macos-aarch64-{TOR_VERSION}.tar.gz",
        "tar.gz",
        "tor/tor"
    ),
    ("Windows", "AMD64"): (
        f"https://archive.torproject.org/tor-package-archive/torbrowser/{TOR_VERSION}/tor-expert-bundle-windows-x86_64-{TOR_VERSION}.tar.gz",
        "tar.gz",
        "tor/tor.exe"
    ),
}

TORRC_CONTENT = """\
SocksPort 9050
ControlPort 9051
CookieAuthentication 0
HashedControlPassword ""
DataDirectory {data_dir}
Log notice stderr
"""

# ============================================================================
# GESTIONNAIRE DE PROCESSUS TOR (singleton)
# ============================================================================

_tor_process: Optional[subprocess.Popen] = None
_tor_lock = threading.Lock()


def _get_platform_key() -> Optional[tuple]:
    """Retourne la clé (system, machine) pour la table d'URLs"""
    system  = platform.system()
    machine = platform.machine()
    # Normaliser les variantes
    if machine in ("x86_64", "AMD64"):
        machine = "x86_64" if system != "Windows" else "AMD64"
    return (system, machine)


def get_tor_binary_path() -> Optional[Path]:
    """Retourne le chemin du binaire Tor s'il existe déjà"""
    system = platform.system()
    binary_name = "tor.exe" if system == "Windows" else "tor"
    binary_path = TOR_BIN_DIR / binary_name
    return binary_path if binary_path.exists() else None


def get_torrc_path() -> Path:
    """Retourne le chemin du torrc gérer par ce module"""
    return TOR_BIN_DIR / "torrc"


def get_data_dir() -> Path:
    """Retourne le répertoire de données Tor"""
    return TOR_BIN_DIR / "data"


def _write_torrc():
    """Créer/met à jour le torrc dans TOR_BIN_DIR"""
    TOR_BIN_DIR.mkdir(parents=True, exist_ok=True)
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    torrc_path = get_torrc_path()
    content = TORRC_CONTENT.format(data_dir=str(data_dir))
    torrc_path.write_text(content, encoding="utf-8")
    return torrc_path


# ============================================================================
# TÃ‰LÃ‰CHARGEMENT ET EXTRACTION DU BINAIRE
# ============================================================================

def download_tor_binary(verbose: bool = True) -> bool:
    """
    Télécharge et extrait le binaire Tor Expert Bundle pour la plateforme courante.

    Returns:
        True si le binaire est disponible après l'opération, False sinon.
    """
    # Déjà présent ?
    if get_tor_binary_path():
        if verbose:
            print(f"Binaire Tor déjà présent: {get_tor_binary_path()}")
        return True

    key = _get_platform_key()
    if key not in TOR_DOWNLOAD_URLS:
        system, machine = platform.system(), platform.machine()
        print(f" Plateforme non supportée: {system} / {machine}")
        print("   Plateformes supportées: Linux x86_64/aarch64, macOS x86_64/arm64(dépressié), Windows x64")
        return False

    url, archive_type, bin_path_in_archive = TOR_DOWNLOAD_URLS[key]

    TOR_BIN_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = TOR_BIN_DIR / f"tor_bundle.{archive_type}"

    # â€” Téléchargement â€”
    if verbose:
        print(f"ðŸ“¥ Téléchargement Tor Expert Bundle...")
        print(f"   Source: {url}")

    try:
        # On utilise une session sans proxy pour le téléchargement initial
        session = requests.Session()
        with session.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(archive_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if verbose and total:
                            pct = downloaded * 100 // total
                            print(f"\r   {pct}% ({downloaded // 1024} Ko / {total // 1024} Ko)", end="", flush=True)
        if verbose:
            print(f"\râœ… Téléchargement terminé ({downloaded // 1024} Ko)        ")
    except Exception as e:
        print(f"\nâŒ Erreur téléchargement: {e}")
        if archive_path.exists():
            archive_path.unlink()
        return False

    # â€” Extraction â€”
    if verbose:
        print(f"ðŸ“¦ Extraction de l'archive...")

    extract_dir = TOR_BIN_DIR / "extracted"
    extract_dir.mkdir(exist_ok=True)

    try:
        if archive_type == "tar.gz":
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(extract_dir)
        elif archive_type == "zip":
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(extract_dir)
        else:
            print(f"âŒ Format d'archive inconnu: {archive_type}")
            return False
    except Exception as e:
        print(f"âŒ Erreur extraction: {e}")
        return False

    # â€” Copie du binaire â€”
    src = extract_dir / bin_path_in_archive
    if not src.exists():
        # Chercher le binaire dans tous les sous-dossiers (au cas oÃ¹ la structure change)
        bin_name = Path(bin_path_in_archive).name
        found = list(extract_dir.rglob(bin_name))
        if found:
            src = found[0]
        else:
            print(f"âŒ Binaire '{bin_name}' introuvable dans l'archive")
            print(f"   Contenu: {list(extract_dir.rglob('*'))[:10]}")
            return False

    system = platform.system()
    dest_name = "tor.exe" if system == "Windows" else "tor"
    dest = TOR_BIN_DIR / dest_name

    shutil.copy2(src, dest)

    # Rendre exécutable sur Unix
    if system != "Windows":
        dest.chmod(0o755)

    # Copier aussi les bibliothèques partagées si présentes (Linux)
    for lib_file in src.parent.glob("*.so*"):
        shutil.copy2(lib_file, TOR_BIN_DIR)

    # Nettoyage
    shutil.rmtree(extract_dir, ignore_errors=True)
    archive_path.unlink(missing_ok=True)

    if verbose:
        print(f"âœ… Binaire Tor extrait: {dest}")

    return True


# ============================================================================
# DÃ‰MARRAGE / ARRÃŠT DU PROCESSUS TOR
# ============================================================================

def is_tor_running_on_port(port: int = 9050) -> bool:
    """Vérifie si quelque chose écoute sur le port SOCKS Tor"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def start_tor(verbose: bool = True, timeout: int = 30) -> bool:
    """
    Démarre le processus Tor depuis le binaire embarqué.
    Si Tor est déjà actif (service système ou précédent démarrage), ne fait rien.

    Returns:
        True si Tor est opérationnel, False sinon.
    """
    global _tor_process

    with _tor_lock:
        # Déjà en cours (notre processus ou service système)
        if is_tor_running_on_port(9050):
            if verbose:
                print("âœ… Tor est déjà actif sur le port 9050")
            return True

        # Vérifier/télécharger le binaire
        binary = get_tor_binary_path()
        if not binary:
            if verbose:
                print("ðŸ“¥ Binaire Tor absent, téléchargement...")
            if not download_tor_binary(verbose=verbose):
                return False
            binary = get_tor_binary_path()

        if not binary:
            print("âŒ Binaire Tor introuvable après téléchargement")
            return False

        # Ã‰crire le torrc
        torrc = _write_torrc()

        if verbose:
            print(f"ðŸš€ Démarrage de Tor...")

        try:
            system = platform.system()

            if system == "Windows":
                _tor_process = subprocess.Popen(
                    [str(binary), "-f", str(torrc)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                # Linux / macOS : les librairies .so du bundle (libssl, libcrypto, etc.)
                # sont dans le même dossier que le binaire. Sans LD_LIBRARY_PATH pointant
                # vers ce dossier, Tor ne démarre pas s'il ne trouve pas ses .so système.
                env = os.environ.copy()
                tor_bin_dir = str(binary.parent)
                existing = env.get("LD_LIBRARY_PATH", "")
                env["LD_LIBRARY_PATH"] = f"{tor_bin_dir}:{existing}" if existing else tor_bin_dir

                _tor_process = subprocess.Popen(
                    [str(binary), "-f", str(torrc)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # détache du terminal courant
                    env=env,                 # indispensable pour trouver les .so
                )
        except Exception as e:
            print(f"âŒ Impossible de démarrer Tor: {e}")
            return False

        # Attendre que Tor soit prêt (connexion SOCKS disponible)
        deadline = time.time() + timeout
        bootstrapped = False

        while time.time() < deadline:
            # Lire la sortie pour détecter le bootstrapping
            if _tor_process.poll() is not None:
                output = _tor_process.stdout.read().decode(errors="replace")
                print(f"âŒ Tor s'est arrêté prématurément:\n{output[-500:]}")
                return False

            if is_tor_running_on_port(9050):
                bootstrapped = True
                break

            # Afficher progression si verbose
            if verbose:
                line = _tor_process.stdout.readline().decode(errors="replace").strip()
                if line and "Bootstrapped" in line:
                    pct = ""
                    import re
                    m = re.search(r"Bootstrapped (\d+)%", line)
                    if m:
                        pct = f" [{m.group(1)}%]"
                    print(f"   â³ Connexion au réseau Tor{pct}...", end="\r", flush=True)
            else:
                time.sleep(0.5)

        if bootstrapped:
            if verbose:
                print("\nâœ… Tor démarré et connecté                    ")
            # Enregistrer l'arrêt automatique à la fin du programme
            atexit.register(stop_tor)
            return True
        else:
            if verbose:
                print(f"\nâŒ Timeout ({timeout}s): Tor n'a pas démarré")
            stop_tor()
            return False


def stop_tor(verbose: bool = False):
    """Arrête le processus Tor géré par ce module"""
    global _tor_process
    with _tor_lock:
        if _tor_process and _tor_process.poll() is None:
            if verbose:
                print("ðŸ›‘ Arrêt de Tor...")
            _tor_process.terminate()
            try:
                _tor_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _tor_process.kill()
            _tor_process = None


def ensure_tor(verbose: bool = True) -> bool:
    """
    Point d'entrée principal : s'assure que Tor est opérationnel.
    Télécharge le binaire si nécessaire, démarre Tor si nécessaire.

    Returns:
        True si Tor est prêt à l'emploi.
    """
    # Déjà actif ?
    if is_tor_running_on_port(9050):
        return True

    # Lancer depuis le binaire embarqué
    return start_tor(verbose=verbose)


# ============================================================================
# IDENTITÃ‰ / ROTATION IP
# ============================================================================

def change_identity(verbose: bool = False) -> bool:
    """
    Change l'identité Tor via ControlPort (NEWNYM).
    Fonctionne avec le torrc embarqué (CookieAuthentication 0, pas de mot de passe).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(("127.0.0.1", 9051))

            # Authentification sans mot de passe (torrc embarqué)
            s.sendall(b'AUTHENTICATE ""\r\n')
            response = s.recv(1024).decode()

            if "250" not in response:
                # Fallback: auth sans argument
                s.sendall(b"AUTHENTICATE\r\n")
                response = s.recv(1024).decode()
                if "250" not in response:
                    if verbose:
                        print(f"âŒ Auth ControlPort échouée: {response.strip()}")
                    return False

            s.sendall(b"SIGNAL NEWNYM\r\n")
            response = s.recv(1024).decode()
            success = "250" in response

            if verbose:
                if success:
                    print("âœ… Nouvelle identité Tor")
                else:
                    print(f"âŒ Ã‰chec NEWNYM: {response.strip()}")

            return success

    except (socket.timeout, ConnectionRefusedError) as e:
        if verbose:
            print(f"âŒ ControlPort inaccessible: {e}")
        return False
    except Exception as e:
        if verbose:
            print(f"âŒ Erreur: {e}")
        return False


# ============================================================================
# DÃ‰TECTION DE BLOCAGE
# ============================================================================

def is_blocked(response_text: str) -> bool:
    """Détecte si la réponse indique un blocage (Cloudflare, WAF, etc.)"""
    text_lower = response_text.lower()

    strict_blocks = [
        "you have been blocked",
        "your access has been blocked",
        "access denied",
        "403 forbidden",
        "attention required",
        "enable javascript and cookies",
        "please complete the security check",
        "checking your browser",
        "please stand by, while we are checking your browser",
        "ray id:",
    ]

    if any(indicator in text_lower for indicator in strict_blocks):
        return True

    # Cloudflare spécifique
    if "cloudflare" in text_lower:
        cf_signs = [
            "<title>attention required",
            "<title>just a moment",
            "cf-error-details",
            "cf-wrapper",
            "challenge-platform",
            "cf_clearance",
        ]
        return any(sign in text_lower for sign in cf_signs)

    return False


# ============================================================================
# VÃ‰RIFICATION CONNEXION TOR
# ============================================================================

def verify_tor_connection(verbose: bool = False) -> bool:
    """Vérifie que les requêtes passent bien par Tor"""
    try:
        response = requests.get(
            "https://check.torproject.org/api/ip",
            proxies=PROXIES,
            timeout=15
        )
        data = response.json()
        is_tor = data.get("IsTor", False)

        if verbose:
            if is_tor:
                print(f"âœ… Connexion Tor active â€” IP: {data.get('IP')}")
            else:
                print(f"âŒ Pas de Tor â€” IP réelle: {data.get('IP')}")

        return is_tor
    except Exception as e:
        if verbose:
            print(f"âŒ Vérification Tor impossible: {e}")
        return False


# ============================================================================
# REQUÃŠTE GET VIA TOR
# ============================================================================

def tor_get(
    url: str,
    max_attempts: int = 5,
    timeout: int = 20,
    verbose: bool = False,
    random_delay: bool = False,
    min_delay: float = 1.0,
    max_delay: float = 3.0,
    auto_start: bool = True,
) -> Optional[requests.Response]:
    """
    Effectue une requête GET via Tor.

    Args:
        url:          URL à récupérer.
        max_attempts: Nombre maximum de tentatives.
        timeout:      Timeout HTTP en secondes.
        verbose:      Afficher les messages de progression.
        random_delay: Ajouter un délai aléatoire entre tentatives.
        min_delay:    Délai minimum (si random_delay=True).
        max_delay:    Délai maximum (si random_delay=True).
        auto_start:   Démarrer Tor automatiquement si inactif.

    Returns:
        requests.Response en cas de succès, None sinon.
    """
    # S'assurer que Tor est actif
    if auto_start:
        if not ensure_tor(verbose=verbose):
            if verbose:
                print("âŒ Impossible de démarrer Tor")
            return None
    elif not is_tor_running_on_port(9050):
        if verbose:
            print("âŒ Tor inactif et auto_start=False")
        return None

    for attempt in range(1, max_attempts + 1):
        if verbose:
            print(f"\n[{attempt}/{max_attempts}] GET {url[:80]}...")

        if random_delay and attempt > 1:
            delay = random.uniform(min_delay, max_delay)
            if verbose:
                print(f"  â³ Attente {delay:.1f}s")
            time.sleep(delay)

        try:
            response = requests.get(
                url,
                proxies=PROXIES,
                headers=HEADERS,
                timeout=timeout
            )

            if response.status_code in (403, 429, 503) or is_blocked(response.text):
                if verbose:
                    print(f"  ðŸ”„ Blocage détecté (HTTP {response.status_code}) â€” rotation IP...")
                change_identity(verbose=verbose)
                time.sleep(random.uniform(5, 8) if random_delay else 5)
                continue

            if response.status_code == 200:
                if verbose:
                    print("  âœ… Succès")
                return response

            if verbose:
                print(f"  âš ï¸ HTTP {response.status_code}, nouvelle tentative...")
            change_identity(verbose=verbose)
            time.sleep(3)

        except requests.exceptions.ProxyError as e:
            if verbose:
                print(f"  âŒ Erreur proxy Tor: {e}")
            # Tor peut avoir besoin d'un moment pour se reconnecter
            time.sleep(3)
            continue

        except requests.exceptions.Timeout:
            if verbose:
                print(f"  â±ï¸ Timeout ({timeout}s)")
            change_identity(verbose=verbose)
            time.sleep(2)

        except Exception as e:
            if verbose:
                print(f"  âŒ Erreur: {e}")
            change_identity(verbose=verbose)
            time.sleep(2)

    if verbose:
        print("\nâŒ Ã‰chec après toutes les tentatives")
    return None


# ============================================================================
# SCRIPT DE TEST
# ============================================================================

