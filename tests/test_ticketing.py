from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from gateline.database import Base
from gateline.models import Event, EventInventory, Order, PriorityIdentifier, Reservation, Seat, SeatRow, Section, Stand, TicketClass, Venue, Voucher
from gateline.services import checkout, reserve, reservation_rows
from gateline.ticketing import CLUB_TICKETS, configure_club_tickets, minimum_adult_price, upgrade_club_tickets


def customer():
    return dict(full_name="Test Fan", email="fan@example.com", address1="1 Road", address2="", city="Belfast", postcode="BT1", country="UK")


@pytest.fixture
def booking():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        venue = Venue(name="The Oval", address="Belfast")
        db.add(venue); db.flush()
        stand = Stand(venue_id=venue.id, name="Main Stand")
        db.add(stand); db.flush()
        section = Section(stand_id=stand.id, name="General Admission", mode="general", capacity=100)
        db.add(section); db.flush()
        event = Event(title="Glentoran v Linfield", home_team="Glentoran", away_team="Linfield", competition="NIFL Premiership 2026/27", venue_id=venue.id,
                      starts_at=datetime(datetime.now(timezone.utc).year+1, 1, 10, 15, tzinfo=timezone.utc),
                      sales_open=datetime.now(timezone.utc)-timedelta(days=1), sales_close=datetime(datetime.now(timezone.utc).year+1, 1, 10, 15, tzinfo=timezone.utc), published=True)
        db.add(event); db.flush()
        db.add(EventInventory(event_id=event.id, section_id=section.id, capacity=100))
        db.add(TicketClass(event_id=event.id, name="Adult", price=Decimal("15")))
        db.flush(); configure_club_tickets(db, event); db.commit(); db.expire(event, ["classes"])
        yield db, event, section, {tc.name: tc.id for tc in event.classes}
    engine.dispose()


@pytest.mark.parametrize("club", ["Glentoran", "Linfield"])
def test_club_prices_upgrade_existing_events_idempotently(booking, club):
    db, event, section, _ = booking
    event.home_team = club; db.commit()
    upgrade_club_tickets(db); upgrade_club_tickets(db)
    classes = db.scalars(select(TicketClass).where(TicketClass.event_id == event.id)).all()
    for name, price, _ in CLUB_TICKETS[club]:
        matching = [tc for tc in classes if tc.name == name]
        assert len(matching) == 1
        assert matching[0].price == Decimal(price)
    assert minimum_adult_price(event) == Decimal("15")
    assert db.get(Section, section.id).capacity == 100


@pytest.mark.parametrize("club,child_price", [("Glentoran", "1"), ("Linfield", "2")])
def test_under_11_requires_a_paid_adult_and_issues_mixed_tickets(booking, club, child_price):
    db, event, section, _ = booking
    event.home_team = club; db.commit(); upgrade_club_tickets(db)
    classes = {tc.name: tc.id for tc in event.classes}
    for selection in ({classes["Under 11"]: 1}, {classes["Under 11"]: 1, classes["Concession"]: 1}):
        with pytest.raises(ValueError, match="paying adult"):
            reserve(db, event.id, section.id, sum(selection.values()), [], selection)
    selection = {classes["Adult"]: 1, classes["Under 11"]: 2}
    r = reserve(db, event.id, section.id, 3, [], selection)
    order = checkout(db, r.token, None, customer())
    assert order.total == Decimal("15") + 2 * Decimal(child_price)
    assert sorted(t.price for t in order.tickets) == [Decimal(child_price), Decimal(child_price), Decimal("15")]
    assert sorted(t.ticket_class.name for t in order.tickets) == ["Adult", "Under 11", "Under 11"]


def test_legacy_checkout_cannot_bypass_under_11_rule(booking):
    db, event, section, classes = booking
    r = reserve(db, event.id, section.id, 1, [])
    with pytest.raises(ValueError, match="paying adult"):
        checkout(db, r.token, classes["Under 11"], customer())


@pytest.mark.parametrize("birth_dates", [[], ["minor"], ["future"], ["invalid"]])
def test_vip_rejects_missing_minor_future_and_invalid_dates(booking, birth_dates):
    db, event, section, classes = booking
    if birth_dates==["minor"]: birth_dates=[event.starts_at.date().replace(year=event.starts_at.year-17).isoformat()]
    if birth_dates==["future"]: birth_dates=[(event.starts_at.date()+timedelta(days=1)).isoformat()]
    r = reserve(db, event.id, section.id, 1, [], {classes["VIP"]: 1})
    with pytest.raises(ValueError, match="VIP"):
        checkout(db, r.token, None, customer(), vip_birth_dates=birth_dates)
    assert db.scalar(select(Order)) is None


def test_vip_full_price_and_eighteenth_birthday(booking):
    db, event, section, classes = booking
    r = reserve(db, event.id, section.id, 1, [], {classes["VIP"]: 1})
    order = checkout(db, r.token, None, customer(), vip_birth_dates=[event.starts_at.date().replace(year=event.starts_at.year-18).isoformat()])
    assert order.total == Decimal("70")
    assert order.tickets[0].price == Decimal("70")


