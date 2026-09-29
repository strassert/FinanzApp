-- KI categorisation. Merchant key = "sign:normalised payee" (categories.merchant_key).

-- The user's answer to a suggestion ("Passt" / "Ändern"): acts like a rule
-- for every booking of that merchant and survives every recomputation.
CREATE TABLE merchant_categories (
    key          TEXT PRIMARY KEY,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    decided_at   TEXT NOT NULL
);

-- Answers of the language model per merchant (stage B). category_id NULL =
-- the model was not sure. Only this cache is read during recomputation.
CREATE TABLE ai_categories (
    key          TEXT PRIMARY KEY,
    category_id  INTEGER REFERENCES categories(id),
    model        TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

ALTER TABLE tx_derived ADD COLUMN merchant_key TEXT;
ALTER TABLE tx_derived ADD COLUMN category_hint TEXT;
