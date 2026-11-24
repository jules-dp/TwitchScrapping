#!/usr/bin/env python3
"""
twitch_clips.py — téléchargement de clips Twitch via la commande grab

Commande :
    grab <login...>   télécharge les clips d'un streamer filtrés par date, vues et durée
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

load_dotenv()

CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
DB_PATH = os.getenv("DB_PATH", "twitch_clips.db")
CLIPS_DIR = Path(os.getenv("CLIPS_DIR", "clips"))

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_URL = "https://api.twitch.tv/helix"

SCHEMA = """
CREATE TABLE IF NOT EXISTS streamers (
    id                TEXT PRIMARY KEY,           -- id utilisateur Twitch
    login             TEXT UNIQUE NOT NULL,
    display_name      TEXT,
    language          TEXT DEFAULT 'fr',
    added_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
    id           TEXT PRIMARY KEY,                -- slug du clip
    streamer_id  TEXT NOT NULL REFERENCES streamers(id),
    title        TEXT,
    url          TEXT NOT NULL,
    view_count   INTEGER DEFAULT 0,
    duration     REAL,
    creator_name TEXT,
    game_id      TEXT,
    language     TEXT,
    created_at   TEXT,                            -- date de création du clip
    collected_at TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'downloaded', -- new | downloaded | failed
    file_path    TEXT,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_clips_streamer ON clips(streamer_id);
"""


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> str:
    return iso(datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# Client API Twitch
# --------------------------------------------------------------------------
class Twitch:
    def __init__(self):
        if not CLIENT_ID or not CLIENT_SECRET:
            sys.exit("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET manquants (voir .env.example)")
        self.session = requests.Session()
        self.token = None

    def _refresh_token(self):
        r = requests.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        if not self.token:
            self._refresh_token()
        for _ in range(5):
            r = self.session.get(
                f"{API_URL}/{endpoint}",
                params=params,
                headers={"Client-Id": CLIENT_ID, "Authorization": f"Bearer {self.token}"},
                timeout=20,
            )
            if r.status_code == 401:  # token expiré
                self._refresh_token()
                continue
            if r.status_code == 429:  # rate limit
                reset = float(r.headers.get("Ratelimit-Reset", time.time() + 5))
                time.sleep(max(1.0, reset - time.time()) + 1)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Échec de l'appel Helix : {endpoint}")

    def paginate(self, endpoint: str, params: dict, max_pages: int = 5):
        params = dict(params)
        for _ in range(max_pages):
            data = self.get(endpoint, params)
            yield from data.get("data", [])
            cursor = data.get("pagination", {}).get("cursor")
            if not cursor:
                break
            params["after"] = cursor


# --------------------------------------------------------------------------
# Commande
# --------------------------------------------------------------------------
def cmd_grab(args, db, tw):
    """Télécharge les clips d'un/des streamer(s) filtrés par date, vues et durée."""
    # Parse --since (YYYY-MM-DD) to ISO started_at
    try:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        sys.exit(f"Format de date invalide pour --since: {args.since}. Attendu YYYY-MM-DD.")
    since = iso(since_dt)

    total_ok = 0
    total_rows = 0

    for login_arg in args.logins:
        login = login_arg.lower().lstrip("@")

        # Résoudre le streamer_id
        row = db.execute("SELECT id, login FROM streamers WHERE login = ?", (login,)).fetchone()
        if row:
            streamer_id, streamer_login = row
        else:
            # Tenter de le créer via l'API users
            users = tw.get("users", {"login": login})["data"]
            if not users:
                print(f"! introuvable : {login}")
                continue
            u = users[0]
            streamer_id, streamer_login = u["id"], u["login"]
            db.execute(
                """INSERT INTO streamers (id, login, display_name, added_at)
                   VALUES (?, ?, ?, ?)""",
                (streamer_id, streamer_login, u["display_name"], utcnow()),
            )
            db.commit()
            print(f"+ {streamer_login} (auto-ajouté)")

        print(f"\n=== {streamer_login} ===")

        # Fetch clips via paginate
        clips = list(tw.paginate(
            "clips",
            {"broadcaster_id": streamer_id, "started_at": since, "first": 100},
            max_pages=args.max_pages,
        ))

        # Filtrer côté client (view_count et duration)
        filtered = [
            c for c in clips
            if c["view_count"] >= args.views and c["duration"] <= args.max_duration
        ]

        if not filtered:
            print("  Aucun clip ne correspond aux critères.")
            continue

        # Trier par vues décroissantes
        filtered.sort(key=lambda c: c["view_count"], reverse=True)

        for c in filtered:
            total_rows += 1
            clip_id = c["id"]
            # Upsert en base (pour éviter les doublons et stocker les métadonnées)
            db.execute(
                """INSERT INTO clips
                       (id, streamer_id, title, url, view_count, duration,
                        creator_name, game_id, language, created_at, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       view_count = excluded.view_count,
                       title = excluded.title""",
                (
                    clip_id, streamer_id, c["title"], c["url"], c["view_count"], c["duration"],
                    c["creator_name"], c["game_id"], c["language"], c["created_at"], utcnow(),
                ),
            )
            db.commit()

            ok, info = _download_clip(db, clip_id, c["url"], streamer_login)
            if ok:
                total_ok += 1
                print(f"  OK    {clip_id} ({c['view_count']} vues, {c['duration']:.1f}s)")
            else:
                print(f"  ECHEC {clip_id} : {info}")
            time.sleep(1)

    print(f"\nTotal : {total_ok}/{total_rows} clip(s) téléchargé(s) dans {CLIPS_DIR}/")


def _download_clip(db, clip_id, url, login):
    """Télécharge un clip unique et met à jour la base. Retourne (success, path_or_error)."""
    out_dir = CLIPS_DIR / login
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(out_dir / f"{clip_id}.%(ext)s"),
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
        db.execute(
            "UPDATE clips SET status='downloaded', file_path=?, error=NULL WHERE id=?",
            (path, clip_id),
        )
        db.commit()
        return True, path
    except Exception as e:  # noqa: BLE001
        db.execute(
            "UPDATE clips SET status='failed', error=? WHERE id=?",
            (str(e)[:500], clip_id),
        )
        db.commit()
        return False, str(e)


# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(description="Téléchargement de clips Twitch")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grab", help="télécharger les clips d'un streamer")
    g.add_argument("logins", nargs="+", help="login(s) du/de des streamer(s)")
    g.add_argument("--since", required=True, help="date de début (YYYY-MM-DD)")
    g.add_argument("--views", type=int, default=30, help="nombre minimum de vues (défaut 30)")
    g.add_argument("--max-duration", type=float, default=60.0, help="durée max en secondes (défaut 60)")
    g.add_argument("--max-pages", type=int, default=2, help="pages de 100 clips par streamer (défaut 2)")

    return p


def main():
    args = build_parser().parse_args()
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)

    cmd_grab(args, db, Twitch())


if __name__ == "__main__":
    main()
