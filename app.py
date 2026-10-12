"""Outside Bingo - Flask app."""
import logging
import os
import re
import threading
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import database as db
from services import backboard_service as bb
from services import quest_service as qs
from services import serpapi_service as serp

load_dotenv()
log = logging.getLogger("outside_bingo")

ANON_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
RATE_LIMIT = 6          # adventures
RATE_WINDOW = 60        # seconds


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE_PATH=os.getenv("DATABASE_PATH", "outside_bingo.db"),
        SERPAPI_API_KEY=os.getenv("SERPAPI_API_KEY", ""),
        BACKBOARD_API_KEY=os.getenv("BACKBOARD_API_KEY", ""),
        BACKBOARD_BASE_URL=os.getenv("BACKBOARD_BASE_URL", "https://app.backboard.io/api"),
        BACKBOARD_LLM_PROVIDER=os.getenv("BACKBOARD_LLM_PROVIDER", "openrouter"),
        BACKBOARD_MODEL=os.getenv("BACKBOARD_MODEL", "meta-llama/llama-3.3-70b-instruct"),
        MAX_CONTENT_LENGTH=16 * 1024,
        SERP_SESSION=None,
        BACKBOARD_SESSION=None,
    )
    if config:
        app.config.update(config)
    db.init_db(app.config["DATABASE_PATH"])

    hits, hits_lock = {}, threading.Lock()

    def rate_limited(key):
        now = time.time()
        with hits_lock:
            recent = [t for t in hits.get(key, []) if now - t < RATE_WINDOW]
            if len(recent) >= RATE_LIMIT:
                hits[key] = recent
                return True
            recent.append(now)
            hits[key] = recent
            return False

    def path():
        return app.config["DATABASE_PATH"]

    def anon_id():
        value = request.headers.get("X-Anon-Id", "")
        return value.lower() if ANON_RE.match(value) else None

    def backboard_client():
        cfg = app.config
        if not cfg["BACKBOARD_API_KEY"]:
            return None
        kwargs = {"session": cfg["BACKBOARD_SESSION"]} if cfg["BACKBOARD_SESSION"] else {}
        return bb.BackboardClient(cfg["BACKBOARD_API_KEY"], cfg["BACKBOARD_BASE_URL"],
                                  cfg["BACKBOARD_LLM_PROVIDER"], cfg["BACKBOARD_MODEL"], **kwargs)

    def assistant_for(client, uid):
        assistant_id = db.get_assistant_id(path(), uid)
        if not assistant_id:
            assistant_id = client.create_assistant()
            db.set_assistant_id(path(), uid, assistant_id)
        return assistant_id

    def remember(uid, text):
        """Best-effort memory write; never breaks the user flow."""
        client = backboard_client()
        if not client:
            return
        try:
            client.remember(assistant_for(client, uid), text)
        except bb.BackboardError as exc:
            log.warning("Backboard memory write failed: %s", exc)

    def quest_payload(quest):
        done = set(quest["completed"])
        total_xp = sum(m["xp"] for m in quest["missions"])
        earned = sum(m["xp"] for m in quest["missions"] if m["id"] in done)
        return {**quest, "total_xp": total_xp, "earned_xp": earned,
                "finished": len(done) >= len(quest["missions"])}

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            activities=qs.ACTIVITIES, times=qs.TIMES, energies=qs.ENERGIES,
            live_search=bool(app.config["SERPAPI_API_KEY"]),
            live_ai=bool(app.config["BACKBOARD_API_KEY"]),
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok", serpapi_configured=bool(app.config["SERPAPI_API_KEY"]),
                       backboard_configured=bool(app.config["BACKBOARD_API_KEY"]))

    @app.get("/api/state")
    def state():
        uid = anon_id()
        if not uid:
            return jsonify(error="Missing or invalid anonymous id."), 400
        db.ensure_user(path(), uid)
        quest = db.latest_quest(path(), uid)
        return jsonify(progress=db.progress(path(), uid),
                       quest=quest_payload(quest) if quest else None)

    @app.post("/api/adventure")
    def adventure():
        uid = anon_id()
        if not uid:
            return jsonify(error="Missing or invalid anonymous id."), 400
        if rate_limited(uid):
            return jsonify(error="Slow down a little - try again in a minute."), 429
        try:
            prefs = qs.validate_preferences(request.get_json(silent=True))
        except qs.ValidationError as exc:
            return jsonify(error=str(exc)), 400
        db.ensure_user(path(), uid)
        notices = []

        # 1. Live destination discovery
        destination = {"source": "demo", "recommended": None, "alternatives": []}
        serp_key = app.config["SERPAPI_API_KEY"]
        if serp_key:
            try:
                kwargs = {"session": app.config["SERP_SESSION"]} if app.config["SERP_SESSION"] else {}
                places = serp.search_destinations(serp_key, prefs["location"], prefs["activity"], **kwargs)
                destination = {"source": "serpapi", "recommended": places[0] if places else None,
                               "alternatives": places[1:]}
                if not places:
                    notices.append("SerpApi found no outdoor destinations for that location. "
                                   "Try a bigger nearby town.")
            except serp.SerpApiError as exc:
                destination["source"] = "error"
                notices.append(f"Live destination search unavailable: {exc}")
        else:
            notices.append("Demo mode: SERPAPI_API_KEY not set, so no live destinations were searched.")

        # 2. Backboard open-weight mission generation with memory
        recommended = destination["recommended"]
        missions, source = None, "fallback"
        client = backboard_client()
        if client:
            try:
                prompt = qs.build_prompt(prefs, recommended, db.recent_mission_titles(path(), uid))
                raw = client.generate(assistant_for(client, uid), prompt)
                missions = qs.parse_missions(raw)
                source = "backboard"
                remember(uid, "User preferences: likes %s walks, energy %s, %d minutes."
                         % (prefs["activity"], prefs["energy"], prefs["minutes"]))
            except bb.BackboardError as exc:
                notices.append(f"AI generation unavailable ({exc}). Showing a fallback card.")
            except qs.ValidationError:
                notices.append("The AI returned an invalid card, so a fallback card is shown.")
        else:
            source = "demo"
            notices.append("Demo mode: BACKBOARD_API_KEY not set. This card is a built-in demo, "
                           "not AI-generated.")
        if missions is None:
            missions = qs.fallback_missions(prefs["activity"])

        quest_id = db.create_quest(path(), uid, prefs, destination, missions, source)
        quest = db.get_quest(path(), uid, quest_id)
        return jsonify(quest=quest_payload(quest), notices=notices,
                       progress=db.progress(path(), uid))

    def owned_mission(quest_id, mission_id):
        uid = anon_id()
        if not uid:
            return None, None, (jsonify(error="Missing or invalid anonymous id."), 400)
        quest = db.get_quest(path(), uid, quest_id)
        if not quest or mission_id not in {m["id"] for m in quest["missions"]}:
            return None, None, (jsonify(error="Quest not found."), 404)
        return uid, quest, None

    @app.post("/api/quests/<int:quest_id>/missions/<mission_id>/complete")
    def complete(quest_id, mission_id):
        uid, quest, err = owned_mission(quest_id, mission_id)
        if err:
            return err
        body = request.get_json(silent=True) or {}
        completed = bool(body.get("completed", True))
        db.set_completion(path(), quest_id, mission_id, completed)
        if completed:
            title = next(m["title"] for m in quest["missions"] if m["id"] == mission_id)
            remember(uid, f"User self-reported completing the mission: {title}")
        updated = db.get_quest(path(), uid, quest_id)
        return jsonify(quest=quest_payload(updated), progress=db.progress(path(), uid))

    @app.post("/api/quests/<int:quest_id>/missions/<mission_id>/feedback")
    def feedback(quest_id, mission_id):
        uid, quest, err = owned_mission(quest_id, mission_id)
        if err:
            return err
        sentiment = (request.get_json(silent=True) or {}).get("sentiment")
        if sentiment not in ("like", "dislike"):
            return jsonify(error="Sentiment must be like or dislike."), 400
        title = next(m["title"] for m in quest["missions"] if m["id"] == mission_id)
        remember(uid, f"User {'enjoyed' if sentiment == 'like' else 'disliked'} the mission: {title}")
        return jsonify(ok=True)

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="Request too large."), 413

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "5000")))
