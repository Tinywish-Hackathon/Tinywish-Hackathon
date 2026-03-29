"""Lightweight SQLite application tracking."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime

_DB_PATH = "applications.db"


def init_tracker(db_path="applications.db"):
    """Initialize the application tracker database."""
    global _DB_PATH

    _DB_PATH = db_path or _DB_PATH

    try:
        with sqlite3.connect(_DB_PATH, timeout=1) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheme_name TEXT NOT NULL,
                    portal TEXT,
                    source_type TEXT,
                    status TEXT,
                    reference TEXT,
                    applied_at TEXT,
                    profile_name TEXT
                )
                """
            )
            conn.commit()
    except Exception:
        pass


def log_application(
    scheme_name,
    portal,
    source_type,
    status,
    reference="",
    profile_name="",
):
    """Log a single application lifecycle event."""
    try:
        init_tracker(_DB_PATH)
        with sqlite3.connect(_DB_PATH, timeout=1) as conn:
            conn.execute(
                """
                INSERT INTO applications (
                    scheme_name,
                    portal,
                    source_type,
                    status,
                    reference,
                    applied_at,
                    profile_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(scheme_name or "").strip(),
                    str(portal or "").strip(),
                    str(source_type or "").strip(),
                    str(status or "").strip(),
                    str(reference or "").strip(),
                    datetime.now().replace(microsecond=0).isoformat(),
                    str(profile_name or "").strip(),
                ),
            )
            conn.commit()
    except Exception:
        pass


def get_recent_applications(limit=10) -> list[dict]:
    """Return recent applications as plain dictionaries."""
    try:
        init_tracker(_DB_PATH)
        with sqlite3.connect(_DB_PATH, timeout=1) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    id,
                    scheme_name,
                    portal,
                    source_type,
                    status,
                    reference,
                    applied_at,
                    profile_name
                FROM applications
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def print_application_history():
    """Print a formatted table of recent application records."""
    rows = get_recent_applications()

    body_lines = ["Application History"]
    divider_index = 1

    if rows:
        for index, row in enumerate(rows, 1):
            applied_at = str(row.get("applied_at", "") or "").replace("T", " ").split(".")[0]
            portal = row.get("portal") or "-"
            status = row.get("status") or "-"

            body_lines.append(f"{index}. {row.get('scheme_name', '')}")
            body_lines.append(f"   Portal: {portal} | Status: {status}")
            body_lines.append(f"   Applied: {applied_at}")
    else:
        body_lines.append("No application records yet.")

    content_width = max(len(line) for line in body_lines)

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "┌┐└┘├┤─│".encode(encoding)
        chars = {
            "top_left": "┌",
            "top_right": "┐",
            "bottom_left": "└",
            "bottom_right": "┘",
            "mid_left": "├",
            "mid_right": "┤",
            "horizontal": "─",
            "vertical": "│",
        }
    except Exception:
        chars = {
            "top_left": "+",
            "top_right": "+",
            "bottom_left": "+",
            "bottom_right": "+",
            "mid_left": "+",
            "mid_right": "+",
            "horizontal": "-",
            "vertical": "|",
        }

    print(chars["top_left"] + chars["horizontal"] * (content_width + 2) + chars["top_right"])
    print(f"{chars['vertical']} {body_lines[0].ljust(content_width)} {chars['vertical']}")
    print(chars["mid_left"] + chars["horizontal"] * (content_width + 2) + chars["mid_right"])
    for line in body_lines[divider_index:]:
        print(f"{chars['vertical']} {line.ljust(content_width)} {chars['vertical']}")
    print(chars["bottom_left"] + chars["horizontal"] * (content_width + 2) + chars["bottom_right"])
