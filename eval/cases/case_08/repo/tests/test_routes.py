from src.api.routes import ROUTES


def test_routes_count():
    assert len(ROUTES) == 4
