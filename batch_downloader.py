import os
import re
from typing import List, Optional

from config import ConfigManager


# ============================================================================
# REPRÉSENTATION D'UNE ENTRÉE
# ============================================================================

class BatchDownloadEntry:
    """Représente une ligne du fichier batch (URL + sélection d'épisodes)."""

    def __init__(self, url: str, episodes: str, line_number: int):
        self.url           = url.strip()
        self.episodes_str  = episodes.strip()
        self.line_number   = line_number
        self.episodes_list: List = []
        self.is_valid      = False
        self.error_message: Optional[str] = None
        self._parse()

    def _parse(self) -> None:
        if not self.url.startswith('http'):
            self.error_message = "URL invalide (doit commencer par http)"
            return
        try:
            self.episodes_list = self._parse_episodes(self.episodes_str)
            if not self.episodes_list:
                self.error_message = "Aucun épisode valide"
                return
            self.is_valid = True
        except Exception as e:
            self.error_message = f"Erreur parsing épisodes : {e}"

    def _parse_episodes(self, raw: str) -> List:
        """
        Accepte : 'all', '5', '1-5', '1,3,5', '1-3,7,10-12'
        Retourne ['all'] ou une liste triée d'entiers.
        """
        raw = raw.lower().strip()
        if raw == 'all':
            return ['all']

        episodes: set = set()
        for part in raw.split(','):
            part = part.strip()
            if '-' in part:
                s, e = part.split('-', 1)
                start, end = int(s.strip()), int(e.strip())
                if start > end:
                    raise ValueError(f"Plage invalide : {start}-{end}")
                episodes.update(range(start, end + 1))
            else:
                ep = int(part)
                if ep < 1:
                    raise ValueError(f"Numéro invalide : {ep}")
                episodes.add(ep)

        return sorted(episodes)

    def __repr__(self) -> str:
        status = "✅" if self.is_valid else "❌"
        eps    = "all" if self.episodes_list == ['all'] else f"{len(self.episodes_list)} ep"
        return f"[L{self.line_number}] {status} {self.url} → {eps}"


# ============================================================================
# PARSER DU FICHIER
# ============================================================================

class BatchDownloadParser:
    """Lit et valide un fichier batch."""

    def __init__(self, filepath: str):
        self.filepath      = filepath
        self.entries:          List[BatchDownloadEntry] = []
        self.valid_entries:    List[BatchDownloadEntry] = []
        self.invalid_entries:  List[BatchDownloadEntry] = []

    def parse(self) -> bool:
        """Retourne True si au moins une entrée valide."""
        if not os.path.exists(self.filepath):
            print(f"❌ Fichier non trouvé : {self.filepath}")
            return False

        print(f"\n📄 Lecture : {self.filepath}")
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"❌ Erreur lecture : {e}")
            return False

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            m = re.match(r'\[(.*?)\]\s*/\s*\[(.*?)\]', line)
            if not m:
                print(f"⚠️ Ligne {line_num} : format invalide (attendu : [URL] / [Episodes])")
                continue

            url, episodes = m.groups()
            entry = BatchDownloadEntry(url, episodes, line_num)
            self.entries.append(entry)
            (self.valid_entries if entry.is_valid else self.invalid_entries).append(entry)

        print(f"\n📊 Résumé parsing :")
        print(f"   • Total    : {len(self.entries)}")
        print(f"   • Valides  : {len(self.valid_entries)}")
        print(f"   • Invalides: {len(self.invalid_entries)}")

        if self.invalid_entries:
            print("\n⚠️ Entrées invalides :")
            for e in self.invalid_entries:
                print(f"   Ligne {e.line_number} : {e.error_message}")

        return len(self.valid_entries) > 0


# ============================================================================
# GESTIONNAIRE D'EXÉCUTION
# ============================================================================

