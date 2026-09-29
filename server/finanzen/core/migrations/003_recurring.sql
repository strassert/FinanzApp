-- User decisions on detected recurring payments; the detection itself is
-- computed on demand from the transactions. Key: account:sign:payee.

CREATE TABLE recurring_decisions (
    key         TEXT PRIMARY KEY,
    decision    TEXT NOT NULL,                        -- rejected
    decided_at  TEXT NOT NULL
);
