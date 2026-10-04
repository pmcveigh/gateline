from pathlib import Path

from starlette.middleware.sessions import SessionMiddleware

from gateline.main import app
from gateline.main import build_calendar
from gateline import __version__


def test_session_middleware_wraps_request_middleware():
    assert app.user_middleware[0].cls is SessionMiddleware


def test_club_filter_accepts_empty_venue():
    home_route = next(route for route in app.routes if getattr(route, "path", None) == "/")
    venue_query = next(param for param in home_route.dependant.query_params if param.name == "venue")
    venue, errors = venue_query.validate("", {}, loc=("query", "venue"))

    assert venue is None
    assert errors == []


def test_home_uses_club_grid_and_expanded_calendar():
    template = Path("gateline/templates/home.html").read_text()

    assert 'class="club-grid"' in template
    assert '<select name="club">' not in template
    assert '<details class="day" open>' in template


def test_calendar_orders_events_from_soonest_to_furthest():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    later = SimpleNamespace(starts_at=datetime(2027, 3, 2, 15, tzinfo=timezone.utc))
    soonest = SimpleNamespace(starts_at=datetime(2026, 11, 1, 19, 45, tzinfo=timezone.utc))

    calendar = build_calendar([later, soonest])

    assert [event for _, events in calendar for event in events] == [soonest, later]


def test_v018_admin_and_camera_interfaces_are_discoverable():
    admin = Path("gateline/templates/admin.html").read_text()
    gate = Path("gateline/templates/gate.html").read_text()

    assert __version__ == "0.1.8"
    assert "/admin/events/new" in admin
    assert "Take QR photo" in gate
    assert "getUserMedia" in gate
    assert "BarcodeDetector" in gate
    assert "replaceChildren" in gate
