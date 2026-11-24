# Twitch Clips Grabber 🎮

Un outil en ligne de commande simple et efficace pour collecter et télécharger les clips Twitch d'un ou plusieurs streamers, avec des filtres avancés (date, vues, durée).

L'outil utilise l'API Twitch Helix pour la recherche de clips et `yt-dlp` pour le téléchargement des vidéos. Une base de données SQLite locale permet de garder une trace des clips déjà traités.

## 🚀 Fonctionnalités

- **Commande unique `grab`** : Automatise tout le processus (résolution du streamer, recherche des clips, filtrage et téléchargement).
- **Filtres personnalisables** :
  - `--since` : Date de début (format YYYY-MM-DD).
  - `--views` : Nombre minimum de vues (défaut : 30).
  - `--max-duration` : Durée maximale en secondes (défaut : 60).
- **Gestion intelligente** : Auto-ajout des streamers inconnus et stockage des métadonnées en base SQLite.
- **Organisation** : Téléchargement des vidéos dans des dossiers séparés par streamer.

## 🛠 Installation

1. **Cloner le dépôt** :
   ```bash
   git clone https://github.com/votre-username/TwitchScrapping.git
   cd TwitchScrapping
   ```

2. **Créer un environnement virtuel et installer les dépendances** :
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Sur Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configurer les identifiants Twitch** :
   Créez un fichier `.env` à la racine du projet (utilisez `.env.example` comme modèle) :
   ```env
   TWITCH_CLIENT_ID=votre_client_id
   TWITCH_CLIENT_SECRET=votre_client_secret
   # Optionnel :
   DB_PATH=twitch_clips.db
   CLIPS_DIR=clips
   ```
   *Note : Vous pouvez obtenir ces identifiants sur la [Twitch Developer Console](https://dev.twitch.tv/console).*

## 📖 Utilisation

La commande principale est `grab`. Elle accepte un ou plusieurs logins de streamers.

### Exemples

Télécharger les clips de **Squeezie** depuis le 1er novembre 2026 avec au moins 50 vues :
```bash
python twitch_clips.py grab squeezie --since 2026-11-01 --views 50
```

Télécharger les clips de **Kameto** et **Gotaga** (max 45 secondes) :
```bash
python twitch_clips.py grab kamet0 gotaga --since 2026-11-20 --max-duration 45
```

### Arguments disponibles
- `logins` : Un ou plusieurs noms d'utilisateurs Twitch.
- `--since` (Requis) : Date de début de recherche (YYYY-MM-DD).
- `--views` : Seuil de vues minimum (Défaut : 30).
- `--max-duration` : Durée max du clip en secondes (Défaut : 60.0).
- `--max-pages` : Nombre de pages de 100 clips à parcourir par streamer (Défaut : 2).

## 🗃 Architecture

- **`twitch_clips.py`** : Script principal contenant toute la logique.
- **`twitch_clips.db`** : Base de données SQLite stockant les streamers et les métadonnées des clips.
- **`clips/`** : Dossier de destination des vidéos téléchargées (organisé par login).

## 📝 Licence

Ce projet est destiné à un usage personnel. Assurez-vous de respecter les conditions d'utilisation de Twitch et les droits des créateurs de contenu lors de l'utilisation de cet outil.
