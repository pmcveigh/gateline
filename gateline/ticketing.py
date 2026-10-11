"""Club ticket menus and shared pricing/eligibility rules."""

from datetime import date, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from sqlalchemy import select
from .models import Event, TicketClass


CLUB_TICKETS = {
    "Glentoran": (
        ("Grandstand Upper", "18", "Adult admission"),
        ("Grandstand Lower", "15", "Adult admission"),
        ("Sydenham End", "15", "Adult admission"),
        ("Concession", "8", "Eligible concessions"),
        ("Under 11", "1", "Must attend with a paying adult in this booking"),
        ("VIP", "70", "Adults only; £50 with a valid season-ticket number"),
    ),
    "Linfield": (
        ("South Stand Half Way Line", "18", "Adult admission"),
        ("General Admission", "15", "Adult admission"),
        ("Concession", "8", "Eligible concessions"),
        ("Under 11", "2", "Must attend with a paying adult in this booking"),
    ),
}
ADULT_NAMES = {"Adult", "General Admission", "Grandstand Upper", "Grandstand Lower", "Sydenham End", "South Stand Half Way Line", "VIP"}
VIP_MIN_AGE = 18


def is_adult(ticket_class):
    return ticket_class.name in ADULT_NAMES or ticket_class.name.lower().startswith("adult ")


def minimum_adult_price(event):
    prices = [tc.price for tc in event.classes if is_adult(tc) and tc.maximum > 0]
    return min(prices) if prices else None


def configure_club_tickets(db, event):
    """Add the club's menu without changing inventory or historical ticket prices."""
    existing = {tc.name: tc for tc in db.scalars(select(TicketClass).where(TicketClass.event_id==event.id))}
    for name, price, description in CLUB_TICKETS.get(event.home_team, ()):
        if name in existing:
            existing[name].price = Decimal(price)
            existing[name].description = description
        else:
            db.add(TicketClass(event_id=event.id, name=name, price=Decimal(price), description=description, minimum=0, maximum=10))
    db.flush()
    db.expire(event, ["classes"])


def upgrade_club_tickets(db):
    for event in db.scalars(select(Event).where(Event.home_team.in_(CLUB_TICKETS))):
        configure_club_tickets(db, event)
    db.commit()


def selected_classes(event, selection, quantity):
    classes = {tc.id: tc for tc in event.classes}
    lines = []
    for class_id, count in selection.items():
        try:
            tc = classes.get(int(class_id))
        except (TypeError, ValueError):
            raise ValueError("Invalid ticket class")
        if not tc or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("Invalid ticket selection")
        if count < tc.minimum or count > tc.maximum:
            raise ValueError("Ticket class quantity limit exceeded")
        lines.append((tc, count))
    if not lines or sum(count for _, count in lines) != quantity:
        raise ValueError("Ticket quantities must match the reservation")
    if any(tc.name == "Under 11" for tc, _ in lines) and not any(is_adult(tc) and tc.price > 0 for tc, _ in lines):
        raise ValueError("Under 11 tickets require a paying adult ticket in the same booking")
    return lines


def validate_vip_ages(event, lines, birth_dates):
    count = sum(qty for tc, qty in lines if tc.name == "VIP")
    if len(birth_dates) != count:
        raise ValueError("Enter a date of birth for each VIP attendee")
    kick_off = event.starts_at
    if kick_off.tzinfo is None: kick_off = kick_off.replace(tzinfo=timezone.utc)
    match_day = kick_off.astimezone(ZoneInfo("Europe/London")).date()
    for raw in birth_dates:
        try:
            born = date.fromisoformat(raw)
        except (TypeError, ValueError):
            raise ValueError("Enter a valid VIP attendee date of birth")
        age = match_day.year - born.year - ((match_day.month, match_day.day) < (born.month, born.day))
        if born > match_day or age < VIP_MIN_AGE:
            raise ValueError(f"VIP attendees must be aged {VIP_MIN_AGE} or above on the match date")
