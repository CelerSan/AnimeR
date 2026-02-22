
import os
import re
import json
import time
import random
import subprocess
import urllib.parse
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import tor
from config import ConfigManager

# --- Dépendances optionnelles ---
try:
    import requests
    from bs4 import BeautifulSoup
    import img2pdf
    DEPENDENCIES_OK = True
except ImportError as e:
    print(f"❌ Dépendance manquante : {e}")
    print("💡 Installation : pip install requests beautifulsoup4 img2pdf PySocks")
    DEPENDENCIES_OK = False

try:
    from rich.console import Console
    from rich.progress import (
        Progress, TextColumn, BarColumn, TaskProgressColumn,
        TimeRemainingColumn, DownloadColumn, TransferSpeedColumn,
    )
    console = Console()
    RICH_OK = True
except ImportError:
    RICH_OK = False
    # Stub minimal pour que le code s'exécute sans Rich
    class _FakeConsole:
        def print(self, *args, **kwargs):
            # Nettoie les balises Rich basiques avant d'afficher
            text = " ".join(str(a) for a in args)
            text = re.sub(r'\[/?[a-z_ ]+\]', '', text)
            print(text)
    console = _FakeConsole()


# ============================================================================
# PARSER D'URL  (source unique — importé par rien d'autre dans ce projet)
# ============================================================================

class URLParser:
    """Parse et classifie les URLs anime-sama."""

    SCAN_MARKERS  = ('/scan/',)
    VIDEO_MARKERS = ('/film/', '/saison', '/oav/', '/ova/', '/kai/', '/special/', '/movie/')
    LANG_CODES    = {'vf', 'vostfr', 'vo', 'fr', 'en', 'vf1', 'vf2', 'va', 'vj'}

    @staticmethod
    def detect_content_type(url: str) -> str:
        """Retourne 'scan', 'video' ou 'unknown'."""
        url_lower = url.lower()
        if any(m in url_lower for m in URLParser.SCAN_MARKERS):
            return 'scan'
        if any(m in url_lower for m in URLParser.VIDEO_MARKERS):
            return 'video'
        return 'unknown'

    @staticmethod
    def parse_url(url: str) -> Dict:
        """
        Retourne un dict avec :
            serie_name, content_type, content_number, language,
            is_scan, full_url
        """
        result = {
            'serie_name':     None,
            'content_type':   None,
            'content_number': None,
            'language':       None,
            'is_scan':        False,
            'full_url':       url,
        }
        try:
            parts = url.lower().split('/')
            cat_idx = next((i for i, p in enumerate(parts) if 'catalogue' in p), -1)
            if cat_idx < 0 or cat_idx + 1 >= len(parts):
                return result

            result['serie_name'] = parts[cat_idx + 1].strip('/')

            if cat_idx + 2 < len(parts):
                content = parts[cat_idx + 2]
                if content == 'scan':
                    result['content_type'] = 'scan'
                    result['is_scan']      = True
                elif 'saison' in content:
                    result['content_type'] = 'anime'
                    m = re.search(r'saison(\d+)', content)
                    if m:
                        result['content_number'] = m.group(1)
                elif content == 'film':
                    result['content_type'] = 'film'
                elif content in ('oav', 'ova', 'kai', 'special', 'movie'):
                    result['content_type'] = content

            if cat_idx + 3 < len(parts):
                lang = parts[cat_idx + 3].strip('/')
                if lang in URLParser.LANG_CODES:
                    result['language'] = lang
        except Exception:
            pass
        return result


# ============================================================================
# UTILITAIRES COMMUNS
# ============================================================================

def _check_interrupt() -> None:
    """Lève KeyboardInterrupt si un arrêt a été demandé via ConfigManager."""
    if ConfigManager.should_stop():
        raise KeyboardInterrupt("Arrêt demandé")


# ============================================================================
# TÉLÉCHARGEUR DE SCANS
# ============================================================================

class ScanDownloader:
    """Télécharge des chapitres de scan et les convertit en PDF."""

    BASE_API = "https://anime-sama.tv/s2/scans/get_nb_chap_et_img.php"

    def __init__(self, url: str, config: ConfigManager):
        self.scan_url  = url.rstrip('/')
        self.config    = config
        self.url_info  = URLParser.parse_url(url)

        parsed = urllib.parse.urlparse(url)
        self.base_domain    = f"{parsed.scheme}://{parsed.netloc}"
        self.base_image_url = f"{self.base_domain}/s2/scans/"

        self.exact_series_name:   Optional[str] = None
        self.encoded_series_name: Optional[str] = None

        # Construction du dossier de destination
        base_dir   = config.get_download_base_dir()
        serie_name = self.url_info.get('serie_name') or 'unknown'
        lang       = self.url_info.get('language')

        self.download_dir = os.path.join(base_dir, serie_name, "Scans")
        if lang:
            self.download_dir = os.path.join(self.download_dir, lang.upper())

        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        print(f"📂 Dossier : {self.download_dir}")

    # ------------------------------------------------------------------ #

    def extract_series_name(self) -> Optional[str]:
        """Extrait le nom exact de la série depuis la balise <h3 id='titreOeuvre'>."""
        _check_interrupt()
        print("🔍 Extraction du nom de série…")

        response = tor.tor_get(self.scan_url, max_attempts=5, timeout=20, verbose=False)
        if not response:
            print("❌ Impossible de récupérer la page")
            return None

        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            el   = soup.find('h3', {'id': 'titreOeuvre'})
            if el:
                name = el.get_text().strip()
                print(f"✅ Série : '{name}'")
                return name
            print("❌ Balise <h3 id='titreOeuvre'> introuvable")
            return None
        except Exception as e:
            print(f"❌ Erreur parsing : {e}")
            return None

    def get_chapters_from_api(self, series_name: str) -> Optional[Dict[str, int]]:
        """Interroge l'API pour obtenir le nombre de pages par chapitre."""
        _check_interrupt()
        print(f"📡 Récupération des chapitres pour '{series_name}'…")

        encoded  = urllib.parse.quote(series_name)
        api_url  = f"{self.BASE_API}?oeuvre={encoded}"
        response = tor.tor_get(api_url, max_attempts=5, timeout=20, verbose=False)

        if not response:
            print("❌ Échec requête API")
            return None

        try:
            data = response.json()
            if not isinstance(data, dict):
                print("❌ Format JSON invalide")
                return None

            chapters = {str(k): int(v) for k, v in data.items()}
            print(f"✅ {len(chapters)} chapitres trouvés")

            if chapters:
                keys = sorted(chapters, key=int)
                print(f"   Chapitres {keys[0]} à {keys[-1]}")

            return chapters
        except Exception as e:
            print(f"❌ Erreur API : {e}")
            return None

    def select_chapters(self, chapters_data: Dict[str, int]) -> List[str]:
        """Sélection interactive des chapitres à télécharger."""
        _check_interrupt()

        print(f"\n📚 SÉLECTION DES CHAPITRES")
        print("=" * 50)

        sorted_chaps = sorted(chapters_data, key=int)
        print(f"📊 {len(sorted_chaps)} chapitres disponibles")
        print(f"\n📋 Aperçu (10 premiers) :")
        for ch in sorted_chaps[:10]:
            print(f"  {ch}. Chapitre {ch} ({chapters_data[ch]} pages)")
        if len(sorted_chaps) > 10:
            print(f"  … et {len(sorted_chaps) - 10} autres")
        print(f"\n💡 Plage : {sorted_chaps[0]} à {sorted_chaps[-1]}")

        while True:
            try:
                _check_interrupt()
                choice = input("\n👉 Chapitres [N, X-Y, ou 'all'] : ").strip().lower()

                if choice == 'all':
                    return sorted_chaps

                if choice.isdigit():
                    if choice in chapters_data:
                        return [choice]
                    print(f"❌ Chapitre {choice} inexistant")
                    continue

                if '-' in choice and ',' not in choice:
                    try:
                        s, e = (int(x.strip()) for x in choice.split('-', 1))
                        sel  = [c for c in sorted_chaps if s <= int(c) <= e]
                        if sel:
                            print(f"✅ {len(sel)} chapitre(s) sélectionné(s)")
                            return sel
                        print(f"❌ Aucun chapitre dans la plage {s}-{e}")
                    except ValueError:
                        print("❌ Format invalide. Ex : '1-10'")
                    continue

                if ',' in choice:
                    sel = [p.strip() for p in choice.split(',') if p.strip() in chapters_data]
                    if sel:
                        return sel
                    print("❌ Aucun chapitre valide")
                    continue

                print("❌ Format invalide. Ex : '1', '1-10', '1,3,5', 'all'")

            except KeyboardInterrupt:
                print("\n↩️ Annulé")
                return []

    def _download_image(self, url: str, output_path: str) -> bool:
        """Télécharge une image via Tor."""
        _check_interrupt()
        min_d, max_d = self.config.get_scan_delays()
        time.sleep(random.uniform(min_d, max_d))

        response = tor.tor_get(url, max_attempts=3, timeout=30, verbose=False)
        if not response or response.status_code != 200:
            return False

        with open(output_path, 'wb') as f:
            f.write(response.content)

        return os.path.getsize(output_path) > 1024

    def download_chapter_pages(
        self, chapter_num: str, page_count: int
    ) -> Tuple[List[str], List[int]]:
        """Télécharge toutes les pages d'un chapitre."""
        _check_interrupt()

        base_url = f"{self.base_image_url}{self.encoded_series_name}/{chapter_num}/"
        console.print(f"\n[yellow]📥 Chapitre {chapter_num} ({page_count} pages)[/yellow]")

        temp_dir = os.path.join(self.download_dir, f"chapitre_{chapter_num}_temp")
        Path(temp_dir).mkdir(parents=True, exist_ok=True)

        FORMATS   = ['.jpg', '.png', '.jpeg', '.webp']
        pages:  List[str] = []
        failed: List[int] = []

        progress_ctx = Progress(
            TextColumn("[bold blue]Chapitre {task.fields[chapter]}:"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) if RICH_OK else None

        if progress_ctx:
            progress_ctx.start()
            task = progress_ctx.add_task("Téléchargement", total=page_count, chapter=chapter_num)

        for page_num in range(1, page_count + 1):
            try:
                _check_interrupt()
                downloaded = False

                for ext in FORMATS:
                    _check_interrupt()
                    img_url = f"{base_url}{page_num}{ext}"
                    out     = os.path.join(temp_dir, f"page_{page_num:03d}{ext}")

                    if self._download_image(img_url, out):
                        pages.append(out)
                        downloaded = True
                        break
                    elif os.path.exists(out):
                        os.remove(out)

                if not downloaded:
                    failed.append(page_num)

                if progress_ctx:
                    progress_ctx.update(task, advance=1)
                else:
                    print(f"  Page {page_num}/{page_count}", end='\r', flush=True)

            except KeyboardInterrupt:
                if progress_ctx:
                    progress_ctx.stop()
                raise

        if progress_ctx:
            progress_ctx.stop()

        pages.sort()
        console.print(f"\n[cyan]📊 Résultat :[/cyan]")
        console.print(f"  [green]✅ Pages : {len(pages)}/{page_count}[/green]")
        console.print(f"  [red]❌ Échecs : {len(failed)}[/red]")
        return pages, failed

    def retry_failed_pages(
        self, chapter_num: str, failed: List[int], temp_dir: str
    ) -> Tuple[List[str], List[int]]:
        """Relance le téléchargement des pages échouées."""
        if not failed:
            return [], []

        print(f"\n🔄 RETRY {len(failed)} page(s)…")
        FORMATS        = ['.jpg', '.png', '.jpeg', '.webp']
        base_url       = f"{self.base_image_url}{self.encoded_series_name}/{chapter_num}/"
        recovered:     List[str] = []
        still_failed:  List[int] = list(failed)

        for page_num in list(failed):
            try:
                _check_interrupt()
                print(f"\n  🔄 Retry page {page_num}…", end=" ")
                for ext in FORMATS:
                    out = os.path.join(temp_dir, f"page_{page_num:03d}{ext}")
                    if self._download_image(f"{base_url}{page_num}{ext}", out):
                        recovered.append(out)
                        still_failed.remove(page_num)
                        print("✅")
                        break
            except KeyboardInterrupt:
                raise

        print(f"\n📊 Retry : {len(recovered)} récupérées, {len(still_failed)} échouées")
        return recovered, still_failed

    def convert_to_pdf(self, images: List[str], chapter_num: str) -> Optional[str]:
        """Convertit une liste d'images en fichier PDF."""
        _check_interrupt()
        if not images:
            return None

        images.sort()
        lang     = self.url_info.get('language')
        pdf_name = f"Chapitre_{chapter_num}"
        if lang:
            pdf_name += f"_{lang.upper()}"
        pdf_name += ".pdf"
        pdf_path  = os.path.join(self.download_dir, pdf_name)

        try:
            print(f"📄 Conversion PDF ({len(images)} pages)…")
            with open(pdf_path, "wb") as f:
                f.write(img2pdf.convert(images))

            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1024:
                size = os.path.getsize(pdf_path)
                fmt  = f"{size // 1024} KB" if size < 1024 ** 2 else f"{size // 1024 ** 2} MB"
                print(f"✅ PDF : {pdf_name} ({fmt})")
                return pdf_path
            return None
        except Exception as e:
            print(f"❌ Erreur PDF : {e}")
            return None

    def download_chapter(self, chapter_num: str, page_count: int) -> bool:
        """Orchestre le téléchargement complet d'un chapitre."""
        try:
            _check_interrupt()
            print(f"\n{'='*60}")
            print(f"📖 CHAPITRE {chapter_num} – {page_count} pages")
            print(f"{'='*60}")

            pages, failed = self.download_chapter_pages(chapter_num, page_count)

            if failed:
                temp_dir = os.path.join(self.download_dir, f"chapitre_{chapter_num}_temp")
                recovered, still_failed = self.retry_failed_pages(chapter_num, failed, temp_dir)
                pages.extend(recovered)
                pages.sort()

                if still_failed:
                    log = os.path.join(self.download_dir, f"chapitre_{chapter_num}_echecs.txt")
                    with open(log, 'w') as f:
                        f.write('\n'.join(f"Page {p}" for p in still_failed))
                    print(f"📝 Log échecs : {log}")

            if not pages:
                print(f"\n❌ CHAPITRE {chapter_num} ÉCHOUÉ")
                return False

            pdf_path = self.convert_to_pdf(pages, chapter_num)

            # Nettoyage des fichiers temporaires
            if pages:
                import shutil
                shutil.rmtree(os.path.dirname(pages[0]), ignore_errors=True)

            ok = pdf_path is not None
            print(f"\n{'✅' if ok else '❌'} CHAPITRE {chapter_num}")
            print("=" * 60)
            return ok

        except KeyboardInterrupt:
            print(f"\n⚠️ Chapitre {chapter_num} interrompu")
            raise

    def run(self) -> None:
        """Point d'entrée principal du téléchargeur de scans."""
        try:
            print("\n📚 TÉLÉCHARGEUR DE SCANS")
            print("=" * 60)
            print(f"🔗 URL : {self.scan_url}")

            # Étape 1 : nom de série
            self.exact_series_name = self.extract_series_name()
            if not self.exact_series_name:
                print("\n❌ Impossible d'extraire le nom")
                return
            self.encoded_series_name = urllib.parse.quote(self.exact_series_name)

            # Étape 2 : chapitres via API
            chapters_data = self.get_chapters_from_api(self.exact_series_name)
            if not chapters_data:
                print("\n❌ Impossible de récupérer les chapitres")
                return

            # Étape 3 : sélection
            chapters_to_dl = self.select_chapters(chapters_data)
            if not chapters_to_dl:
                print("❌ Aucun chapitre sélectionné")
                return

            # Étape 4 : confirmation + téléchargement
            print(f"\n📊 {len(chapters_to_dl)} chapitre(s) à télécharger")
            if input("\n❓ Confirmer ? (o/n) : ").lower() != 'o':
                print("↩️ Annulé")
                return

            successful, failed_chaps = [], []

            for i, ch in enumerate(chapters_to_dl, 1):
                print(f"\n{'#'*60}")
                print(f"# PROGRESSION : {i}/{len(chapters_to_dl)}")
                print(f"{'#'*60}")
                try:
                    if self.download_chapter(ch, chapters_data[ch]):
                        successful.append(ch)
                    else:
                        failed_chaps.append(ch)
                except KeyboardInterrupt:
                    failed_chaps.append(ch)
                    break

            print(f"\n{'='*60}")
            print("📊 RÉSUMÉ FINAL")
            print(f"{'='*60}")
            print(f"✅ Réussis : {len(successful)}/{len(chapters_to_dl)}")
            print(f"❌ Échoués : {len(failed_chaps)}/{len(chapters_to_dl)}")
            if failed_chaps:
                print(f"\n📋 Chapitres échoués : {failed_chaps}")
            print(f"\n✅ Terminé !")
            print(f"📂 Dossier : {self.download_dir}")

        except KeyboardInterrupt:
            print("\n⚠️ Interrompu")
        except Exception as e:
            print(f"\n❌ Erreur : {e}")


# ============================================================================
# TÉLÉCHARGEUR DE VIDÉOS
# ============================================================================

class VideoDownloader:
    """Télécharge des épisodes vidéo via yt-dlp."""

    def __init__(self, url: str, config: ConfigManager):
        self.video_url     = url.rstrip('/')
        self.config        = config
        self.url_info      = URLParser.parse_url(url)
        self.episodes_js_url = f"{self.video_url}/episodes.js"
        self.player_priority = config.get_player_priority()

        # Construction du dossier de destination
        base_dir     = config.get_download_base_dir()
        serie_name   = self.url_info.get('serie_name') or 'unknown'
        content_type = self.url_info.get('content_type') or 'video'
        lang         = self.url_info.get('language')

        if content_type == 'anime':
            sub = f"Saison_{self.url_info.get('content_number', '1')}"
        elif content_type == 'film':
            sub = "Films"
        elif content_type in ('oav', 'ova'):
            sub = content_type.upper()
        else:
            sub = content_type.capitalize() if content_type else "Videos"

        self.download_dir = os.path.join(base_dir, serie_name, sub)
        if lang:
            self.download_dir = os.path.join(self.download_dir, lang.upper())

        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        print(f"📂 Dossier : {self.download_dir}")

    # ------------------------------------------------------------------ #

    def download_episodes_js(self) -> bool:
        """Télécharge le fichier episodes.js via Tor."""
        _check_interrupt()
        print("📥 Téléchargement episodes.js…")

        response = tor.tor_get(self.episodes_js_url, max_attempts=5, timeout=30, verbose=True)
        if not response or response.status_code != 200:
            print(f"❌ Erreur HTTP {getattr(response, 'status_code', '?')}")
            return False

        js_path = os.path.join(self.download_dir, "episodes.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(response.text)
        print("✅ episodes.js téléchargé")
        return True

    def parse_episodes_js(self) -> Optional[Dict]:
        """Parse episodes.js et retourne un dict des lecteurs disponibles."""
        _check_interrupt()

        js_path = os.path.join(self.download_dir, "episodes.js")
        if not os.path.exists(js_path):
            print("❌ episodes.js non trouvé")
            return None

        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        players: Dict = {}
        for var, links_raw in re.findall(
            r'var\s+(eps\d+)\s*=\s*\[(.*?)\];', content, re.DOTALL
        ):
            links = re.findall(r"'([^']+)'", links_raw)
            if links:
                p_type = self._identify_player(links[0])
                players[var] = {'type': p_type, 'links': links, 'count': len(links)}
                print(f"🔍 {var} : {p_type} – {len(links)} épisodes")

        return players or None

    def _identify_player(self, url: str) -> str:
        for name in ('sibnet', 'sendvid', 'vidmoly', 'oneupload', 'movearn'):
            if name in url:
                return name
        return 'unknown'

    def select_player(self, players: Dict) -> Optional[Dict]:
        """Affiche le menu de sélection du lecteur et retourne le choix."""
        if not players:
            return None

        print(f"\n📺 CHOIX DU LECTEUR")
        print("=" * 50)

        player_list = sorted(
            players.items(),
            key=lambda x: (
                self.player_priority.index(x[1]['type'])
                if x[1]['type'] in self.player_priority else 999
            ),
        )

        for i, (var, data) in enumerate(player_list, 1):
            star = " 🌟 RECOMMANDÉ" if i == 1 else ""
            print(f"  {i}. {data['type'].upper()} ({var}) – {data['count']} épisodes{star}")

        while True:
            try:
                _check_interrupt()
                choice = input("\n👉 Choix (Entrée = recommandé) : ").strip()
                if not choice:
                    _, sel = player_list[0]
                    print(f"✅ Lecteur : {sel['type'].upper()}")
                    return sel
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(player_list):
                        _, sel = player_list[idx]
                        print(f"✅ Lecteur : {sel['type'].upper()}")
                        return sel
                print(f"❌ Choix invalide (1-{len(player_list)})")
            except KeyboardInterrupt:
                _, sel = player_list[0]
                print(f"\n↩️ Utilisation du recommandé ({sel['type'].upper()})")
                return sel

    def select_episodes(self, total: int) -> List[int]:
        """Sélection interactive des épisodes à télécharger."""
        _check_interrupt()

        print(f"\n📺 SÉLECTION DES ÉPISODES")
        print("=" * 50)
        print(f"📊 {total} épisode(s) disponible(s)")

        while True:
            try:
                _check_interrupt()
                choice = input("\n👉 Épisodes [N, X-Y, ou 'all'] : ").strip().lower()

                if choice == 'all':
                    return list(range(1, total + 1))

                if choice.isdigit():
                    ep = int(choice)
                    if 1 <= ep <= total:
                        return [ep]
                    print(f"❌ Doit être entre 1 et {total}")
                    continue

                if '-' in choice and ',' not in choice:
                    try:
                        s, e = map(int, choice.split('-', 1))
                        if 1 <= s <= e <= total:
                            return list(range(s, e + 1))
                        print(f"❌ Plage invalide (1-{total})")
                    except ValueError:
                        print("❌ Format invalide. Ex : '1-10'")
                    continue

                if ',' in choice:
                    sel = sorted({
                        int(p.strip())
                        for p in choice.split(',')
                        if p.strip().isdigit() and 1 <= int(p.strip()) <= total
                    })
                    if sel:
                        return sel

                print("❌ Format invalide. Ex : '1', '1-10', '1,3,5', 'all'")

            except KeyboardInterrupt:
                print("\n↩️ Annulé")
                return []

    # ------------------------------------------------------------------ #
    # Extraction Vidmoly
    # ------------------------------------------------------------------ #

    def extract_vidmoly_m3u8(self, url: str) -> Optional[str]:
        """Extrait le lien m3u8 depuis une page Vidmoly."""
        url = url.replace('vidmoly.to', 'vidmoly.biz')
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://vidmoly.biz/',
        }
        print("  ⚡ Extraction m3u8…")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"  ❌ HTTP {response.status_code}")
                return None

            html = response.text

            if self.config.is_debug_vidmoly():
                debug_file = os.path.join(os.path.dirname(__file__), "vidmoly_debug_page.html")
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(html)
                print(f"  💾 [DEBUG] Page sauvegardée : {debug_file}")

            patterns = [
                r'file:"([^"]+\.m3u8[^"]*)"',
                r'sources:\s*\[\{file:"([^"]+)"',
                r'file\s*:\s*"([^"]+\.m3u8[^"]*)"',
                r"sources:\s*\[\s*\{\s*file:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]",
            ]
            for i, pat in enumerate(patterns, 1):
                m = re.search(pat, html)
                if m:
                    print(f"  🔗 Lien m3u8 trouvé (pattern {i})")
                    return m.group(1)

            print("  ❌ Aucun lien m3u8 trouvé")
            return None
        except Exception as e:
            print(f"  ❌ Erreur : {e}")
            return None

    # ------------------------------------------------------------------ #
    # Téléchargement avec yt-dlp
    # ------------------------------------------------------------------ #

    def download_with_ytdlp(self, url: str, filename: str, player_type: str) -> bool:
        """Télécharge une vidéo avec yt-dlp et affiche la progression."""
        _check_interrupt()

        actual_url = url
        if player_type == 'vidmoly':
            actual_url = self.extract_vidmoly_m3u8(url)
            if not actual_url:
                return False

        output = os.path.join(self.download_dir, filename)
        console.print(f"[yellow]  📥 Téléchargement : {filename}[/yellow]")
        console.print("[cyan]  ⚡ Mode : Connexion directe[/cyan]")

        try:
            import yt_dlp
        except ImportError:
            print("❌ yt-dlp non installé. Lancez : pip install yt-dlp")
            return False

        progress_obj = None
        task_id = None

        def progress_hook(d):
            nonlocal progress_obj, task_id
            if not RICH_OK:
                if d['status'] == 'downloading':
                    pct = d.get('_percent_str', '?').strip()
                    speed = d.get('_speed_str', '').strip()
                    print(f"  📥 {pct} {speed}", end='\r', flush=True)
                elif d['status'] == 'finished':
                    print()
                return

            if d['status'] == 'downloading':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                if progress_obj is None and total > 0:
                    progress_obj = Progress(
                        TextColumn("[bold blue]{task.description}"),
                        BarColumn(), DownloadColumn(),
                        TransferSpeedColumn(), TimeRemainingColumn(),
                        console=console,
                    )
                    progress_obj.start()
                    task_id = progress_obj.add_task("[cyan]  Téléchargement", total=total)
                if task_id is not None and progress_obj:
                    progress_obj.update(task_id, completed=downloaded)
            elif d['status'] == 'finished':
                if progress_obj:
                    progress_obj.stop()

        fmt = 'best' if player_type == 'vidmoly' else 'best[ext=mp4]'
        ydl_opts = {
            'outtmpl':                       output,
            'format':                        fmt,
            'merge_output_format':           'mp4',
            'concurrent_fragment_downloads': self.config.get_max_threads(),
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            'nocheckcertificate': True,
            'progress_hooks':    [progress_hook],
            'quiet':              True,
            'no_warnings':        True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([actual_url])
        except KeyboardInterrupt:
            if progress_obj:
                progress_obj.stop()
            raise
        except Exception as e:
            if progress_obj:
                progress_obj.stop()
            console.print(f"[red]  ❌ Erreur : {e}[/red]")
            return False

        if progress_obj:
            progress_obj.stop()

        if os.path.exists(output):
            size = os.path.getsize(output)
            console.print(f"[green]  ✅ Téléchargé ({size // (1024*1024)} Mo)[/green]")
            return True

        console.print("[red]  ❌ Échec[/red]")
        return False

    def download_episode(self, ep_num: int, url: str, player_type: str) -> bool:
        """Télécharge un épisode avec jusqu'à 3 tentatives."""
        filename = f"Episode_{ep_num}.mp4"
        min_size = self.config.get_min_file_size()

        for attempt in range(1, 4):
            try:
                _check_interrupt()
                print(f"  🔄 Tentative {attempt}/3")
                if self.download_with_ytdlp(url, filename, player_type):
                    fpath = os.path.join(self.download_dir, filename)
                    if os.path.exists(fpath) and os.path.getsize(fpath) >= min_size:
                        return True
                    print("  ❌ Fichier corrompu ou trop petit")
                    if os.path.exists(fpath):
                        os.remove(fpath)
                time.sleep(2)
            except KeyboardInterrupt:
                raise

        return False

    def run(self) -> None:
        """Point d'entrée principal du téléchargeur de vidéos."""
        try:
            print("\n🎬 TÉLÉCHARGEUR DE VIDÉOS")
            print("=" * 60)
            print(f"🔗 URL : {self.video_url}")
            print("⚠️ Note : Tor non utilisé pour les vidéos")

            # Étape 1 : episodes.js
            if not self.download_episodes_js():
                print("\n❌ Impossible de télécharger episodes.js")
                return

            # Étape 2 : parse
            players = self.parse_episodes_js()
            if not players:
                print("\n❌ Aucun lecteur trouvé")
                return

            # Étape 3 : sélection lecteur
            selected = self.select_player(players)
            if not selected:
                print("❌ Aucun lecteur sélectionné")
                return

            total_eps    = selected['count']
            player_type  = selected['type']
            player_links = selected['links']

            print(f"\n✅ Configuration :")
            print(f"   • Lecteur : {player_type.upper()}")
            print(f"   • Épisodes : {total_eps}")

            # Étape 4 : sélection épisodes
            episodes_to_dl = self.select_episodes(total_eps)
            if not episodes_to_dl:
                print("❌ Aucun épisode sélectionné")
                return

            # Étape 5 : confirmation + téléchargement
            print(f"\n📊 {len(episodes_to_dl)} épisode(s)")
            if input("\n❓ Confirmer ? (o/n) : ").lower() != 'o':
                print("↩️ Annulé")
                return

            successful, failed_eps = [], []

            for i, ep_num in enumerate(episodes_to_dl, 1):
                print(f"\n{'#'*60}")
                print(f"# PROGRESSION : {i}/{len(episodes_to_dl)} – Épisode {ep_num}")
                print(f"{'#'*60}")

                ep_idx = ep_num - 1
                if ep_idx >= len(player_links):
                    print(f"❌ Épisode {ep_num} inexistant")
                    failed_eps.append(ep_num)
                    continue

                try:
                    if self.download_episode(ep_num, player_links[ep_idx], player_type):
                        successful.append(ep_num)
                    else:
                        failed_eps.append(ep_num)
                except KeyboardInterrupt:
                    failed_eps.append(ep_num)
                    break

            print(f"\n{'='*60}")
            print("📊 RÉSUMÉ FINAL")
            print(f"{'='*60}")
            print(f"✅ Réussis : {len(successful)}/{len(episodes_to_dl)}")
            print(f"❌ Échoués : {len(failed_eps)}/{len(episodes_to_dl)}")

            if failed_eps:
                print(f"\n📋 Épisodes échoués : {failed_eps}")
                log = os.path.join(self.download_dir, "episodes_echoues.txt")
                with open(log, 'w') as f:
                    f.write(f"# Série : {self.url_info['serie_name']}\n")
                    f.write(f"# Lecteur : {player_type}\n\n")
                    f.write('\n'.join(f"Episode_{e}" for e in failed_eps))
                print(f"📝 Log : {log}")

            print(f"\n✅ Terminé !")
            print(f"📂 Dossier : {self.download_dir}")

        except KeyboardInterrupt:
            print("\n⚠️ Interrompu")
        except Exception as e:
            print(f"\n❌ Erreur : {e}")


# ============================================================================
# API PUBLIQUE
# ============================================================================

def classify_url(url: str) -> Dict:
    """Classifie une URL et retourne ses métadonnées."""
    return {
        'type':        URLParser.detect_content_type(url),
        'parsed_info': URLParser.parse_url(url),
    }


def process_download(url: str, config: Optional[ConfigManager] = None) -> bool:
    """
    Point d'entrée principal pour lancer un téléchargement.

    Args:
        url:    URL complète (scan ou vidéo)
        config: Instance ConfigManager (créée si absent)

    Returns:
        True si le téléchargement s'est terminé sans erreur fatale.
    """
    if not url or not url.startswith('http'):
        print("❌ URL invalide")
        return False

    if not DEPENDENCIES_OK:
        print("❌ Dépendances manquantes")
        return False

    if config is None:
        config = ConfigManager()

    info = classify_url(url)

    print(f"\n{'='*60}")
    print("🔍 ANALYSE DE L'URL")
    print(f"{'='*60}")
    print(f"   • Type   : {info['type'].upper()}")
    print(f"   • Série  : {info['parsed_info']['serie_name']}")
    print(f"   • Langue : {info['parsed_info']['language']}")
    print(f"{'='*60}")

    if info['type'] == 'scan':
        print("\n🚀 Mode : SCANS (Tor requis)")
        dl = ScanDownloader(url, config)
    else:
        print("\n🚀 Mode : VIDÉOS (connexion directe)")
        try:
            subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
        except Exception:
            print("❌ yt-dlp non installé. Lancez : pip install yt-dlp")
            return False
        dl = VideoDownloader(url, config)

    try:
        dl.run()
        return True
    except KeyboardInterrupt:
        print("\n⚠️ Interrompu")
        return False
    except Exception as e:
        print(f"❌ Erreur : {e}")
        return False
