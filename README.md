# AnimeR

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**AnimeR** est un téléchargeur automatisé d'anime et de scans depuis anime-sama, avec routage Tor intégré pour les scans et téléchargement direct pour les vidéos.

## ✨ Fonctionnalités

- 🔍 **Recherche dans le catalogue** : recherche interactive par nom et type (anime/film/scan)
- 🎬 **Téléchargement de vidéos** : télécharge des épisodes via yt-dlp (multi-lecteurs : Sibnet, Sendvid, Vidmoly, etc.)
- 📚 **Téléchargement de scans** : télécharge les chapitres et les convertit en PDF
- 📋 **Mode batch** : télécharge plusieurs séries depuis un fichier texte
- 🎯 **Sélection fine** : choix des saisons, langues et épisodes/chapitres spécifiques
- ⚙️ **Configuration JSON** : paramètres personnalisables (répertoires, threads, délais, etc.)

---

## 📦 Installation

### Prérequis

- **Python 3.7+**
- **pip** (gestionnaire de paquets Python)
- **yt-dlp** (installé automatiquement)

### Installation rapide

```bash
# Cloner le dépôt
git clone https://github.com/votre-username/AnimeR.git
cd AnimeR

# (Optionnel) Créer un environnement virtuel
python3 -m venv .venv
source .venv/bin/activate  # Linux( ou éventuellement macOS)
# .venv\Scripts\activate   # Windows

# Installer les dépendances
pip install -r requirements.txt
```

Le fichier `requirements.txt` contient :
```
requests
beautifulsoup4
img2pdf
PySocks
yt-dlp
rich
```

---

## 🚀 Utilisation

### Lancement

```bash
python main.py
```

### Paramètres clés du fichier config.json

| Paramètre | Description | Valeur par défaut |
|-----------|-------------|-------------------|
| `download_base` | Répertoire de destination | `./AnimeRT` |
| `min_delay_seconds` | Délai min entre pages (scans) | `1` |
| `max_delay_seconds` | Délai max entre pages (scans) | `3` |
| `player_priority` | Ordre de priorité des lecteurs | `["sibnet", "sendvid", ...]` |

**Modification :** Menu principal → `4. Configuration` ou édition manuelle du fichier.

---

## 🔒 Tor

### Binaire embarqué

AnimeR télécharge automatiquement le **Tor Expert Bundle officiel** depuis [torproject.org](https://www.torproject.org/) au premier lancement. Aucune installation système requise.

**Plateformes supportées :**
- Linux (x86_64, aarch64)
- Windows (x64)

---

## 📋 Format du fichier batch

```
# Commentaires commencent par #

# Format : [URL] / [Episodes]

# Télécharger les épisodes 1 à 3
[https://anime-sama.tv/catalogue/serie/saison1/vf/] / [1-3]

# Télécharger tous les chapitres
[https://anime-sama.tv/catalogue/serie/scan/vf/] / [all]

# Télécharger des épisodes spécifiques
[https://anime-sama.tv/catalogue/serie/saison2/vostfr/] / [10-15]

```

**Formats d'épisodes acceptés :**
- `all` : tous les épisodes/chapitres
- `5` : épisode 5 uniquement
- `1-5` : épisodes 1 à 5



## ❓ FAQ

### Le téléchargement de Tor échoue

**Solution :** Téléchargez manuellement le Tor Expert Bundle depuis [torproject.org](https://www.torproject.org/download/tor/) et extrayez le binaire dans `./tor_bin/tor` (ou `tor.exe` sur Windows).

### Les vidéos ne se téléchargent pas

**Solution :** Vérifiez que `yt-dlp` est installé :

```bash
pip install --upgrade yt-dlp
yt-dlp --version
```

### Les scans échouent avec "Tor inactif"

**Solution :** Vérifiez que Tor démarre correctement :

```bash
# Menu principal → 5. Vérifier les prérequis
# Puis redémarrez le programme
```

### Erreur "CloudFlare blocked"

**Solution :** C'est normal — le programme utilise Tor pour contourner la protection. Si l'erreur persiste, changez d'identité Tor (automatique après 3 échecs).

### Comment changer le répertoire de téléchargement ?

**Solution :** Menu principal → `4. Configuration` → `1. Changer le répertoire`

Ou éditez `config.json` :

```json
{
  "directories": {
    "download_base": "/chemin/vers/dossier"
  }
}
```

---

## 🤝 Contribution

Les contributions sont les bienvenues ! Merci de :

1. Fork le projet
2. Créer une branche pour votre fonctionnalité (`git checkout -b feature/AmazingFeature`)
3. Commit vos changements (`git commit -m 'Add AmazingFeature'`)
4. Push vers la branche (`git push origin feature/AmazingFeature`)
5. Ouvrir une Pull Request

**Guidelines :**
- Respecter l'architecture existante (pas de cycles d'import)
- Documenter les fonctions publiques
- Tester sur Linux/macOS/Windows si possible


## ⚠️ Avertissement

**Usage éducatif uniquement.** Télécharger du contenu protégé par le droit d'auteur sans autorisation est illégal dans de nombreux pays. Utilisez ce logiciel uniquement pour du contenu dont vous possédez les droits ou qui est dans le domaine public.

Les auteurs de ce projet ne sont pas responsables de l'utilisation que vous faites de ce logiciel.

---

## 🙏 Remerciements

- [Tor Project](https://www.torproject.org/) pour le binaire Tor Expert Bundle
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) pour le téléchargement de vidéos
- [Anime Sama API](https://github.com/Sky-NiniKo/anime-sama_api) pour l'inspiration
- [anime-sama.tv](https://anime-sama.tv/) pour le catalogue

---

