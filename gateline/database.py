import os
import secrets

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gateline.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass


def upgrade_schema():
    """Apply the small, additive upgrades required by existing installations.

    ``create_all`` deliberately does not alter tables which already exist.  Keep
    these compatibility changes here so starting a newer Gateline release with
    an older database does not leave the ORM ahead of the physical schema.
    """
    with engine.begin() as connection:
        event_columns = {
            column["name"] for column in inspect(connection).get_columns("events")
        }
        for column in ("sales_suspended", "archived"):
            if column not in event_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE events ADD COLUMN {column} "
                        "BOOLEAN NOT NULL DEFAULT FALSE"
                    )
                )

        order_columns = {
            column["name"] for column in inspect(connection).get_columns("orders")
        }
        if "access_token" not in order_columns:
            connection.execute(
                text("ALTER TABLE orders ADD COLUMN access_token VARCHAR(64)")
            )

        missing_tokens = connection.execute(
            text("SELECT id FROM orders WHERE access_token IS NULL")
        ).scalars()
        for order_id in missing_tokens:
            connection.execute(
                text("UPDATE orders SET access_token = :token WHERE id = :order_id"),
                {"token": secrets.token_urlsafe(24), "order_id": order_id},
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_access_token "
                "ON orders(access_token)"
            )
        )

        # Legacy reservations retain their single-class checkout behaviour.
        if inspect(connection).has_table("reservations"):
            columns = {column["name"] for column in inspect(connection).get_columns("reservations")}
            if "selection_json" not in columns:
                connection.execute(text("ALTER TABLE reservations ADD COLUMN selection_json TEXT NOT NULL DEFAULT '{}'"))

        if inspect(connection).has_table("ticket_classes"):
            columns = {column["name"] for column in inspect(connection).get_columns("ticket_classes")}
            if "enabled" not in columns:
                connection.execute(text("ALTER TABLE ticket_classes ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT TRUE"))
            if "adult_admission" not in columns:
                connection.execute(text("ALTER TABLE ticket_classes ADD COLUMN adult_admission BOOLEAN"))
            for column,default in (("concession_under",16),("concession_over",65)):
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE ticket_classes ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}"))

        additions={
            "events":{"season_claim_required":"BOOLEAN NOT NULL DEFAULT FALSE"},
            "event_inventory":{"audience":"VARCHAR(20) NOT NULL DEFAULT 'home'"},
            "ticket_classes":{"audience":"VARCHAR(20) NOT NULL DEFAULT 'home'","section_id":"INTEGER REFERENCES sections(id)"},
            "users":{"username":"VARCHAR(30)"},
            "orders":{"supporter_id":"INTEGER REFERENCES users(id)"},
            "tickets":{"attendee_user_id":"INTEGER REFERENCES users(id)","attendee_birth_date":"DATE","season_ticket_id":"INTEGER REFERENCES season_tickets(id)"},
            "club_pricing":{"portal_defaults_applied":"BOOLEAN NOT NULL DEFAULT FALSE"},
        }
        for table,fields in additions.items():
            if not inspect(connection).has_table(table): continue
            columns={column["name"] for column in inspect(connection).get_columns(table)}
            for column,definition in fields.items():
                if column not in columns: connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        if inspect(connection).has_table("users"):
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_supporter_id ON orders(supporter_id)"))
        if inspect(connection).has_table("tickets"):
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tickets_event_season ON tickets(event_id,season_ticket_id)"))

def get_db():
    with SessionLocal() as db:
        yield db
