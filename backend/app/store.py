"""Lưu lịch sử (SQLite) và từ điển phát âm (JSON) trên máy."""
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
