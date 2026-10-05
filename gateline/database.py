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

def get_db():
    with SessionLocal() as db:
        yield db
