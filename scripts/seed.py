"""Create a disposable demo database covering the 2026/27 NIFL clubs."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateline.auth import hash_password
from gateline.database import Base, SessionLocal, engine
from gateline.models import (
    Club,
    Event,
    EventInventory,
    PriorityIdentifier,
    Section,
    Stand,
    TicketClass,
    User,
    Venue,
)


COMPETITIONS = {
    "NIFL Premiership 2026/27": [
        ("Ballymena United", "Ballymena Showgrounds"),
        ("Bangor", "Clandeboye Park"),
        ("Carrick Rangers", "Taylors Avenue"),
        ("Cliftonville", "Solitude"),
        ("Coleraine", "Coleraine Showgrounds"),
        ("Crusaders", "Seaview"),
        ("Dungannon Swifts", "Stangmore Park"),
        ("Glentoran", "The Oval"),
        ("Larne", "Inver Park"),
        ("Limavady United", "Limavady Showgrounds"),
        ("Linfield", "Windsor Park"),
        ("Portadown", "Shamrock Park"),
    ],
    "NIFL Championship 2026/27": [
        ("Annagh United", "BMG Arena"),
        ("Ards", "Clandeboye Park"),
        ("Armagh City", "Holm Park"),
        ("Ballinamallard United", "Ferney Park"),
        ("Dundela", "Wilgar Park"),
        ("Glenavon", "Mourneview Park"),
        ("Harland & Wolff Welders", "Blanchflower Stadium"),
        ("Institute", "Ryan McBride Brandywell Stadium"),
        ("Loughgall", "Lakeview Park"),
        ("Moyola Park", "Mill Meadow"),
        ("Newington", "Solitude"),
        ("Newry City", "Newry Showgrounds"),
        ("Queen’s University", "The Dub"),
        ("Rathfriland Rangers", "Iveagh Park"),
        ("Strabane Athletic", "Limavady Showgrounds"),
        ("Warrenpoint Town", "Milltown"),
    ],
    "NIFL Women’s Premiership 2026": [
        ("Cliftonville Ladies", "Solitude"),
        ("Crusaders Strikers", "Seaview"),
        ("Derry City Women", "Ryan McBride Brandywell Stadium"),
        ("Glentoran Women", "Blanchflower Stadium"),
        ("Larne Women", "Inver Park"),
        ("Linfield Women", "Midgley Park"),
        ("Lisburn Ladies", "Bluebell Stadium"),
        ("Lisburn Rangers", "Crewe Park"),
    ],
}


def email_slug(name: str) -> str:
    """Return a stable, safe local part for a demo club email address."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def seed_database() -> int:
    """Replace the configured database with the complete NIFL demo dataset."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        venues: dict[str, Venue] = {}
        sections: dict[str, Section] = {}
        for venue_name in sorted(
            {venue for clubs in COMPETITIONS.values() for _, venue in clubs}
        ):
            venue = Venue(
                name=venue_name,
                address=f"{venue_name}, Northern Ireland",
            )
            db.add(venue)
            db.flush()
            venues[venue_name] = venue

            stand = Stand(venue_id=venue.id, name="Main Stand", gate="Gate 1")
            db.add(stand)
            db.flush()
            section = Section(
                stand_id=stand.id,
                name="General Admission",
                mode="general",
                capacity=1000,
            )
            db.add(section)
            db.flush()
            sections[venue_name] = section

        fixture_number = 0
        first_kickoff = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)
        for competition, clubs in COMPETITIONS.items():
            for index, (home_team, venue_name) in enumerate(clubs):
                away_team = clubs[(index + 1) % len(clubs)][0]
                kickoff = first_kickoff + timedelta(days=fixture_number * 2)
                fixture_number += 1

                db.add(
                    Club(
                        name=home_team,
                        short_name=home_team,
                        contact_email=f"tickets@{email_slug(home_team)}.test",
                        address=f"{venue_name}, Northern Ireland",
                        currency="GBP",
                    )
                )
                event = Event(
                    title=f"{home_team} v {away_team}",
                    home_team=home_team,
                    away_team=away_team,
                    competition=competition,
                    venue_id=venues[venue_name].id,
                    starts_at=kickoff,
                    sales_open=datetime(2026, 8, 1, tzinfo=timezone.utc),
                    sales_close=kickoff,
                    description=f"{home_team} host {away_team} at {venue_name}.",
                    published=True,
                )
                db.add(event)
                db.flush()

                section = sections[venue_name]
                db.add(
                    EventInventory(
                        event_id=event.id,
                        section_id=section.id,
                        capacity=section.capacity,
                    )
                )
                db.add_all(
                    [
                        TicketClass(
                            event_id=event.id,
                            name=name,
                            description=description,
                            price=price,
                        )
                        for name, description, price in [
                            ("Adult", "Standard admission", Decimal("15")),
                            ("Concession", "Eligible concessions", Decimal("10")),
                            ("Child", "Under 16", Decimal("5")),
                        ]
                    ]
                )

        db.add_all(
            [
                PriorityIdentifier(code="ST001234", maximum=2),
                PriorityIdentifier(code="ST005678", maximum=1),
                User(
                    email="admin@gateline.test",
                    name="Demo Administrator",
                    password_hash=hash_password("Admin123!"),
                    role="admin",
                ),
                User(
                    email="gate@gateline.test",
                    name="Gate 1 Operator",
                    password_hash=hash_password("Gate123!"),
                    role="gate",
                    gate="Gate 1",
                ),
            ]
        )
        db.commit()

    return fixture_number


if __name__ == "__main__":
    if os.getenv("RESET_DEMO_DATABASE") != "1":
        raise SystemExit(
            "Refusing destructive demo seed. Set RESET_DEMO_DATABASE=1 "
            "with a disposable DATABASE_URL."
        )
    fixture_count = seed_database()
    print(f"Demo data created with {fixture_count} fixtures.")
