from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from gateline.clubs import LEAGUES
from gateline.database import Base, get_db
from gateline.main import app
from gateline.models import Event, EventInventory, PriorityIdentifier, Reservation, Section, Stand, TicketClass, Venue
from gateline.ticketing import configure_club_tickets


class BrowseParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.selected = []
        self.open_leagues = 0
        self.events = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("aria-current") == "true":
            self.selected.append(attrs["href"])
        if tag == "details" and attrs.get("class") == "league-group" and "open" in attrs:
            self.open_leagues += 1
        if tag == "a" and attrs.get("href", "").startswith("/events/"):
            self.events.append(attrs["href"])


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'browse.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        venue = Venue(name="Solitude", address="Belfast")
        db.add(venue)
        db.flush()
        stand=Stand(venue_id=venue.id,name="Main Stand"); db.add(stand); db.flush()
        section=Section(stand_id=stand.id,name="General Admission",mode="general",capacity=100); db.add(section); db.flush()
        db.add(PriorityIdentifier(code="ST123",maximum=2))
        now = datetime.now(timezone.utc)
        for home, away, competition in (
            ("Cliftonville", "Linfield", "NIFL Premiership 2026/27"),
            ("Cliftonville Ladies", "Linfield Women", "NIFL Women’s Premiership 2026"),
            ("Queen’s University", "Ards", "NIFL Championship 2026/27"),
            ("Limavady United", "Bangor", "NIFL Premiership 2026/27"),
            ("Glentoran", "Linfield", "NIFL Premiership 2026/27"),
        ):
            event=Event(title=f"{home} v {away}", home_team=home, away_team=away,
                         competition=competition, venue_id=venue.id, published=True,
                         starts_at=now + timedelta(days=1), sales_open=now,
                         sales_close=now + timedelta(days=1))
            db.add(event); db.flush()
            db.add(EventInventory(event_id=event.id,section_id=section.id,capacity=100))
            db.add_all([TicketClass(event_id=event.id,name="Adult",price=Decimal("18")),
                        TicketClass(event_id=event.id,name="General Admission",price=Decimal("15")),
                        TicketClass(event_id=event.id,name="Concession",price=Decimal("1"))])
            db.flush(); configure_club_tickets(db,event)
        db.commit()

    def test_db():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr("gateline.main.LOG_DIR", tmp_path / "logs")
    app.dependency_overrides[get_db] = test_db
    # Startup is unnecessary: this fixture owns an isolated, fully created schema.
    client = TestClient(app)
    yield client
    client.close()
    app.dependency_overrides.pop(get_db)
    engine.dispose()


def test_directory_includes_all_four_leagues_without_requiring_fixtures(client):
    assert [len(clubs) for clubs in LEAGUES.values()] == [12, 16, 12, 8]
    response = client.get("/")
    assert response.status_code == 200
    for league in LEAGUES:
        assert league.replace("'", "&#39;") in response.text
    assert "Ballyclare Comrades" in response.text
    assert "Limavady United" in response.text
    assert "Other clubs" not in response.text
    assert BrowseParser(response.text).open_leagues == 1
    empty = client.get("/", params={"club": "Ballyclare Comrades"})
    assert empty.status_code == 200
    assert "No fixtures match these filters." in empty.text
    assert BrowseParser(empty.text).open_leagues == 1
    profile = client.get("/clubs/Ballyclare%20Comrades")
    assert profile.status_code == 200
    assert "Dixon Park" in profile.text


def test_womens_filter_is_distinct_from_mens_and_keeps_other_filters(client):
    response = client.get("/", params={"club": "Cliftonville Ladies", "venue": 1,
                                     "competition": "NIFL Women’s Premiership 2026",
                                     "date": (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()})
    assert response.status_code == 200
    parsed = BrowseParser(response.text)
    assert set(parsed.events) == {"/events/2"}
    assert parsed.open_leagues == 1
    assert len(parsed.selected) == 1
    assert "club=Cliftonville%20Ladies" in parsed.selected[0]
    assert "venue=1" in parsed.selected[0]
    assert "competition=" in parsed.selected[0]
    assert "date=" in parsed.selected[0]
    mens = client.get("/", params={"club": "Cliftonville"})
    assert set(BrowseParser(mens.text).events) == {"/events/1"}


def test_club_apostrophe_alias_preserves_existing_fixtures_and_profile(client):
    for name in ("Queen's University", "Queen’s University"):
        response = client.get("/", params={"club": name})
        assert response.status_code == 200
        assert set(BrowseParser(response.text).events) == {"/events/3"}
        profile = client.get(f"/clubs/{name}")
        assert profile.status_code == 200
        assert "Blanchflower Stadium" in profile.text


@pytest.mark.parametrize("name", ["NIFL Premiership 2026/27", "NIFL Championship 2026/27", "NIFL Women's Premiership 2026", "NIFL Women’s Premiership 2026", "NIFL Premiership", "NCL Premier"])
def test_competition_profiles_accept_encoded_slashes_aliases_and_empty_leagues(client,name):
    response=client.get("/competitions/"+quote(name,safe=""))
    assert response.status_code==200
    assert "Competition" in response.text
    if name=="NCL Premier": assert "No events listed." in response.text


def test_unknown_competition_remains_not_found(client):
    assert client.get("/competitions/does-not-exist").status_code==404


def test_match_cards_use_minimum_adult_price_and_profiles_include_dates(client):
    for path in ("/", "/clubs/Cliftonville", "/venues/1", "/competitions/NIFL%20Premiership%202026%2F27"):
        response=client.get(path)
        assert response.status_code==200
        assert "Adult tickets from £15.00" in response.text
        assert "Adult tickets from £1.00" not in response.text
        if path!="/":
            assert 'class="match-date"' in response.text
            assert (datetime.now(timezone.utc)+timedelta(days=1)).strftime("%d %b %Y") in response.text


def test_mixed_ticket_reservation_post_and_checkout_keep_prices_and_expiry(client):
    event_page=client.get("/events/5")
    assert "Grandstand Upper" in event_page.text and "£18.00" in event_page.text
    # Find class IDs from the public selection form without relying on seed IDs.
    import re
    pairs=re.findall(r'<b>([^<]+) <span.*?name="class_ids" value="(\d+)"',event_page.text,re.S)
    classes={name.strip():int(class_id) for name,class_id in pairs}
    rejected=client.post("/events/5/reserve",data={"section_id":1,"class_ids":[classes["Under 11"]],"ticket_quantities":[1]},follow_redirects=False)
    assert rejected.status_code==409 and "paying adult" in rejected.text
    accepted=client.post("/events/5/reserve",data={"section_id":1,"class_ids":[classes["Grandstand Lower"],classes["Under 11"]],"ticket_quantities":[1,1]},follow_redirects=False)
    assert accepted.status_code==303
    location=accepted.headers["location"]
    first=client.get(location); second=client.get(location)
    assert first.status_code==200 and "Grandstand Lower" in first.text and "Under 11" in first.text
    assert "£15.00" in first.text and "£1.00" in first.text
    expiry=lambda html: re.search(r'data-expires="(\d+)"',html).group(1)
    assert expiry(first.text)==expiry(second.text)
    response=client.post(location,data={"full_name":"Test Fan","email":"fan@example.com","address1":"1 Road","city":"Belfast","postcode":"BT1","country":"UK"})
    assert response.status_code==200 and "Total £16.00" in response.text
