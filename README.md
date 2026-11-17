# Twitch Clips Scraper

Outil Python qui collecte les clips de streamers francophones sur Twitch, les stocke dans une base SQLite et les télécharge automatiquement. L'objectif à terme est de les recadrer au format vertical (9:16) et de les publier sur TikTok.

## Fonctionnalités

- [x] Authentification à l'API Twitch Helix (OAuth, client credentials)
- [x] Collecte des clips d'une liste de streamers francophones
- [x] Stockage des streamers et des clips dans une base SQLite
- [x] Téléchargement automatique des clips avec `yt-dlp`

## Stack technique

- **Python 3.10+**
- **API Twitch Helix** pour récupérer les streamers et les clips
- **SQLite** pour la base de données
- **yt-dlp** pour le téléchargement des vidéos
- **FFmpeg** pour le traitement vidéo (étape de recadrage)

## Installation

```bash
git clone https://github.com/jules-dp/TwitchScrapping
cd TwitchScrapping

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Il faut aussi installer FFmpeg

## Configuration

1. Crée une application sur la [console développeur Twitch](https://dev.twitch.tv/console) pour obtenir un `Client ID` et un `Client Secret`.
2. Copie le fichier d'exemple et renseigne tes identifiants :

```bash
cp .env.example .env
```

```env
TWITCH_CLIENT_ID=ton_client_id
TWITCH_CLIENT_SECRET=ton_client_secret

## Utilisation

```bash
# 1. Récupérer les clips des streamers et remplir la base
python collect.py

# 2. Télécharger les clips en attente
python download.py
```

Les vidéos sont enregistrées dans le dossier `clips/` et la base se trouve dans `twitch_clips.db`.

## Structure de la base de données

| Table       | Contenu principal                                                         |
|-------------|---------------------------------------------------------------------------|
| `streamers` | identifiant Twitch, pseudo, nom affiché                                   |
| `clips`     | identifiant du clip, streamer, titre, URL, vues, durée, date, statut de téléchargement |

## Avertissement

Les clips appartiennent à leurs créateurs et aux streamers concernés. Avant toute republication, vérifie les conditions d'utilisation de Twitch et de TikTok, et obtiens l'accord des streamers. Ce projet est à but éducatif et personnel.
