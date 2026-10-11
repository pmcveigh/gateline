from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from gateline.clubs import LEAGUES
from gateline.database import Base, get_db
from gateline.main import app
from gateline.models import Event, Venue


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
        now = datetime.now(timezone.utc)
        for home, away, competition in (
            ("Cliftonville", "Linfield", "NIFL Premiership 2026/27"),
            ("Cliftonville Ladies", "Linfield Women", "NIFL Women’s Premiership 2026"),
            ("Queen’s University", "Ards", "NIFL Championship 2026/27"),
            ("Limavady United", "Bangor", "NIFL Premiership 2026/27"),
        ):
            db.add(Event(title=f"{home} v {away}", home_team=home, away_team=away,
                         competition=competition, venue_id=venue.id, published=True,
                         starts_at=now + timedelta(days=1), sales_open=now,
                         sales_close=now + timedelta(days=1)))
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
    assert [len(clubs) for clubs in LEAGUES.values()] == [11, 16, 12, 8]
    response = client.get("/")
    assert response.status_code == 200
    for league in LEAGUES:
        assert league.replace("'", "&#39;") in response.text
    assert "Ballyclare Comrades" in response.text
    assert "Limavady United" in response.text  # Retain existing clubs outside the supplied list.
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
