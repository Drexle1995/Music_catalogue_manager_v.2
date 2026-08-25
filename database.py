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
    created_at      TEXT    NOT NULL,
    user_id         INTEGER REFERENCES users(id)
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

-- Quota ledger: one row per user per calendar day, tracks saves (not generations).
CREATE TABLE IF NOT EXISTS quota_ledger (
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date           TEXT    NOT NULL,
    daily_saves    INTEGER NOT NULL DEFAULT 0,
    monthly_saves  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
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

-- Sample-Bibliothek: Metadaten zu Audio-Samples (WAV/AIFF/FLAC).
-- Kompatibilitaets-Score und Transponierempfehlung werden zur Laufzeit
-- pro Song-Key berechnet und nicht gespeichert.
-- Track-Zuordnungen sind sitzungsgebunden und werden nicht persistent abgelegt.
CREATE TABLE IF NOT EXISTS samples (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    path                 TEXT    NOT NULL UNIQUE,         -- POSIX-Pfad zur Audiodatei
    name                 TEXT    NOT NULL,                -- Anzeigename im Sample-Browser
    category             TEXT    NOT NULL                 -- Oberkategorie: tone | color | environment
                         CHECK(category IN ('tone', 'color', 'environment')),
    subcategory          TEXT    NOT NULL,                -- Unterklasse innerhalb der Kategorie
    root_note            INTEGER,                         -- MIDI-Notennummer 0-127 (NULL = atonal)
    root_hz              REAL,                            -- Grundfrequenz in Hz (NULL = unbekannt)
    duration_sec         REAL    NOT NULL DEFAULT 0.0,   -- Laenge des Samples in Sekunden
    spectral_centroid_hz REAL    NOT NULL DEFAULT 0.0,   -- Spektraler Schwerpunkt in Hz
    source_sample_rate   INTEGER NOT NULL DEFAULT 44100, -- Abtastrate der Quelldatei
    channels             INTEGER NOT NULL DEFAULT 1      -- 1 = Mono, 2 = Stereo
                         CHECK(channels IN (1, 2)),
    tags                 TEXT    NOT NULL DEFAULT '[]',  -- JSON-Array freier Suchbegriffe
    bpm                  REAL,                           -- erkanntes Tempo in BPM (NULL = arhythmisch)
    analysed             INTEGER NOT NULL DEFAULT 0,     -- 0 = unanalysiert, 1 = analysiert
    created_at           TEXT    NOT NULL                -- ISO-Zeitstempel der Erfassung
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
    # Auth-Spalten fuer Web-Login — nullable, damit Demo-Nutzer unveraendert bleiben.
    if "password_hash" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "tier" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'")
    if "stripe_customer_id" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
    # is_admin: 1 = Zugang zu allen Admin-Routen, 0 = nur /generate und /stats.
    if "is_admin" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    sub_cols = {row["name"] for row in
                conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
    if "stripe_sub_id" not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN stripe_sub_id TEXT")
    if "period_end" not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN period_end TEXT")

    track_cols = {row["name"] for row in
                  conn.execute("PRAGMA table_info(tracks)").fetchall()}
    if "user_id" not in track_cols:
        conn.execute("ALTER TABLE tracks ADD COLUMN user_id INTEGER REFERENCES users(id)")

    # Migration: samples-Tabelle fuer aeltere Datenbanken nachtraglich anlegen.
    # CREATE TABLE IF NOT EXISTS genuegt hier, da die Tabelle im SCHEMA oben
    # bereits definiert ist und executescript sie beim Erstlauf anlegt.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS samples (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            path                 TEXT    NOT NULL UNIQUE,
            name                 TEXT    NOT NULL,
            category             TEXT    NOT NULL
                                 CHECK(category IN ('tone', 'color', 'environment')),
            subcategory          TEXT    NOT NULL,
            root_note            INTEGER,
            root_hz              REAL,
            duration_sec         REAL    NOT NULL DEFAULT 0.0,
            spectral_centroid_hz REAL    NOT NULL DEFAULT 0.0,
            source_sample_rate   INTEGER NOT NULL DEFAULT 44100,
            channels             INTEGER NOT NULL DEFAULT 1
                                 CHECK(channels IN (1, 2)),
            tags                 TEXT    NOT NULL DEFAULT '[]',
            bpm                  REAL,
            analysed             INTEGER NOT NULL DEFAULT 0,
            created_at           TEXT    NOT NULL
        );
    """)

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


# --- Auth helpers ------------------------------------------------------------

def get_user_by_email(email: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row


def create_user(email: str, password_hash: str, tier: str = "free"):
    """Insert a new web-auth user; returns the new user id."""
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, tier, is_subscriber, created_at) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (email.split("@")[0], email, password_hash, tier, now),
    )
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return uid


# --- Quota helpers -----------------------------------------------------------

def get_quota(user_id: int, date: str):
    """Return the quota_ledger row for (user_id, date), or None if it doesn't exist yet."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM quota_ledger WHERE user_id = ? AND date = ?",
        (user_id, date),
    ).fetchone()
    conn.close()
    return row


def increment_quota(user_id: int, date: str):
    """Upsert quota_ledger for today, incrementing daily and monthly saves by 1."""
    # monthly_saves counts saves in the same YYYY-MM month prefix as date.
    month_prefix = date[:7]  # e.g. "2026-08"
    conn = get_conn()
    # Ensure the row exists for today.
    conn.execute(
        "INSERT OR IGNORE INTO quota_ledger (user_id, date, daily_saves, monthly_saves) "
        "VALUES (?, ?, 0, 0)",
        (user_id, date),
    )
    conn.execute(
        "UPDATE quota_ledger SET daily_saves = daily_saves + 1 "
        "WHERE user_id = ? AND date = ?",
        (user_id, date),
    )
    # Sum monthly saves across all days in the same month.
    monthly = conn.execute(
        "SELECT COALESCE(SUM(daily_saves), 0) AS s FROM quota_ledger "
        "WHERE user_id = ? AND substr(date, 1, 7) = ?",
        (user_id, month_prefix),
    ).fetchone()["s"]
    # Write the monthly total back to every row for this month so /quota can read it cheaply.
    conn.execute(
        "UPDATE quota_ledger SET monthly_saves = ? "
        "WHERE user_id = ? AND substr(date, 1, 7) = ?",
        (monthly, user_id, month_prefix),
    )
    conn.commit()
    conn.close()
