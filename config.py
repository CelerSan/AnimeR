
import os
import json
import threading
from typing import Any, Optional

CONFIG_FILE = "config.json"
VERSION = "2.2"


class ConfigManager:
    """
    Gestionnaire de configuration JSON unique pour tout le projet.

    Fusionne les logiques précédemment dupliquées dans main.py et
    downloader.py. Expose une interface uniforme get/set avec notation
    pointée et gère la lecture/écriture du fichier config.json.

    Thread-safe via un verrou interne.
    """

    # Flag d'interruption globale (modifié par le gestionnaire SIGINT de main.py)
    shutdown_requested: bool = False
    _lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Valeurs par défaut (source unique de vérité)
    # ------------------------------------------------------------------ #
    _DEFAULTS: dict = {
        "_version": VERSION,
        "directories": {
            "download_base": ""
        },
        "tor": {
            "proxy_host": "127.0.0.1",
            "proxy_port": 9050,
            "control_port": 9051,
            "auto_download_binary": True
        },
        "downloads": {
            "max_threads": 16,
            "min_file_size_mb": 1
        },
        "scans": {
            "min_delay_seconds": 1,
            "max_delay_seconds": 3,
            "max_retries_per_page": 3
        },
        "videos": {
            "player_priority": ["sibnet", "sendvid", "vidmoly", "oneupload", "movearn"],
            "download_timeout_seconds": 3600
        },
        "batch": {
            "player": ""
        },
        "debug": {
            "save_vidmoly_html": False
        },
        "ui": {
            "verbose_mode": True,
            "language": "fr"
        }
    }

    # ------------------------------------------------------------------ #
    # Initialisation
    # ------------------------------------------------------------------ #

    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = config_path
        self.config: dict = {}
        self._load()

    def _load(self) -> None:
        """Charge la configuration depuis le disque ou crée le fichier."""
        if not os.path.exists(self.config_path):
            print(f"📄 Création de {self.config_path}…")
            self.config = self._deep_copy(self._DEFAULTS)
            self._write()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            # Fusionner avec les défauts pour les clés manquantes
            self.config = self._merge(self._deep_copy(self._DEFAULTS), loaded)
        except Exception as e:
            print(f"⚠️ Erreur lecture config ({e}), utilisation des valeurs par défaut")
            self.config = self._deep_copy(self._DEFAULTS)

    # ------------------------------------------------------------------ #
    # API publique : lecture
    # ------------------------------------------------------------------ #

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Récupère une valeur par chemin de clés.

        Exemples :
            cfg.get("directories", "download_base")
            cfg.get("downloads", "max_threads", default=8)
        """
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_download_base_dir(self) -> str:
        """
        Retourne le répertoire de base des téléchargements.

        Priorité : directories.download_base → fallback ./AnimeRT
        Crée le dossier s'il n'existe pas.
        """
        config_dir = self.get("directories", "download_base", default="").strip()

        if not config_dir:
            config_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "AnimeRT"
            )
            print(f"📂 Répertoire par défaut : {config_dir}")
        else:
            print(f"📂 Répertoire configuré : {config_dir}")

        os.makedirs(config_dir, exist_ok=True)
        return config_dir

    def get_player_priority(self) -> list:
        """Retourne la liste ordonnée des lecteurs vidéo préférés."""
        return self.get(
            "videos", "player_priority",
            default=["sibnet", "sendvid", "vidmoly", "oneupload", "movearn"]
        )

    def get_scan_delays(self) -> tuple:
        """Retourne (min_delay, max_delay) en secondes pour les scans."""
        return (
            self.get("scans", "min_delay_seconds", default=1),
            self.get("scans", "max_delay_seconds", default=3),
        )

    def get_max_threads(self) -> int:
        return self.get("downloads", "max_threads", default=16)

    def get_min_file_size(self) -> int:
        """Retourne la taille minimale de fichier valide en octets."""
        mb = self.get("downloads", "min_file_size_mb", default=1)
        return mb * 1024 * 1024

    def is_tor_auto_download(self) -> bool:
        return self.get("tor", "auto_download_binary", default=True)

    def is_verbose(self) -> bool:
        return self.get("ui", "verbose_mode", default=True)

    def is_debug_vidmoly(self) -> bool:
        return self.get("debug", "save_vidmoly_html", default=False)

    # ------------------------------------------------------------------ #
    # API publique : écriture
    # ------------------------------------------------------------------ #

    def set(self, *keys: str, value: Any) -> None:
        """
        Définit une valeur par chemin de clés (crée les niveaux manquants).

        Exemple :
            cfg.set("downloads", "max_threads", value=8)
        """
        with self._lock:
            node = self.config
            for key in keys[:-1]:
                if key not in node or not isinstance(node[key], dict):
                    node[key] = {}
                node = node[key]
            node[keys[-1]] = value

    def save(self) -> bool:
        """Sauvegarde la configuration sur le disque."""
        with self._lock:
            return self._write()

    # Alias rétrocompatible (ancienne méthode save_config)
    def save_config(self) -> bool:
        return self.save()

    def reset(self) -> None:
        """Réinitialise la configuration aux valeurs par défaut."""
        self.config = self._deep_copy(self._DEFAULTS)
        self._write()
        print("✅ Configuration réinitialisée")

    # ------------------------------------------------------------------ #
    # Flag d'interruption (utilisé par le gestionnaire SIGINT de main.py)
    # ------------------------------------------------------------------ #

    @classmethod
    def request_shutdown(cls) -> None:
        """Demande l'arrêt propre de toutes les boucles."""
        cls.shutdown_requested = True

    @classmethod
    def reset_shutdown(cls) -> None:
        """Réinitialise le flag (ex. : retour au menu après interruption)."""
        cls.shutdown_requested = False

    @classmethod
    def should_stop(cls) -> bool:
        """Retourne True si un arrêt a été demandé."""
        return cls.shutdown_requested

    # ------------------------------------------------------------------ #
    # Helpers internes
    # ------------------------------------------------------------------ #

    def _write(self) -> bool:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"❌ Erreur sauvegarde config : {e}")
            return False

    @staticmethod
    def _deep_copy(d: dict) -> dict:
        """Copie profonde sans dépendance externe."""
        return json.loads(json.dumps(d))

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        """
        Fusionne override dans base récursivement.
        Les valeurs de override écrasent celles de base ;
        les clés absentes de override sont conservées depuis base.
        """
        for key, val in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(val, dict):
                ConfigManager._merge(base[key], val)
            else:
                base[key] = val
        return base

    # ------------------------------------------------------------------ #
    # Représentation
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return f"ConfigManager(path={self.config_path!r}, shutdown={self.shutdown_requested})"
