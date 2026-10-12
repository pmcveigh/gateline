-- Run once after migration 004 if managing migrations manually.
-- Application startup applies these additive changes automatically.
ALTER TABLE events ADD COLUMN season_claim_required BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE event_inventory ADD COLUMN audience VARCHAR(20) NOT NULL DEFAULT 'home';
ALTER TABLE ticket_classes ADD COLUMN audience VARCHAR(20) NOT NULL DEFAULT 'home';
ALTER TABLE ticket_classes ADD COLUMN section_id INTEGER REFERENCES sections(id);
ALTER TABLE tickets ADD COLUMN season_ticket_id INTEGER REFERENCES season_tickets(id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_tickets_event_season ON tickets(event_id,season_ticket_id);
-- Startup creates the requested demonstration fixture, allocations and test codes.
