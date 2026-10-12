import json
import uuid

import pytest

from app import create_app
from services import quest_service as qs
from services import serpapi_service as serp

GOOD = {"location": "Ranchi, Jharkhand", "minutes": 20, "activity": "birds", "energy": "chill"}


def mission_json(n=5):
    return json.dumps({"missions": [
        {"id": f"x{i}", "title": f"T{i}", "instruction": "Look <b>around</b>", "xp": 10} for i in range(n)]})


class FakeResp:
    def __init__(self, status=200, payload=None, text_payload=True):
        self.status_code, self._p = status, payload or {}

    def json(self):
        return self._p


class FakeSerp:
    def __init__(self, resp):
        self.resp = resp

    def get(self, *a, **k):
        return self.resp


class FakeBB:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if url.endswith("/assistants"):
            return FakeResp(200, {"assistant_id": "a1"})
        if url.endswith("/threads"):
            return FakeResp(200, {"thread_id": "t1"})
        if url.endswith("/messages"):
            return FakeResp(200, {"content": self.reply})
        return FakeResp(200, {})


@pytest.fixture
def make(tmp_path):
    def _make(**cfg):
        return create_app({"DATABASE_PATH": str(tmp_path / "t.db"), "SERPAPI_API_KEY": "",
                           "BACKBOARD_API_KEY": "", **cfg}).test_client()
    return _make


def hdr(uid=None):
    return {"X-Anon-Id": uid or str(uuid.uuid4())}


def test_parse_missions_valid_and_sanitised():
    ms = qs.parse_missions("```json\n" + mission_json() + "\n```")
    assert [m["id"] for m in ms] == ["m1", "m2", "m3", "m4", "m5"]
    assert "<" not in ms[0]["instruction"]


@pytest.mark.parametrize("raw", ["nope", mission_json(4), '{"missions":[1,2,3,4,5]}',
                                 json.dumps({"missions": [{"title": "a", "instruction": "b", "xp": "x"}] * 5})])
def test_parse_missions_rejects_bad(raw):
    with pytest.raises(qs.ValidationError):
        qs.parse_missions(raw)


def test_validate_preferences():
    assert qs.validate_preferences(GOOD)["minutes"] == 20
    with pytest.raises(qs.ValidationError):
        qs.validate_preferences({**GOOD, "minutes": 99})
    with pytest.raises(qs.ValidationError):
        qs.validate_preferences({**GOOD, "location": " "})


def test_parse_results_uses_only_returned_data():
    places = serp.parse_results({"local_results": [{"title": "Park", "address": "1 St", "rating": 4.5, "place_id": "p"}, {}]})
    assert len(places) == 1 and places[0]["rating"] == 4.5 and "query_place_id=p" in places[0]["link"]


def test_health_and_index(make):
    c = make()
    assert c.get("/health").get_json()["status"] == "ok"
    assert b"Your next adventure is just" in c.get("/").data


def test_demo_mode_is_labelled(make):
    c = make()
    r = c.post("/api/adventure", json=GOOD, headers=hdr())
    q = r.get_json()["quest"]
    assert r.status_code == 200 and q["mission_source"] == "demo"
    assert q["destination"]["source"] == "demo" and q["destination"]["recommended"] is None


def test_requires_anon_id_and_validates(make):
    c = make()
    assert c.post("/api/adventure", json=GOOD).status_code == 400
    assert c.post("/api/adventure", json={**GOOD, "energy": "x"}, headers=hdr()).status_code == 400


def test_live_flow_and_completion_isolated(make):
    serp_resp = FakeResp(200, {"local_results": [{"title": "Birdy Park", "address": "A", "place_id": "p"}]})
    bb = FakeBB(mission_json())
    c = make(SERPAPI_API_KEY="k", BACKBOARD_API_KEY="k", SERP_SESSION=FakeSerp(serp_resp), BACKBOARD_SESSION=bb)
    h = hdr()
    data = c.post("/api/adventure", json=GOOD, headers=h).get_json()
    q = data["quest"]
    assert q["mission_source"] == "backboard" and q["destination"]["recommended"]["name"] == "Birdy Park"
    sent = [k for (_, u, k) in bb.calls if u.endswith("/messages")][0]["data"]
    assert "Birdy Park" in sent["content"] and sent["memory"] == "Auto"
    r = c.post(f"/api/quests/{q['id']}/missions/m1/complete", json={"completed": True}, headers=h)
    assert r.get_json()["progress"]["xp"] == 10
    assert c.post(f"/api/quests/{q['id']}/missions/m1/complete", json={}, headers=hdr()).status_code == 404
    assert c.get("/api/state", headers=h).get_json()["quest"]["completed"] == ["m1"]
    for i in range(2, 6):
        r = c.post(f"/api/quests/{q['id']}/missions/m{i}/complete", json={}, headers=h)
    assert r.get_json()["quest"]["finished"] and r.get_json()["progress"]["quests_completed"] == 1


def test_assistants_are_per_user(make):
    bb = FakeBB(mission_json())
    c = make(BACKBOARD_API_KEY="k", BACKBOARD_SESSION=bb)
    c.post("/api/adventure", json=GOOD, headers=hdr())
    c.post("/api/adventure", json=GOOD, headers=hdr())
    assert sum(1 for (_, u, _k) in bb.calls if u.endswith("/assistants")) == 2


def test_malformed_model_output_falls_back(make):
    c = make(BACKBOARD_API_KEY="k", BACKBOARD_SESSION=FakeBB("not json"))
    q = c.post("/api/adventure", json=GOOD, headers=hdr()).get_json()
    assert q["quest"]["mission_source"] == "fallback" and len(q["quest"]["missions"]) == 5


@pytest.mark.parametrize("status,payload", [(401, {}), (429, {}), (200, {"error": "Google Maps hasn't returned any results for this query."})])
def test_serpapi_failures_and_empty(make, status, payload):
    c = make(SERPAPI_API_KEY="k", SERP_SESSION=FakeSerp(FakeResp(status, payload)))
    r = c.post("/api/adventure", json=GOOD, headers=hdr())
    assert r.status_code == 200
    d = r.get_json()
    assert d["quest"]["destination"]["recommended"] is None and d["notices"]
