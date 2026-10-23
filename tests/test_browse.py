from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import quote, parse_qs, urlsplit, urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from gateline.clubs import LEAGUES
from gateline.database import Base, get_db
from gateline.main import app
from gateline.models import Event, EventInventory, PriorityIdentifier, Reservation, Section, Stand, TicketClass, User, Venue
from gateline.auth import hash_password
from gateline.ticketing import configure_club_tickets

STAFF_PASSWORD_HASH=hash_password("Test123!")


class BrowseParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.selected = []
        self.selected_values = {}
        self.open_leagues = 0
        self.events = []
        self.feed(html)
        if self.selected_values: self.selected = ["/?" + urlencode(self.selected_values, doseq=True)]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and "checked" in attrs:
            self.selected_values.setdefault(attrs["name"], []).append(attrs["value"])
        if tag == "a" and attrs.get("aria-current") == "true" and "club-card" in attrs.get("class", "").split():
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
        db.add_all([User(email="admin@test.test",name="Admin",password_hash=STAFF_PASSWORD_HASH,role="admin"),User(email="gate@test.test",name="Gate",password_hash=STAFF_PASSWORD_HASH,role="gate")])
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
    monkeypatch.setattr("gateline.main.engine",engine)
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
    assert BrowseParser(response.text).open_leagues == 0
    empty = client.get("/", params={"club": "Ballyclare Comrades"})
    assert empty.status_code == 200
    assert "No fixtures match these filters." in empty.text
    assert BrowseParser(empty.text).open_leagues == 0
    profile = client.get("/clubs/Ballyclare%20Comrades")
    assert profile.status_code == 200
    assert "Dixon Park" in profile.text


def test_womens_filter_is_distinct_from_mens_and_keeps_other_filters(client):
    response = client.get("/", params={"club": "Cliftonville Ladies", "venue": 1,
                                     "competition": "NIFL Women’s Premiership 2026"})
    assert response.status_code == 200
    parsed = BrowseParser(response.text)
    assert set(parsed.events) == {"/events/2"}
    assert parsed.open_leagues == 0
    assert len(parsed.selected) == 1
    selected=parse_qs(urlsplit(parsed.selected[0]).query)
    assert selected=={"club":["Cliftonville Ladies"],"venue":["1"],"competition":["NIFL Women's Premiership"]}
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
        assert ("Tickets from £15.00" if path == "/" else "Adult tickets from £15.00") in response.text
        assert "Adult tickets from £1.00" not in response.text
        if path!="/":
            assert 'class="match-date"' in response.text
            assert __import__("gateline.main",fromlist=["local_time"]).local_time(datetime.now(timezone.utc)+timedelta(days=1)).strftime("%d %b %Y") in response.text


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
    response=client.post(location,data={"full_name":"Test Fan","email":"fan@example.com","address1":"1 Road","city":"Belfast","postcode":"BT1","country":"UK","attendee_birth_dates":["", "2018-01-01"],"attendee_names":["Test Fan", "Child Fan"]})
    assert response.status_code==200 and "Total £16.00" in response.text


def test_sidebar_filters_replace_date_and_per_fixture_counts(client):
    response=client.get("/",params={"club":"Cliftonville","venue":1,"competition":"NIFL Premiership 2026/27","date":"1999-01-01"})
    assert response.status_code==200
    assert set(BrowseParser(response.text).events)=={"/events/1"}
    assert 'id="fixture-filters"' in response.text
    assert '<select name="venue"' not in response.text and '<select name="competition"' not in response.text
    assert 'name="date"' not in response.text and 'date=' not in response.text
    assert '<em>' not in response.text
    assert '<summary>Stadium' in response.text and '<summary>Competition' in response.text


def test_ticket_selection_starts_at_zero_and_does_not_disclose_stock(client):
    import re
    response=client.get("/events/5")
    assert response.status_code==200
    assert re.findall(r'name="ticket_quantities"[^>]*value="([^"]*)"',response.text)
    assert set(re.findall(r'name="ticket_quantities"[^>]*value="([^"]*)"',response.text))=={"0"}
    assert "100 available" not in response.text and " tickets left" not in response.text
    empty=client.post("/events/5/reserve",data={"section_id":1},follow_redirects=False)
    assert empty.status_code==409


def test_club_pricing_is_restricted_to_administrators(client):
    assert client.get("/admin/clubs/Glentoran/pricing").status_code==401
    assert client.post("/admin/clubs/Glentoran/pricing").status_code==401
    client.post("/login",data={"email":"gate@test.test","password":"Test123!"})
    assert client.get("/admin/clubs/Glentoran/pricing").status_code==403
    assert client.post("/admin/clubs/Glentoran/pricing").status_code==403


def test_club_prices_override_initial_defaults_on_new_fixtures(client):
    client.post("/login",data={"email":"admin@test.test","password":"Test123!"})
    editor=client.get("/admin/clubs/Ballyclare%20Comrades/pricing")
    assert editor.status_code==200
    assert 'name="ticket_prices" type="number" value="15"' in editor.text
    saved=client.post("/admin/clubs/Ballyclare%20Comrades/pricing",data={"ticket_names":["Adult","Concession"],"ticket_prices":["21","9.50"],"ticket_descriptions":["Home admission","Eligible concessions"],"ticket_categories":["adult","other"]},follow_redirects=False)
    assert saved.status_code==303
    now=datetime.now(timezone.utc)
    payload={"title":"Ballyclare v Glentoran","home_team":"Ballyclare Comrades","away_team":"Glentoran","competition":"NCL Premier","venue_id":1,"starts_at":(now+timedelta(days=3)).isoformat(),"sales_open":(now-timedelta(hours=1)).isoformat(),"sales_close":(now+timedelta(days=2)).isoformat()}
    draft=client.post("/admin/events",data=payload,follow_redirects=False)
    assert draft.status_code==303
    event_id=draft.headers["location"].split("/")[-1]
    assert client.post(f"/admin/events/{event_id}/state",data={"action":"publish"},follow_redirects=False).status_code==303
    public=client.get(f"/events/{event_id}")
    assert "£21.00" in public.text and "£9.50" in public.text
    assert "Grandstand" not in public.text and "£15.00" not in public.text
    payload.update(home_team="New Unconfigured Club",title="New Club v Glentoran")
    empty=client.post("/admin/events",data=payload,follow_redirects=False)
    empty_id=empty.headers["location"].split("/")[-1]
    assert client.post(f"/admin/events/{empty_id}/state",data={"action":"publish"},follow_redirects=False).status_code==303
    public=client.get(f"/events/{empty_id}")
    assert "£15.00" in public.text and "£8.00" in public.text
    assert client.post(f"/admin/events/{empty_id}/publish",follow_redirects=False).status_code==303
    client.post("/admin/clubs/New%20Unconfigured%20Club/pricing",data={})
    assert client.post(f"/admin/events/{empty_id}/publish").status_code==409
