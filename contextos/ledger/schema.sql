CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    ide             TEXT,
    model           TEXT,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_tokens_in   BIGINT DEFAULT 0,
    sent_tokens_in  BIGINT DEFAULT 0,
    savings_usd     DOUBLE DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id              TEXT PRIMARY KEY,
    session_id           TEXT NOT NULL,
    turn_index           INTEGER NOT NULL,
    role                 TEXT NOT NULL,
    raw_content          TEXT,
    heat_state           TEXT DEFAULT 'HOT',
    is_compacted         BOOLEAN DEFAULT FALSE,
    compacted_summary    TEXT,
    token_count_raw      INTEGER DEFAULT 0,
    token_count_compacted INTEGER DEFAULT 0,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);

CREATE TABLE IF NOT EXISTS sent_payloads (
    payload_id         TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL,
    turn_ids_included  TEXT,
    total_tokens_sent  INTEGER DEFAULT 0,
    tokens_saved       INTEGER DEFAULT 0,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pinned_segments (
    pin_id      TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    content     TEXT NOT NULL,
    label       TEXT,
    pinned_by   TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
