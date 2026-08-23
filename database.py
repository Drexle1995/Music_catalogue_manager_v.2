"""
Datenbankschicht (SQLite).

Enthaelt das Schema, den Verbindungsaufbau und kleine Hilfsfunktionen.
Bewusst ohne ORM gehalten, damit im Pruefungsgespraech jede Zeile SQL
nachvollziehbar und erklaerbar ist.
"""

import json
import os
import sqlite3
from datetime import datetime

import config


# --- Schema -----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    genre           TEXT,
    source_midi     TEXT    UNIQUE,          -- Pfad der .mid aus Music Architect
    watermark_tag   TEXT,                    -- Layer-1 copyright-Tag
    watermark_hash  TEXT,                    -- Layer-1 SHA-256 (Dateiname)
    fitness_score   REAL,                    -- optional (falls im Namen kodiert)
    status          TEXT    NOT NULL DEFAULT 'available',  -- available|leased|exclusive_sold
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    tier        TEXT    NOT NULL,            -- z.B. lease_wav, trackout ...
    file_path   TEXT    NOT NULL UNIQUE,     -- Pfad der gemasterten Audiodatei (DAW)
    file_format TEXT,
    found_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS licenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id      INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    tier          TEXT    NOT NULL,          -- Preis-Stufe (siehe config.DEFAULT_TIERS)
    license_type  TEXT    NOT NULL,          -- lease | exclusive
    buyer_name    TEXT,
    buyer_email   TEXT,
    buyer_user_id INTEGER REFERENCES users(id),  -- registrierter Kaeufer (NULL = Gast)
    price         REAL    NOT NULL,
    currency      TEXT    NOT NULL DEFAULT 'EUR',
    payment_status TEXT   NOT NULL DEFAULT 'open',  -- open | paid
    paid_at       TEXT,
    sold_at       TEXT    NOT NULL,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    email          TEXT UNIQUE,
    is_subscriber  INTEGER NOT NULL DEFAULT 0,   -- 0 = Basis, 1 = Abo
    sub_start      TEXT,                          -- Abo-Beginn (ISO-Datum)
    sub_end        TEXT,                          -- Abo-Ende (ISO-Datum)
    created_at     TEXT NOT NULL
);

-- Abgeschlossene Abos (Freemium-Umsatzstrom, mit Laufzeit).
CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    term_months  INTEGER NOT NULL,
    price        REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',    -- open | paid
    start_date   TEXT,
    end_date     TEXT,
    created_at   TEXT NOT NULL,
    paid_at      TEXT
);

-- Nutzungsprotokoll der Track-Generierung -> Grundlage fuer das Tageslimit.
CREATE TABLE IF NOT EXISTS generations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source      TEXT,                            -- z.B. erzeugte Datei / Lauf-Info
    created_at  TEXT NOT NULL                    -- ISO-Zeit (lokal)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Audit-Protokoll: jede geschaeftsrelevante Aktion wird revisionssicher
-- mitgeschrieben (erfuellt die Anforderung "Protokoll fuehren").
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    event      TEXT NOT NULL,                -- z.B. LICENSE_SOLD, SCAN, SETTING_CHANGED
    entity     TEXT,                         -- track | license | settings | catalog
    entity_id  TEXT,
    details    TEXT                          -- JSON mit Zusatzinfos
);
"""


def get_conn():
    """Liefert eine SQLite-Verbindung mit Fremdschluessel-Enforcement."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Legt Tabellen an und befuellt Standard-Einstellungen (idempotent)."""
    conn = get_conn()
    conn.executescript(SCHEMA)

    # Standardwerte fuer Einstellungen setzen, falls noch nicht vorhanden.
    defaults = {}
    defaults.update(config.DEFAULT_ECONOMICS)
    defaults.update(config.DEFAULT_SUBSCRIPTION)
    defaults.update(config.DEFAULT_BILLING)
    defaults["catalog_dir"] = config.DEFAULT_CATALOG_DIR
    defaults["export_dir"] = config.DEFAULT_EXPORT_DIR
    defaults["music_architect_cmd"] = config.DEFAULT_MA_COMMAND
    for key, tier in config.DEFAULT_TIERS.items():
        defaults[f"price_{key}"] = str(tier["price"])

    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    # --- Leichte Migration: neue Spalten ergaenzen (aeltere DBs) ------------
    lic_cols = {row["name"] for row in
                conn.execute("PRAGMA table_info(licenses)").fetchall()}
    if "list_price" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN list_price REAL")
    if "discount_pct" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN discount_pct REAL DEFAULT 0")
    if "payment_status" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN payment_status TEXT DEFAULT 'open'")
    if "paid_at" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN paid_at TEXT")
    if "buyer_user_id" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN buyer_user_id INTEGER")

    user_cols = {row["name"] for row in
                 conn.execute("PRAGMA table_info(users)").fetchall()}
    if "sub_start" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN sub_start TEXT")
    if "sub_end" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN sub_end TEXT")

    # --- Zwei Demo-Nutzer anlegen, damit Rabatt & Limit sofort erlebbar sind -
    user_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    if user_count == 0:
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("INSERT INTO users (name, email, is_subscriber, created_at) "
                     "VALUES (?, ?, 1, ?)", ("Abo-Kunde (Demo)", "abo@example.com", now))
        conn.execute("INSERT INTO users (name, email, is_subscriber, created_at) "
                     "VALUES (?, ?, 0, ?)", ("Basis-Kunde (Demo)", "basis@example.com", now))

    conn.commit()
    conn.close()


# --- Einstellungen ----------------------------------------------------------

def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_all_settings():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# --- Audit-Protokoll --------------------------------------------------------

def log_event(event, entity=None, entity_id=None, details=None):
    """Schreibt einen Eintrag ins Audit-Protokoll."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (ts, event, entity, entity_id, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now().isoformat(timespec="seconds"),
            event,
            entity,
            str(entity_id) if entity_id is not None else None,
            json.dumps(details, ensure_ascii=False) if details else None,
        ),
    )
    conn.commit()
    conn.close()


def get_audit_log(limit=500):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows
