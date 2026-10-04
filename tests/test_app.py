from starlette.middleware.sessions import SessionMiddleware

from gateline.main import app


def test_session_middleware_wraps_request_middleware():
    assert app.user_middleware[0].cls is SessionMiddleware
