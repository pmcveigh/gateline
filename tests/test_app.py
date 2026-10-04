from starlette.middleware.sessions import SessionMiddleware

from gateline.main import app


def test_session_middleware_wraps_request_middleware():
    assert app.user_middleware[0].cls is SessionMiddleware


def test_club_filter_accepts_empty_venue():
    home_route = next(route for route in app.routes if getattr(route, "path", None) == "/")
    venue_query = next(param for param in home_route.dependant.query_params if param.name == "venue")
    venue, errors = venue_query.validate("", {}, loc=("query", "venue"))

    assert venue is None
    assert errors == []
