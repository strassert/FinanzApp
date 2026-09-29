-- Day a booking counts for in budget periods. Equals the booking date,
-- except a salary booked in the last days of a month (calendar months),
-- which counts from the 1st of the next month. Filled by core.recompute;
-- NULL until the first recompute after this migration.

ALTER TABLE tx_derived ADD COLUMN budget_date TEXT;
