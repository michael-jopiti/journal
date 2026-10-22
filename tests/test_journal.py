from datetime import date

import pytest

from journal import create_app
from journal.storage import Store, clean_entry, parse_date

DAY = date(2026, 10, 23)


@pytest.fixture
def client(tmp_path):
    return create_app(tmp_path).test_client()


def test_clean_entry_coerces_untrusted_input():
    raw = {
        "color": "nope",
        "evil": 1,
        "sections": {
            "check_in": {"mood": 9, "energy": True, "stress": 3},
            "gratitude": {"items": ["a", 5, "c", "extra"]},
            "day": {"what_happened": 42},
        },
    }
    e = clean_entry(DAY, raw)
    assert e["color"] == "paper"
    assert "evil" not in e
    assert e["sections"]["check_in"] == {"mood": None, "energy": None, "stress": 3}
    assert e["sections"]["gratitude"]["items"] == ["a", "", "c"]
    assert e["sections"]["day"]["what_happened"] == ""


def test_store_round_trip_and_listing(tmp_path):
    store = Store(tmp_path)
    assert store.load(DAY)["sections"]["check_in"]["mood"] is None
    store.save(DAY, {"color": "yellow", "sections": {"check_in": {"mood": 4}}})
    assert store.load(DAY)["color"] == "yellow"
    assert store.load(DAY)["sections"]["check_in"]["mood"] == 4
    (tmp_path / "notes.json").write_text("{}")  # stray file is ignored
    assert store.days() == [DAY]
    assert [e["date"] for e in store.entries()] == ["2026-10-23"]
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("bad", ["2026-13-01", "20261023", "2026-1-1", "abc"])
def test_parse_date_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_date(bad)


def test_api_and_pages(client):
    assert client.get("/today").status_code == 302
    assert client.get("/").status_code == 200
    assert client.get("/?range=year").status_code == 200
    assert client.get("/?range=bogus").status_code == 200
    assert client.get("/2026-10-23").status_code == 200
    assert client.get("/not-a-date").status_code == 404
    assert client.put("/api/entries/2026-10-23", data="x").status_code == 400
    r = client.put("/api/entries/2026-10-23", json={"color": "black"})
    assert r.get_json()["color"] == "black"
    assert client.get("/api/entries").get_json()[0]["date"] == "2026-10-23"
    assert b"data-color=\"black\"" in client.get("/2026-10-23").data


def test_charts_average_and_bucket(tmp_path):
    from journal.insights import RANGES_BY_ID, build_charts

    store = Store(tmp_path)
    store.save(date(2026, 10, 22), {"sections": {"check_in": {"mood": 2}}})
    store.save(date(2026, 10, 23), {"sections": {"check_in": {"mood": 4}}})
    entries = list(store.entries())
    mood = next(c for c in build_charts(entries, RANGES_BY_ID["week"], DAY) if c["id"] == "mood")
    assert mood["average"] == 3 and mood["count"] == 2 and len(mood["dots"]) == 2
    year = next(c for c in build_charts(entries, RANGES_BY_ID["year"], DAY) if c["id"] == "mood")
    assert year["count"] == 2 and year["path"]
    energy = next(c for c in build_charts(entries, RANGES_BY_ID["week"], DAY) if c["id"] == "energy")
    assert energy["average"] is None and energy["path"] == ""


def test_shutdown_requires_header(client):
    assert client.post("/api/shutdown").status_code == 403


PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16


def test_image_upload_serve_and_entry_reference(client):
    from io import BytesIO

    up = client.post("/api/entries/2026-10-23/images", data={"file": (BytesIO(PNG), "x.svg")})
    assert up.status_code == 201
    name = up.get_json()["file"]
    assert name.endswith(".png")  # extension comes from the bytes, not the filename
    got = client.get(f"/images/2026-10-23/{name}")
    assert got.status_code == 200 and got.data == PNG
    assert got.headers["X-Content-Type-Options"] == "nosniff"

    photos = [{"file": name, "caption": "Lake"}, {"file": "../../etc/passwd", "caption": "bad"}]
    saved = client.put("/api/entries/2026-10-23", json={"sections": {"pictures": {"photos": photos}}})
    assert saved.get_json()["sections"]["pictures"]["photos"] == [{"file": name, "caption": "Lake"}]
    assert client.get("/2026-10-23").status_code == 200


def test_image_upload_rejects_non_images_and_bad_paths(client):
    from io import BytesIO

    bad = client.post("/api/entries/2026-10-23/images", data={"file": (BytesIO(b"<svg onload=x>"), "a.png")})
    assert bad.status_code == 415
    assert client.post("/api/entries/2026-10-23/images").status_code == 400
    assert client.get("/images/2026-10-23/..%2Fsecret").status_code == 404


def test_numbers_and_tags_are_validated():
    e = clean_entry(
        DAY,
        {
            "sections": {
                "habits": {"sleep_hours": 7.5, "alcohol": -1, "exercise": float("nan")},
                "day": {"emotions": ["sad", "calm", "bogus", {"x": 1}]},
            }
        },
    )
    assert e["sections"]["habits"] == {"sleep_hours": 7.5, "alcohol": None, "exercise": None}
    assert e["sections"]["day"]["emotions"] == ["calm", "sad"]  # option order, unknowns dropped
    assert clean_entry(DAY, {"sections": {"habits": {"alcohol": 0}}})["sections"]["habits"]["alcohol"] == 0


def test_streaks_and_gaps(tmp_path):
    from datetime import timedelta

    from journal.insights import RANGES_BY_ID, day_strip, streaks

    days = {DAY, DAY - timedelta(1), DAY - timedelta(2), DAY - timedelta(5)}
    assert streaks(days, DAY) == (3, 3)
    assert streaks(days - {DAY}, DAY) == (2, 2)  # empty today keeps the streak alive
    assert streaks(set(), DAY) == (0, 0)
    store = Store(tmp_path)
    for d in days:
        store.save(d, {})
    strip, missed = day_strip(list(store.entries()), RANGES_BY_ID["week"], DAY, min(days))
    assert len(strip) == 7 and missed == 2  # 2026-10-20 and 21 are gaps


def test_number_chart_scales_to_data(tmp_path):
    from journal.insights import RANGES_BY_ID, build_charts

    store = Store(tmp_path)
    store.save(DAY, {"sections": {"habits": {"sleep_hours": 6}}})
    sleep = next(c for c in build_charts(list(store.entries()), RANGES_BY_ID["week"], DAY) if c["id"] == "sleep_hours")
    assert sleep["average"] == 6 and sleep["axis"] == "0 – 6 h"


def test_search_and_export(client):
    client.put(
        "/api/entries/2026-10-23",
        json={"sections": {"day": {"what_happened": "Walked by the LAKE today", "emotions": ["calm"]}, "habits": {"sleep_hours": 8}}},
    )
    page = client.get("/search?q=lake").data
    assert b"<mark>LAKE</mark>" in page and b"2026-10-23" in page
    assert b"1 day found" in client.get("/search?q=calm").data
    assert b"0 days found" in client.get("/search?q=zzz").data
    assert client.get("/search").status_code == 200
    sheet = client.get("/2026-10-23/export").data
    assert b"Walked by the LAKE" in sheet and b"8.0 h" in sheet or b"8 h" in sheet
    assert b"Thought record" not in sheet  # empty sections are skipped
    assert client.get("/nope/export").status_code == 404