class BatchDownloadManager:
    """Orchestre l'exécution séquentielle des téléchargements batch."""

    def __init__(self, entries: List[BatchDownloadEntry], config: ConfigManager):
        self.entries    = entries
        self.config     = config
        self.successful: List[BatchDownloadEntry] = []
        self.failed:     List[BatchDownloadEntry] = []
        self.skipped:    List[BatchDownloadEntry] = []

    def run(self) -> None:
        total = len(self.entries)
        print(f"\n{'='*60}")
        print(f"🚀 TÉLÉCHARGEMENT BATCH – {total} entrée(s)")
        print(f"{'='*60}")

        print("\n📋 Liste :")
        for idx, e in enumerate(self.entries, 1):
            eps = "all" if e.episodes_list == ['all'] else f"{len(e.episodes_list)} ep"
            print(f"   {idx}. {e.url}")
            print(f"      → {eps} : {e.episodes_str}")

        if input(f"\n❓ Télécharger ces {total} entrée(s) ? (o/n) : ").strip().lower() != 'o':
            print("↩️ Annulé")
            return

        try:
            import downloader as dl_module
        except ImportError:
            print("❌ downloader.py non trouvé")
            return

        for idx, entry in enumerate(self.entries, 1):
            if ConfigManager.should_stop():
                self.skipped.extend(self.entries[idx - 1:])
                break

            print(f"\n{'#'*60}")
            print(f"# ENTRÉE {idx}/{total} (Ligne {entry.line_number})")
            print(f"{'#'*60}")
            print(f"🔗 URL : {entry.url}")
            print(f"📺 Épisodes : {entry.episodes_str}")

            try:
                info  = dl_module.classify_url(entry.url)
                ctype = info['type']
                print(f"📂 Type : {ctype.upper()}")

                success = (
                    self._process_scan(entry, dl_module)
                    if ctype == 'scan'
                    else self._process_video(entry, dl_module)
                )
                (self.successful if success else self.failed).append(entry)
                print(f"\n{'✅' if success else '❌'} Entrée {idx}")

            except KeyboardInterrupt:
                ConfigManager.request_shutdown()
                self.skipped.extend(self.entries[idx:])
                break
            except Exception as e:
                print(f"\n❌ Erreur : {e}")
                self.failed.append(entry)

        self._print_summary()

    # ------------------------------------------------------------------ #

    def _process_scan(self, entry: BatchDownloadEntry, dl_module) -> bool:
        try:
            dl = dl_module.ScanDownloader(entry.url, self.config)

            series_name = dl.extract_series_name()
            if not series_name:
                print("❌ Impossible d'extraire le nom de série")
                return False

            import urllib.parse
            dl.encoded_series_name = urllib.parse.quote(series_name)
            dl.exact_series_name   = series_name

            chapters_data = dl.get_chapters_from_api(series_name)
            if not chapters_data:
                print("❌ Impossible de récupérer les chapitres")
                return False

            print(f"📚 {len(chapters_data)} chapitre(s) disponible(s)")

            if entry.episodes_list == ['all']:
                chapters_to_dl = sorted(chapters_data, key=int)
                print(f"📥 Tous les chapitres ({len(chapters_to_dl)})")
            else:
                chapters_to_dl = [str(c) for c in entry.episodes_list if str(c) in chapters_data]
                excluded = [c for c in entry.episodes_list if str(c) not in chapters_data]
                if excluded:
                    print(f"⚠️ Chapitres inexistants ignorés : {excluded}")
                print(f"📥 {len(chapters_to_dl)} chapitre(s)")

            if not chapters_to_dl:
                print("❌ Aucun chapitre valide")
                return False

            successful, failed = [], []
            for i, ch in enumerate(chapters_to_dl, 1):
                print(f"\n{'='*50}")
                print(f"📖 Chapitre {ch} ({i}/{len(chapters_to_dl)})")
                print(f"{'='*50}")
                try:
                    if dl.download_chapter(ch, chapters_data[ch]):
                        successful.append(ch)
                    else:
                        failed.append(ch)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"❌ Erreur : {e}")
                    failed.append(ch)

            print(f"\n📊 Scans : {len(successful)}/{len(chapters_to_dl)} réussis")
            return len(successful) > 0

        except Exception as e:
            print(f"❌ Erreur scan : {e}")
            return False

    def _process_video(self, entry: BatchDownloadEntry, dl_module) -> bool:
        try:
            dl = dl_module.VideoDownloader(entry.url, self.config)

            if not dl.download_episodes_js():
                print("❌ Impossible de télécharger episodes.js")
                return False

            players = dl.parse_episodes_js()
            if not players:
                print("❌ Aucun lecteur trouvé")
                return False

            # Sélection automatique : lecteur préféré (config) ou priorité par défaut
            preferred = self.config.get("batch", "player", default="")
            selected  = None

            if preferred:
                for _, data in players.items():
                    if data['type'].lower() == preferred.lower():
                        selected = data
                        print(f"✅ Lecteur configuré : {data['type'].upper()}")
                        break

            if not selected:
                ordered = sorted(
                    players.values(),
                    key=lambda d: (
                        dl.player_priority.index(d['type'])
                        if d['type'] in dl.player_priority else 999
                    ),
                )
                if ordered:
                    selected = ordered[0]
                    print(f"✅ Lecteur auto : {selected['type'].upper()}")

            if not selected:
                print("❌ Aucun lecteur valide")
                return False

            total_eps    = selected['count']
            player_type  = selected['type']
            player_links = selected['links']
            print(f"📺 {total_eps} épisode(s) disponible(s)")

            if entry.episodes_list == ['all']:
                episodes_to_dl = list(range(1, total_eps + 1))
                print(f"📥 Tous les épisodes (1-{total_eps})")
            else:
                episodes_to_dl = [ep for ep in entry.episodes_list if ep <= total_eps]
                excluded = [ep for ep in entry.episodes_list if ep > total_eps]
                if excluded:
                    print(f"⚠️ Épisodes hors plage ignorés : {excluded}")
                print(f"📥 {len(episodes_to_dl)} épisode(s)")

            if not episodes_to_dl:
                print("❌ Aucun épisode valide")
                return False

            successful, failed = [], []
            for i, ep_num in enumerate(episodes_to_dl, 1):
                print(f"\n{'='*50}")
                print(f"🎬 Épisode {ep_num} ({i}/{len(episodes_to_dl)})")
                print(f"{'='*50}")
                ep_idx = ep_num - 1
                if ep_idx >= len(player_links):
                    print(f"❌ Épisode {ep_num} inexistant")
                    failed.append(ep_num)
                    continue
                try:
                    if dl.download_episode(ep_num, player_links[ep_idx], player_type):
                        successful.append(ep_num)
                    else:
                        failed.append(ep_num)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"❌ Erreur : {e}")
                    failed.append(ep_num)

            print(f"\n📊 Vidéos : {len(successful)}/{len(episodes_to_dl)} réussies")
            return len(successful) > 0

        except Exception as e:
            print(f"❌ Erreur vidéo : {e}")
            return False

    def _print_summary(self) -> None:
        print(f"\n{'='*60}")
        print("📊 RÉSUMÉ BATCH FINAL")
        print(f"{'='*60}")
        print(f"✅ Succès  : {len(self.successful)}")
        print(f"❌ Échecs  : {len(self.failed)}")
        print(f"⭕ Ignorés : {len(self.skipped)}")

        if self.failed:
            print("\n❌ Entrées échouées :")
            for e in self.failed:
                print(f"   • Ligne {e.line_number} : {e.url}")

        if self.skipped:
            print("\n⭕ Entrées ignorées :")
            for e in self.skipped:
                print(f"   • Ligne {e.line_number} : {e.url}")


