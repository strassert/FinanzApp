-- Depot positions from broker exports and security prices. The depot value
-- (holdings x last price) is written as daily balances of type DEPOT.

CREATE TABLE depot_trades (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    ext_id        TEXT NOT NULL,                      -- broker transaction number
    booking_date  TEXT NOT NULL,
    isin          TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    quantity      TEXT NOT NULL,                      -- decimal string, negative = sold
    amount_minor  INTEGER,
    currency      TEXT,
    UNIQUE (account_id, ext_id)
);
CREATE INDEX depot_trades_account ON depot_trades(account_id, booking_date);

CREATE TABLE security_prices (
    isin      TEXT NOT NULL,
    date      TEXT NOT NULL,
    price     TEXT NOT NULL,                          -- decimal string, per unit
    currency  TEXT NOT NULL,
    source    TEXT NOT NULL,                          -- quote | trade
    PRIMARY KEY (isin, date)
);
