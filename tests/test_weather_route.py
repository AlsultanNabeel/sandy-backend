"""GET /api/weather: no city of the user's and none asked for means asking, never a
default (it used to be one city in Egypt for everybody)."""
import mongomock


def test_the_weather_route_with_no_city_anywhere_asks_for_one(monkeypatch):
    from app.api.auth_handlers import make_token
    from app.api.server import create_app

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    c = create_app(mongo_db=mongomock.MongoClient().db).test_client()
    r = c.get("/api/weather", headers={"Authorization": f"Bearer {make_token('user', user_id='u1')}"})
    assert r.status_code == 400 and r.get_json()["error"] == "city_required"
