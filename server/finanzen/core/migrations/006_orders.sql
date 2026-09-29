-- Online orders (Amazon export) and splitting a bank transaction into items.

-- Raw order items, as imported. Never deleted; re-import adds only new rows.
CREATE TABLE order_items (
    id                INTEGER PRIMARY KEY,
    source            TEXT NOT NULL,          -- amazon
    ext_id            TEXT NOT NULL,          -- stable identity within the source
    order_id          TEXT NOT NULL,
    shipment_key      TEXT NOT NULL,          -- order_id + ship date: one charge per shipment
    order_date        TEXT NOT NULL,
    ship_date         TEXT,
    name              TEXT NOT NULL,
    quantity          INTEGER NOT NULL DEFAULT 1,
    amount_minor      INTEGER NOT NULL,       -- total owed for the line, positive
    currency          TEXT NOT NULL,
    payment           TEXT,
    status            TEXT,
    user_category_id  INTEGER REFERENCES categories(id),
    imported_at       TEXT NOT NULL,
    UNIQUE (source, ext_id)
);
CREATE INDEX order_items_shipment ON order_items(shipment_key);

-- User decisions on shipment <-> bank transaction matches.
CREATE TABLE order_decisions (
    shipment_key  TEXT NOT NULL,
    tx_id         INTEGER NOT NULL REFERENCES transactions(id),
    decision      TEXT NOT NULL,              -- confirmed | rejected
    decided_at    TEXT NOT NULL,
    PRIMARY KEY (shipment_key, tx_id)
);

-- Derived (rebuilt by recompute): which shipment paid by which transaction.
CREATE TABLE order_matches (
    shipment_key  TEXT NOT NULL,
    tx_id         INTEGER NOT NULL,
    status        TEXT NOT NULL,              -- auto | suggested | confirmed
    PRIMARY KEY (shipment_key, tx_id)
);

-- Derived: a transaction split into item lines; amounts sum to the transaction.
CREATE TABLE tx_splits (
    tx_id            INTEGER NOT NULL,
    item_id          INTEGER NOT NULL,
    amount_eur_minor INTEGER,                 -- signed like the transaction
    category_id      INTEGER,
    category_source  TEXT NOT NULL,
    PRIMARY KEY (tx_id, item_id)
);

-- One row per counted line: whole transactions, or their splits.
CREATE VIEW tx_lines AS
    SELECT t.id AS tx_id, NULL AS item_id, t.account_id, t.booking_date, d.budget_date, t.status,
           d.role, d.category_id, d.amount_eur_minor
    FROM transactions t JOIN tx_derived d ON d.tx_id = t.id
    WHERE NOT EXISTS (SELECT 1 FROM tx_splits s WHERE s.tx_id = t.id)
    UNION ALL
    SELECT t.id, s.item_id, t.account_id, t.booking_date, d.budget_date, t.status,
           d.role, s.category_id, s.amount_eur_minor
    FROM tx_splits s JOIN transactions t ON t.id = s.tx_id JOIN tx_derived d ON d.tx_id = t.id;
