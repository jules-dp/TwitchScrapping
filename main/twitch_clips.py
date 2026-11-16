#!/usr/bin/env python3
"""
twitch_clips.py — collecte et téléchargement de clips Twitch
(API Helix + SQLite + yt-dlp)

Commandes :
    add <login...>   ajoute des streamers à la base par leur login Twitch
    discover         ajoute automatiquement les streamers FR actuellement en live
    collect          récupère les clips récents de tous les streamers de la base
    download         télécharge les meilleurs clips pas encore téléchargés
    stats            résumé de la base
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
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
    peak_viewers      INTEGER DEFAULT 0,          -- max de viewers vu via discover
    added_at          TEXT NOT NULL,
    last_collected_at TEXT
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
    status       TEXT NOT NULL DEFAULT 'new',     -- new | downloaded | failed
    file_path    TEXT,
    error        TEXT,
    posted       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_clips_status   ON clips(status, view_count DESC);
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
# Commandes
# --------------------------------------------------------------------------
def cmd_add(args, db, tw):
    logins = [l.lower().lstrip("@") for l in args.logins]
    for i in range(0, len(logins), 100):  # l'API accepte 100 logins max
        batch = logins[i : i + 100]
        users = tw.get("users", {"login": batch})["data"]
        found = set()
        for u in users:
            db.execute(
                """INSERT INTO streamers (id, login, display_name, added_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       login = excluded.login,
                       display_name = excluded.display_name""",
                (u["id"], u["login"], u["display_name"], utcnow()),
            )
            found.add(u["login"])
            print(f"+ {u['display_name']}")
        for missing in sorted(set(batch) - found):
            print(f"! introuvable : {missing}")
    db.commit()


def cmd_discover(args, db, tw):
    """Ajoute les streamers francophones actuellement en live (triés par viewers)."""
    added = 0
    for s in tw.paginate(
        "streams",
        {"language": "fr", "type": "live", "first": 100},
        max_pages=args.pages,
    ):
        if s["viewer_count"] < args.min_viewers:
            break  # la liste est triée par viewers décroissants
        exists = db.execute("SELECT 1 FROM streamers WHERE id = ?", (s["user_id"],)).fetchone()
        db.execute(
            """INSERT INTO streamers (id, login, display_name, peak_viewers, added_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   login = excluded.login,
                   display_name = excluded.display_name,
                   peak_viewers = MAX(peak_viewers, excluded.peak_viewers)""",
            (s["user_id"], s["user_login"], s["user_name"], s["viewer_count"], utcnow()),
        )
        if not exists:
            added += 1
            print(f"+ {s['user_name']} ({s['viewer_count']} viewers)")
    db.commit()
    print(f"{added} nouveau(x) streamer(s) ajouté(s).")


def cmd_collect(args, db, tw):
    since = iso(datetime.now(timezone.utc) - timedelta(hours=args.hours))
    streamers = db.execute(
        "SELECT id, login FROM streamers ORDER BY peak_viewers DESC, login"
    ).fetchall()
    if not streamers:
        sys.exit("Aucun streamer en base. Utilise 'add' ou 'discover' d'abord.")

    total_new = 0
    for sid, login in streamers:
        new = 0
        for c in tw.paginate(
            "clips",
            {"broadcaster_id": sid, "started_at": since, "first": 100},
            max_pages=args.max_pages,
        ):
            exists = db.execute("SELECT 1 FROM clips WHERE id = ?", (c["id"],)).fetchone()
            db.execute(
                """INSERT INTO clips
                       (id, streamer_id, title, url, view_count, duration,
                        creator_name, game_id, language, created_at, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       view_count = excluded.view_count,
                       title = excluded.title""",
                (
                    c["id"], sid, c["title"], c["url"], c["view_count"], c["duration"],
                    c["creator_name"], c["game_id"], c["language"], c["created_at"], utcnow(),
                ),
            )
            if not exists:
                new += 1
        db.execute("UPDATE streamers SET last_collected_at = ? WHERE id = ?", (utcnow(), sid))
        db.commit()
        total_new += new
        print(f"{login:<25} +{new} clip(s)")
    print(f"Total : {total_new} nouveau(x) clip(s).")


def cmd_download(args, db):
    since = iso(datetime.now(timezone.utc) - timedelta(hours=args.since_hours))
    statuses = ("new", "failed") if args.retry_failed else ("new",)
    placeholders = ",".join("?" * len(statuses))
    rows = db.execute(
        f"""SELECT c.id, c.url, s.login
            FROM clips c JOIN streamers s ON s.id = c.streamer_id
            WHERE c.status IN ({placeholders})
              AND c.view_count >= ?
              AND c.duration <= ?
              AND c.created_at >= ?
            ORDER BY c.view_count DESC
            LIMIT ?""",
        (*statuses, args.min_views, args.max_duration, since, args.limit),
    ).fetchall()

    if not rows:
        print("Rien à télécharger avec ces filtres.")
        return

    ok = 0
    for clip_id, url, login in rows:
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
            ok += 1
            print(f"OK    {login}/{clip_id}")
        except Exception as e:  # noqa: BLE001
            db.execute(
                "UPDATE clips SET status='failed', error=? WHERE id=?",
                (str(e)[:500], clip_id),
            )
            print(f"ECHEC {login}/{clip_id} : {e}")
        db.commit()
        time.sleep(1)  # on reste poli avec Twitch
    print(f"{ok}/{len(rows)} clip(s) téléchargé(s) dans {CLIPS_DIR}/")


def cmd_stats(db):
    n = db.execute("SELECT COUNT(*) FROM streamers").fetchone()[0]
    print(f"Streamers : {n}")
    for status, count in db.execute("SELECT status, COUNT(*) FROM clips GROUP BY status"):
        print(f"  clips {status:<11}: {count}")
    print("Top streamers par nombre de clips :")
    for login, count, best in db.execute(
        """SELECT s.login, COUNT(*), MAX(c.view_count)
           FROM clips c JOIN streamers s ON s.id = c.streamer_id
           GROUP BY s.id ORDER BY COUNT(*) DESC LIMIT 10"""
    ):
        print(f"  {login:<25} {count:>4} clips (meilleur : {best} vues)")


# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(description="Collecte de clips Twitch FR")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="ajouter des streamers par login")
    a.add_argument("logins", nargs="+")

    d = sub.add_parser("discover", help="ajouter les streamers FR en live")
    d.add_argument("--pages", type=int, default=3, help="pages de 100 streams (défaut 3)")
    d.add_argument("--min-viewers", type=int, default=200, help="seuil de viewers (défaut 200)")

    c = sub.add_parser("collect", help="récupérer les clips récents")
    c.add_argument("--hours", type=int, default=48, help="fenêtre de temps (défaut 48h)")
    c.add_argument("--max-pages", type=int, default=2, help="pages de 100 clips par streamer")

    dl = sub.add_parser("download", help="télécharger les meilleurs clips")
    dl.add_argument("--min-views", type=int, default=20)
    dl.add_argument("--max-duration", type=float, default=60.0)
    dl.add_argument("--limit", type=int, default=20)
    dl.add_argument("--since-hours", type=int, default=72, help="clips créés depuis N heures")
    dl.add_argument("--retry-failed", action="store_true")

    sub.add_parser("stats", help="résumé de la base")
    return p


def main():
    args = build_parser().parse_args()
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)

    if args.cmd == "add":
        cmd_add(args, db, Twitch())
    elif args.cmd == "discover":
        cmd_discover(args, db, Twitch())
    elif args.cmd == "collect":
        cmd_collect(args, db, Twitch())
    elif args.cmd == "download":
        cmd_download(args, db)
    elif args.cmd == "stats":
        cmd_stats(db)


if __name__ == "__main__":
    main()
