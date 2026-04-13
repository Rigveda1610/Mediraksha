import json
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mediraksha.db")


def _get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create audit table if not exists. Call on app startup."""
    conn = _get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            patient TEXT,
            report_type TEXT,
            diagnoses TEXT,
            risk_level TEXT,
            language TEXT,
            file TEXT,
            words_in_report INTEGER
        )
    """
    )
    conn.commit()
    conn.close()
    logger.info("Audit database initialized at %s", DB_PATH)


def add_entry(entry: dict, max_audit: int = 100):
    """Insert audit entry, trim to max_audit most recent."""
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO audit_log (id, timestamp, patient, report_type, diagnoses, risk_level, language, file, words_in_report) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry["id"],
            entry["timestamp"],
            entry.get("patient"),
            entry.get("report_type"),
            json.dumps(entry.get("diagnoses", [])),
            entry.get("risk_level"),
            entry.get("language"),
            entry.get("file"),
            entry.get("words_in_report"),
        ),
    )
    conn.execute(
        """
        DELETE FROM audit_log WHERE id NOT IN (
            SELECT id FROM audit_log ORDER BY timestamp DESC LIMIT ?
        )
    """,
        (max_audit,),
    )
    conn.commit()
    conn.close()
    logger.info("Stored audit entry %s", entry.get("id"))


def get_log():
    """Return all entries ordered by most recent first."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC").fetchall()
    conn.close()
    result = []
    for row in rows:
        entry = dict(row)
        entry["diagnoses"] = json.loads(entry.get("diagnoses") or "[]")
        result.append(entry)
    logger.info("Loaded %d audit entries", len(result))
    return result


def clear_log():
    conn = _get_db()
    conn.execute("DELETE FROM audit_log")
    conn.commit()
    conn.close()
    logger.info("Cleared audit log at %s", datetime.now().isoformat())
