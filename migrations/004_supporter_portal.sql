-- Run once after migration 003 if managing migrations manually.
-- Startup applies additive columns and creates the new tables automatically.
ALTER TABLE users ADD COLUMN username VARCHAR(30);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username);
ALTER TABLE orders ADD COLUMN supporter_id INTEGER REFERENCES users(id);
CREATE INDEX IF NOT EXISTS ix_orders_supporter_id ON orders(supporter_id);
ALTER TABLE tickets ADD COLUMN attendee_user_id INTEGER REFERENCES users(id);
ALTER TABLE tickets ADD COLUMN attendee_birth_date DATE;
ALTER TABLE ticket_classes ADD COLUMN concession_under INTEGER NOT NULL DEFAULT 16;
ALTER TABLE ticket_classes ADD COLUMN concession_over INTEGER NOT NULL DEFAULT 65;
ALTER TABLE club_pricing ADD COLUMN portal_defaults_applied BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS supporter_profiles (
	user_id INTEGER NOT NULL, 
	birth_date DATE, 
	clubs_json TEXT NOT NULL, 
	force_concession BOOLEAN NOT NULL, 
	disability_type TEXT NOT NULL, 
	access_details TEXT NOT NULL, 
	share_access_needs BOOLEAN NOT NULL, 
	address1 VARCHAR NOT NULL, 
	address2 VARCHAR NOT NULL, 
	city VARCHAR NOT NULL, 
	postcode VARCHAR NOT NULL, 
	country VARCHAR NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS season_tickets (
	id INTEGER NOT NULL, 
	club_name VARCHAR(150) NOT NULL, 
	number VARCHAR(100) NOT NULL, 
	user_id INTEGER NOT NULL, 
	full_name VARCHAR(120) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	section VARCHAR(100) NOT NULL, 
	ticket_type VARCHAR(100) NOT NULL, 
	competition VARCHAR NOT NULL, 
	valid_from DATE NOT NULL, 
	valid_until DATE NOT NULL, 
	active BOOLEAN NOT NULL, 
	qr_token VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (club_name, number), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	UNIQUE (qr_token)
);

CREATE TABLE IF NOT EXISTS supporter_attendances (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	season_ticket_id INTEGER, 
	ticket_id INTEGER, 
	event_id INTEGER NOT NULL, 
	scanned_at TIMESTAMP NOT NULL, 
	operator_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, event_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(season_ticket_id) REFERENCES season_tickets (id), 
	FOREIGN KEY(ticket_id) REFERENCES tickets (id), 
	FOREIGN KEY(event_id) REFERENCES events (id), 
	FOREIGN KEY(operator_id) REFERENCES users (id)
);
-- Initialise the requested test supporter and current-season Glentoran record through application startup.
