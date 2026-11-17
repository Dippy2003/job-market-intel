-- Cleaned location, and a pointer from a duplicate row to the row we keep.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS location_normalized text;

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duplicate_of bigint;
