-- Amounts are integers in minor units. Dates are ISO strings (YYYY-MM-DD),
-- timestamps ISO 8601 UTC.

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE connections (
    id            INTEGER PRIMARY KEY,
    institution   TEXT NOT NULL,
    country       TEXT NOT NULL,
    session_id    TEXT,
    valid_until   TEXT,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | expired | error
    paused_until  TEXT,
    last_error    TEXT,
    last_sync_at  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE pending_consents (
    state         TEXT PRIMARY KEY,
    institution   TEXT NOT NULL,
    country       TEXT NOT NULL,
    connection_id INTEGER REFERENCES connections(id),  -- set when renewing
    created_at    TEXT NOT NULL
);

CREATE TABLE accounts (
    id                  INTEGER PRIMARY KEY,
    connection_id       INTEGER REFERENCES connections(id),
    identification_hash TEXT UNIQUE,
    uid                 TEXT,
    source              TEXT NOT NULL,                -- api | import | manual
    kind                TEXT NOT NULL,                -- giro | card | paypal | broker | depot | savings | other
    name                TEXT NOT NULL,
    institution         TEXT,
    currency            TEXT NOT NULL,
    iban                TEXT,
    owner_name          TEXT,
    patterns            TEXT NOT NULL DEFAULT '',     -- comma-separated, matched case-insensitively
    credit_limit_minor  INTEGER,
    hidden              INTEGER NOT NULL DEFAULT 0,
    sort                INTEGER NOT NULL DEFAULT 0,
    color_slot          INTEGER,
    history_loaded_at   TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE balances (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    amount_minor  INTEGER NOT NULL,
    currency      TEXT NOT NULL,
    balance_type  TEXT NOT NULL,                      -- ISO code, or MANUAL / IMPORT
    as_of         TEXT NOT NULL,
    fetched_at    TEXT NOT NULL
);
CREATE INDEX balances_account ON balances(account_id, as_of);

CREATE TABLE transactions (
    id                     INTEGER PRIMARY KEY,
    account_id             INTEGER NOT NULL REFERENCES accounts(id),
    source                 TEXT NOT NULL,             -- api | import | wallet | manual
    ext_id                 TEXT NOT NULL,             -- bank reference or fingerprint
    status                 TEXT NOT NULL,             -- booked | pending
    booking_date           TEXT NOT NULL,
    value_date             TEXT,
    amount_minor           INTEGER NOT NULL,
    currency               TEXT NOT NULL,
    original_amount_minor  INTEGER,
    original_currency      TEXT,
    counterparty           TEXT,
    counterparty_iban      TEXT,
    description            TEXT NOT NULL DEFAULT '',
    mcc                    TEXT,
    apple_pay              INTEGER NOT NULL DEFAULT 0,
    card                   TEXT,
    raw                    TEXT,
    first_seen             TEXT NOT NULL,
    last_seen              TEXT NOT NULL,
    removed_at             TEXT,                      -- pending entry the bank no longer returns
    superseded_by          INTEGER REFERENCES transactions(id),
    user_category_id       INTEGER REFERENCES categories(id),
    note                   TEXT,
    user_excluded          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (account_id, source, ext_id)
);
CREATE INDEX transactions_date ON transactions(booking_date);

-- User decisions on link suggestions; they survive every recomputation.
CREATE TABLE link_decisions (
    kind        TEXT NOT NULL,                        -- transfer | duplicate
    a_id        INTEGER NOT NULL REFERENCES transactions(id),
    b_id        INTEGER NOT NULL REFERENCES transactions(id),
    decision    TEXT NOT NULL,                        -- confirmed | rejected
    decided_at  TEXT NOT NULL,
    PRIMARY KEY (kind, a_id, b_id)
);

-- Derived data: fully rebuilt by core.recompute.
CREATE TABLE links (
    id        INTEGER PRIMARY KEY,
    kind      TEXT NOT NULL,        -- transfer | paypal | refund | duplicate | wallet
    a_id      INTEGER NOT NULL,
    b_id      INTEGER,
    status    TEXT NOT NULL,        -- auto | suggested | confirmed
    evidence  TEXT NOT NULL
);
CREATE INDEX links_a ON links(a_id);
CREATE INDEX links_b ON links(b_id);

CREATE TABLE tx_derived (
    tx_id            INTEGER PRIMARY KEY REFERENCES transactions(id),
    role             TEXT NOT NULL,  -- expense | income | transfer | excluded
    category_id      INTEGER,
    category_source  TEXT NOT NULL,  -- user | transfer | rule | keyword | mcc | refund | default
    amount_eur_minor INTEGER         -- NULL = no rate ("nicht umgerechnet")
);

CREATE TABLE categories (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL,       -- expense | income | transfer
    color_slot  INTEGER,
    builtin     INTEGER NOT NULL DEFAULT 0,
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE category_rules (
    id           INTEGER PRIMARY KEY,
    pattern      TEXT NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    created_at   TEXT NOT NULL
);

CREATE TABLE fx_rates (
    date      TEXT NOT NULL,
    currency  TEXT NOT NULL,
    rate      TEXT NOT NULL,         -- units of currency per 1 EUR (ECB reference), decimal string
    PRIMARY KEY (date, currency)
);

CREATE TABLE import_mappings (
    account_id  INTEGER PRIMARY KEY REFERENCES accounts(id),
    mapping     TEXT NOT NULL        -- JSON
);

CREATE TABLE wallet_events (
    id            INTEGER PRIMARY KEY,
    received_at   TEXT NOT NULL,
    occurred_at   TEXT NOT NULL,
    amount_minor  INTEGER,
    currency      TEXT,
    merchant      TEXT,
    card          TEXT,
    account_id    INTEGER REFERENCES accounts(id),
    tx_id         INTEGER REFERENCES transactions(id),
    status        TEXT NOT NULL,     -- recorded | duplicate | unassigned | ignored
    reason        TEXT
);

CREATE TABLE api_tokens (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    scope         TEXT NOT NULL,     -- app | demo | home
    created_at    TEXT NOT NULL,
    last_used_at  TEXT,
    revoked_at    TEXT
);

CREATE TABLE sync_runs (
    id             INTEGER PRIMARY KEY,
    connection_id  INTEGER REFERENCES connections(id),
    trigger        TEXT NOT NULL,    -- schedule | user | consent
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT NOT NULL,    -- ok | rate_limited | expired | error | skipped
    message        TEXT,
    new_count      INTEGER NOT NULL DEFAULT 0
);
