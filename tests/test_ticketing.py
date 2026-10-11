from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from gateline.database import Base
from gateline.models import ClubPricing, Event, EventInventory, Order, PriorityIdentifier, Reservation, Seat, SeatRow, Section, Stand, TicketClass, Venue, Voucher
from gateline.services import checkout, reserve, reservation_rows
from gateline.ticketing import CLUB_TICKETS, configure_club_tickets, menu_for_club, minimum_adult_price, offered_classes, save_club_pricing, ticket_prefix, upgrade_club_tickets
from gateline.clubs import LEAGUES


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


def club_fixture(db, original, section, club):
    event=Event(title=f"{club} v Visitors",home_team=club,away_team="Visitors",competition=original.competition,venue_id=original.venue_id,starts_at=original.starts_at,sales_open=original.sales_open,sales_close=original.sales_close,published=True)
    db.add(event);db.flush()
    db.add(EventInventory(event_id=event.id,section_id=section.id,capacity=100))
    configure_club_tickets(db,event);db.commit()
    return event


@pytest.mark.parametrize("club", ["Glentoran", "Linfield"])
def test_club_prices_upgrade_existing_events_idempotently(booking, club):
    db, event, section, _ = booking
    event=club_fixture(db,event,section,club)
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
    event=club_fixture(db,event,section,club);upgrade_club_tickets(db)
    classes = {tc.name: tc.id for tc in event.classes}
    for selection in ({classes["Under 11"]: 1}, {classes["Under 11"]: 1, classes["Concession"]: 1}):
        with pytest.raises(ValueError, match="paying adult"):
            reserve(db, event.id, section.id, sum(selection.values()), [], selection)
    adult="Grandstand Lower" if club=="Glentoran" else "General Admission"
    selection = {classes[adult]: 1, classes["Under 11"]: 2}
    r = reserve(db, event.id, section.id, 3, [], selection)
    order = checkout(db, r.token, None, customer())
    assert order.total == Decimal("15") + 2 * Decimal(child_price)
    assert sorted(t.price for t in order.tickets) == [Decimal(child_price), Decimal(child_price), Decimal("15")]
    assert sorted(t.ticket_class.name for t in order.tickets) == [adult, "Under 11", "Under 11"]


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


def test_each_club_has_a_unique_stable_ticket_prefix():
    names=[entry.name for clubs in LEAGUES.values() for entry in clubs]
    assert len({ticket_prefix(name) for name in names})==len(names)
    assert ticket_prefix("Glentoran")=="GLENTORAN"
    assert ticket_prefix("GLENTORAN")==ticket_prefix("Glentoran")
    assert ticket_prefix("Linfield")=="LINFIELD"
    assert ticket_prefix("Queen's University")==ticket_prefix("Queen’s University")
    assert ticket_prefix("Cliftonville")!=ticket_prefix("Cliftonville Ladies")
    assert ticket_prefix("New Club!")!=ticket_prefix("New-Club")


def test_issued_tickets_use_the_home_clubs_prefix(booking):
    import re
    db,event,section,classes=booking
    reservation=reserve(db,event.id,section.id,2,[],{classes["Adult"]:2})
    order=checkout(db,reservation.token,None,customer())
    assert all(re.fullmatch(r"GLENTORAN-[A-F0-9]{12}",ticket.public_id) for ticket in order.tickets)
    assert len({ticket.public_id for ticket in order.tickets})==2


def test_saved_prices_and_custom_types_survive_restart_and_new_fixtures(booking):
    db,event,section,classes=booking
    reservation=reserve(db,event.id,section.id,1,[],{classes["Adult"]:1})
    issued=checkout(db,reservation.token,None,customer()).tickets[0]
    previous_id=issued.public_id
    menu=menu_for_club(db,"Glentoran")
    for item in menu:
        if item["name"]=="Grandstand Upper": item["price"]="23.50"
    menu.append({"name":"Terrace Premium","price":"19.25","description":"Adult admission","adult":True})
    save_club_pricing(db,"Glentoran",[m["name"] for m in menu],[m["price"] for m in menu],[m["description"] for m in menu],["adult" if m["adult"] else "other" for m in menu])
    upgrade_club_tickets(db);upgrade_club_tickets(db)
    future=club_fixture(db,event,section,"Glentoran")
    prices={tc.name:tc.price for tc in offered_classes(future)}
    assert prices["Grandstand Upper"]==Decimal("23.50")
    assert prices["Terrace Premium"]==Decimal("19.25")
    assert prices["VIP"]==Decimal("70") and prices["Under 11"]==Decimal("1")
    assert issued.price==Decimal("15") and issued.public_id==previous_id
    linfield=club_fixture(db,event,section,"Linfield")
    assert "Terrace Premium" not in {tc.name for tc in offered_classes(linfield)}


def test_unknown_club_does_not_receive_another_clubs_or_generic_prices(booking):
    db,event,section,_=booking
    unknown=club_fixture(db,event,section,"Unconfigured Club")
    assert offered_classes(unknown)==[]
    assert minimum_adult_price(unknown) is None


def test_removed_types_cannot_be_selected_but_issued_tickets_are_preserved(booking):
    db,event,section,classes=booking
    reservation=reserve(db,event.id,section.id,1,[],{classes["Adult"]:1})
    ticket=checkout(db,reservation.token,None,customer()).tickets[0]
    save_club_pricing(db,"Glentoran",["Grandstand Upper"],["18"],["Adult admission"],["adult"])
    assert {tc.name for tc in offered_classes(event)}=={"Grandstand Upper"}
    assert ticket.price==Decimal("15") and ticket.ticket_class.name=="Adult"
    with pytest.raises(ValueError): reserve(db,event.id,section.id,1,[],{classes["Adult"]:1})


@pytest.mark.parametrize("price",["","NaN","Infinity","-1","1.001","1000000"])
def test_club_price_is_explicit_and_validated(booking,price):
    db,_,_,_=booking
    before=menu_for_club(db,"Glentoran")
    with pytest.raises(ValueError): save_club_pricing(db,"Glentoran",["Adult"],[price],[""],["adult"])
    assert menu_for_club(db,"Glentoran")==before


def test_legacy_generic_seed_menu_is_retired_without_deleting_classes(booking):
    db,original,section,_=booking
    event=Event(title="Other v Visitors",home_team="Other Club",away_team="Visitors",competition=original.competition,venue_id=original.venue_id,starts_at=original.starts_at,sales_open=original.sales_open,sales_close=original.sales_close,published=True)
    db.add(event);db.flush()
    for title,price,description in (("Adult","15","Standard admission"),("Concession","10","Eligible concessions"),("Child","5","Under 16")):
        db.add(TicketClass(event_id=event.id,name=title,price=Decimal(price),description=description))
    db.commit();upgrade_club_tickets(db);upgrade_club_tickets(db)
    assert menu_for_club(db,"Other Club")==[]
    assert offered_classes(event)==[]
    assert len(event.classes)==3


def test_under_11_cannot_be_mistaken_for_its_own_accompanying_adult(booking):
    db,event,section,_=booking
    save_club_pricing(db,"Glentoran",["under 11"],["1"],["Child admission"],["adult"])
    child=next(tc for tc in offered_classes(event) if tc.name=="Under 11")
    with pytest.raises(ValueError,match="paying adult"):
        reserve(db,event.id,section.id,1,[],{child.id:1})
