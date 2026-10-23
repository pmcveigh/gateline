-- Run once after migration 006 when managing schema manually.
ALTER TABLE tickets ADD COLUMN attendee_name VARCHAR(120);