# ============================================================================
# API PUBLIQUE
# ============================================================================

def process_batch_file(filepath: str) -> bool:
    """
    Point d'entrée principal : parse le fichier et lance les téléchargements.

    Returns:
        True si au moins un téléchargement a réussi.
    """
    config = ConfigManager()
    parser = BatchDownloadParser(filepath)

    if not parser.parse():
        print("\n❌ Aucune entrée valide à traiter")
        return False

    print(f"\n✅ {len(parser.valid_entries)} entrée(s) valide(s) :")
    for entry in parser.valid_entries:
        eps = "all" if entry.episodes_list == ['all'] else f"{len(entry.episodes_list)} ep"
        print(f"   • Ligne {entry.line_number} : {eps}")

    manager = BatchDownloadManager(parser.valid_entries, config)
    manager.run()
    return len(manager.successful) > 0


def create_example_file(filepath: str = "downloads.txt") -> bool:
    """Crée un fichier batch d'exemple."""
    content = """\
# Fichier de téléchargements batch
# Format : [URL] / [Episodes]
#
# Formats d'épisodes :
#   all       → tous les épisodes/chapitres
#   5         → épisode/chapitre 5 uniquement
#   1-5       → épisodes 1 à 5
#   1,3,5     → épisodes 1, 3 et 5
#   1-3,7,10-12 → combinaison

[https://anime-sama.si/catalogue/fire-force/saison3-2/vf/] / [1-3]
[https://anime-sama.si/catalogue/the-mafia-nanny/scan/vf/] / [13]
[https://anime-sama.si/catalogue/hell-mode/saison1/vostfr/] / [all]
"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Fichier exemple créé : {filepath}")
        return True
    except Exception as e:
        print(f"❌ Erreur : {e}")
        return False