def test_vip_discount_requires_valid_entitlement_and_consumes_only_on_success(booking):
    db, event, section, classes = booking
    member = PriorityIdentifier(code="ST123", maximum=1)
    db.add(member); db.commit()
    r = reserve(db, event.id, section.id, 1, [], {classes["VIP"]: 1})
    for code in (None, "WRONG"):
        with pytest.raises(ValueError, match="season-ticket"):
            checkout(db, r.token, None, customer(), priority_code=code, vip_season_holder=True, vip_birth_dates=["1990-01-01"])
    failed = checkout(db, r.token, None, customer(), "fail", "ST123", vip_season_holder=True, vip_birth_dates=["1990-01-01"])
    assert failed.total == Decimal("50") and not failed.tickets
    assert member.used == 0
    successful = checkout(db, r.token, None, customer(), priority_code=" st123 ", vip_season_holder=True, vip_birth_dates=["1990-01-01"])
    assert successful.total == Decimal("50") and successful.tickets[0].price == Decimal("50")
    assert member.used == 1
    another = reserve(db, event.id, section.id, 1, [], {classes["VIP"]: 1})
    with pytest.raises(ValueError, match="season-ticket"):
        checkout(db, another.token, None, customer(), priority_code="ST123", vip_season_holder=True, vip_birth_dates=["1990-01-01"])


def test_season_discount_and_priority_entitlement_are_not_double_counted(booking):
    db, event, section, classes = booking
    event.priority_until = datetime.now(timezone.utc) + timedelta(hours=1)
    member = PriorityIdentifier(code="ST1", maximum=2)
    db.add(member); db.commit()
    r = reserve(db, event.id, section.id, 2, [], {classes["VIP"]: 1, classes["Adult"]: 1})
    order = checkout(db, r.token, None, customer(), priority_code="ST1", vip_season_holder=True, vip_birth_dates=["1990-01-01"])
    assert order.total == Decimal("65") and member.used == 2


def test_reservation_expires_and_cannot_be_paid_twice(booking):
    db, event, section, classes = booking
    r = reserve(db, event.id, section.id, 1, [], {classes["Adult"]: 1})
    r.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    with pytest.raises(ValueError, match="expired"):
        checkout(db, r.token, None, customer())
    fresh = reserve(db, event.id, section.id, 1, [], {classes["Adult"]: 1})
    checkout(db, fresh.token, None, customer())
    with pytest.raises(ValueError, match="completed"):
        checkout(db, fresh.token, None, customer())


def test_mixed_assigned_seats_and_child_tokens_cannot_split_a_booking(booking):
    db, event, section, classes = booking
    section.mode = "assigned"
    row = SeatRow(section_id=section.id, name="A"); db.add(row); db.flush()
    seats = [Seat(row_id=row.id, number=str(i), available=True) for i in (1, 2)]
    db.add_all(seats); db.commit()
    r = reserve(db, event.id, section.id, 2, [s.id for s in seats], {classes["Adult"]: 1, classes["Under 11"]: 1})
    assert reservation_rows(db, r.token + "-1") == []
    order = checkout(db, r.token, None, customer())
    assert len(order.tickets) == 2
    assert {t.seat_id for t in order.tickets} == {s.id for s in seats}
    assert order.total == Decimal("16")


def test_mixed_discount_rounding_matches_order_total_and_free_adult_is_rejected(booking):
    db, event, section, classes = booking
    now = datetime.now(timezone.utc)
    voucher = Voucher(code="SAVE", kind="percentage", value=13, starts_at=now-timedelta(hours=1), expires_at=now+timedelta(hours=1), maximum_uses=2, enabled=True)
    db.add(voucher); db.commit()
    r = reserve(db, event.id, section.id, 4, [], {classes["Adult"]: 1, classes["Under 11"]: 3})
    order = checkout(db, r.token, None, customer(), voucher_code="SAVE")
    assert order.total == Decimal("15.66")
    assert sum(t.price for t in order.tickets) == order.total
    voucher.value = 100; db.commit()
    fresh = reserve(db, event.id, section.id, 2, [], {classes["Adult"]: 1, classes["Under 11"]: 1})
    with pytest.raises(ValueError, match="paying adult"):
        checkout(db, fresh.token, None, customer(), voucher_code="SAVE")


def test_rounding_cannot_make_accompanying_adult_free(booking):
    db,event,section,classes=booking
    db.get(TicketClass,classes["Adult"]).price=Decimal("0.01")
    now=datetime.now(timezone.utc)
    db.add(Voucher(code="SAVE",kind="fixed",value=Decimal("1"),starts_at=now-timedelta(hours=1),expires_at=now+timedelta(hours=1),maximum_uses=1,enabled=True));db.commit()
    r=reserve(db,event.id,section.id,2,[],{classes["Adult"]:1,classes["Under 11"]:1})
    with pytest.raises(ValueError,match="paying adult"):
        checkout(db,r.token,None,customer(),voucher_code="SAVE")
    assert db.scalar(select(Order)) is None


@pytest.mark.parametrize("counts", [{"missing": 1}, {999999: 1}, {1: -1}, {1: True}])
def test_invalid_selections_do_not_reserve_inventory(booking, counts):
    db, event, section, _ = booking
    with pytest.raises(ValueError): reserve(db, event.id, section.id, 1, [], counts)
    assert db.scalar(select(Reservation)) is None
