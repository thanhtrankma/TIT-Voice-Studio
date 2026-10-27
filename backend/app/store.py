"""Lưu lịch sử, bài luyện Shadowing, lượt đăng YouTube (SQLite) và từ điển phát âm (JSON) trên máy."""
import json
import sqlite3
import threading
import time
from typing import Dict, List, Optional

from .config import DATA_DIR, DB_FILE

DICT_FILE = DATA_DIR / "pronunciation-dict.json"

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id TEXT PRIMARY KEY,
                created REAL NOT NULL,
                text TEXT NOT NULL,
                voice TEXT NOT NULL,
                speed REAL NOT NULL,
                duration REAL NOT NULL,
                chars INTEGER NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS shadow (
                id TEXT PRIMARY KEY,
                created REAL NOT NULL,
                title TEXT NOT NULL,
                voice TEXT NOT NULL,
                lines INTEGER NOT NULL,
                duration REAL NOT NULL,
                aspect TEXT NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS youtube (
                video_id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL,
                uploaded REAL NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                privacy TEXT NOT NULL,
                publish_at TEXT,
                account TEXT NOT NULL
            )"""
        )


def add_history(item_id: str, text: str, voice: str, speed: float, duration: float, chars: int) -> dict:
    row = dict(id=item_id, created=time.time(), text=text, voice=voice,
               speed=speed, duration=duration, chars=chars)
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO history VALUES (:id, :created, :text, :voice, :speed, :duration, :chars)", row
        )
    return row


def list_history(limit: int = 200) -> List[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM history ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_history(item_id: str) -> Optional[dict]:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM history WHERE id = ?", (item_id,)).fetchone()
    return dict(r) if r else None


def delete_history(item_id: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM history WHERE id = ?", (item_id,))


def add_shadow(item_id: str, title: str, voice: str, lines: int, duration: float, aspect: str) -> dict:
    row = dict(id=item_id, created=time.time(), title=title, voice=voice,
               lines=lines, duration=duration, aspect=aspect)
    with _lock, _conn() as c:
        c.execute("INSERT INTO shadow VALUES (:id, :created, :title, :voice, :lines, :duration, :aspect)", row)
    return row


_LATEST_UPLOAD = "(SELECT url FROM youtube y WHERE y.lesson_id = s.id ORDER BY uploaded DESC LIMIT 1) AS youtube_url"


def list_shadow(limit: int = 100) -> List[dict]:
    with _lock, _conn() as c:
        rows = c.execute(f"SELECT s.*, {_LATEST_UPLOAD} FROM shadow s ORDER BY created DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_shadow(item_id: str) -> Optional[dict]:
    with _lock, _conn() as c:
        r = c.execute(f"SELECT s.*, {_LATEST_UPLOAD} FROM shadow s WHERE id = ?", (item_id,)).fetchone()
    return dict(r) if r else None


def delete_shadow(item_id: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM shadow WHERE id = ?", (item_id,))


def add_youtube(lesson_id: str, video_id: str, url: str, title: str, privacy: str,
                publish_at: Optional[str], account: str) -> dict:
    row = dict(video_id=video_id, lesson_id=lesson_id, uploaded=time.time(), url=url, title=title,
               privacy=privacy, publish_at=publish_at, account=account)
    with _lock, _conn() as c:
        c.execute("INSERT INTO youtube VALUES (:video_id, :lesson_id, :uploaded, :url, :title, :privacy, "
                  ":publish_at, :account)", row)
    return row


def list_youtube(lesson_id: str) -> List[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM youtube WHERE lesson_id = ? ORDER BY uploaded DESC", (lesson_id,)).fetchall()
    return [dict(r) for r in rows]


def load_dictionary() -> Dict[str, str]:
    if not DICT_FILE.exists():
        return {}
    try:
        return json.loads(DICT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_dictionary(entries: Dict[str, str]) -> Dict[str, str]:
    clean = {k.strip(): v.strip() for k, v in entries.items() if k.strip() and v.strip()}
    DICT_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean
