"""SQLite storage for anonymous users, quests and completion state."""
import json
import sqlite3
from datetime import datetime, timezone


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path):
    with connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                anon_id TEXT PRIMARY KEY,
                assistant_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anon_id TEXT NOT NULL REFERENCES users(anon_id),
                created_at TEXT NOT NULL,
                location TEXT NOT NULL,
                minutes INTEGER NOT NULL,
                activity TEXT NOT NULL,
                energy TEXT NOT NULL,
                destination TEXT,
                missions TEXT NOT NULL,
                mission_source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS completions (
                quest_id INTEGER NOT NULL REFERENCES quests(id),
                mission_id TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (quest_id, mission_id)
            );
            """
        )


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_user(path, anon_id):
    with connect(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (anon_id, created_at) VALUES (?, ?)",
            (anon_id, _now()),
        )


def get_assistant_id(path, anon_id):
    with connect(path) as conn:
        row = conn.execute(
            "SELECT assistant_id FROM users WHERE anon_id = ?", (anon_id,)
        ).fetchone()
    return row["assistant_id"] if row else None


def set_assistant_id(path, anon_id, assistant_id):
    with connect(path) as conn:
        conn.execute(
            "UPDATE users SET assistant_id = ? WHERE anon_id = ?",
            (assistant_id, anon_id),
        )


def create_quest(path, anon_id, prefs, destination, missions, source):
    with connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO quests (anon_id, created_at, location, minutes, activity,
               energy, destination, missions, mission_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                anon_id, _now(), prefs["location"], prefs["minutes"],
                prefs["activity"], prefs["energy"],
                json.dumps(destination) if destination else None,
                json.dumps(missions), source,
            ),
        )
        return cur.lastrowid


def get_quest(path, anon_id, quest_id):
    """Return a quest owned by anon_id (with completed ids) or None."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM quests WHERE id = ? AND anon_id = ?", (quest_id, anon_id)
        ).fetchone()
        if not row:
            return None
        done = [
            r["mission_id"]
            for r in conn.execute(
                "SELECT mission_id FROM completions WHERE quest_id = ?", (quest_id,)
            )
        ]
    return {
        "id": row["id"],
        "location": row["location"],
        "minutes": row["minutes"],
        "activity": row["activity"],
        "energy": row["energy"],
        "destination": json.loads(row["destination"]) if row["destination"] else None,
        "missions": json.loads(row["missions"]),
        "mission_source": row["mission_source"],
        "completed": done,
    }


def set_completion(path, quest_id, mission_id, completed):
    with connect(path) as conn:
        if completed:
            conn.execute(
                "INSERT OR IGNORE INTO completions (quest_id, mission_id, completed_at) VALUES (?, ?, ?)",
                (quest_id, mission_id, _now()),
            )
        else:
            conn.execute(
                "DELETE FROM completions WHERE quest_id = ? AND mission_id = ?",
                (quest_id, mission_id),
            )


def latest_quest(path, anon_id):
    with connect(path) as conn:
        row = conn.execute(
            "SELECT id FROM quests WHERE anon_id = ? ORDER BY id DESC LIMIT 1", (anon_id,)
        ).fetchone()
    return get_quest(path, anon_id, row["id"]) if row else None


def recent_mission_titles(path, anon_id, limit=15):
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT missions FROM quests WHERE anon_id = ? ORDER BY id DESC LIMIT 3",
            (anon_id,),
        ).fetchall()
    titles = []
    for r in rows:
        titles.extend(m.get("title", "") for m in json.loads(r["missions"]))
    return titles[:limit]


def progress(path, anon_id):
    """Total XP, completed missions and finished quests for this user."""
    with connect(path) as conn:
        rows = conn.execute(
            """SELECT q.id, q.missions, GROUP_CONCAT(c.mission_id) AS done
               FROM quests q LEFT JOIN completions c ON c.quest_id = q.id
               WHERE q.anon_id = ? GROUP BY q.id""",
            (anon_id,),
        ).fetchall()
    xp = missions_done = quests_done = 0
    for r in rows:
        done = set((r["done"] or "").split(",")) - {""}
        missions = json.loads(r["missions"])
        for m in missions:
            if m["id"] in done:
                xp += m["xp"]
                missions_done += 1
        if missions and len(done) >= len(missions):
            quests_done += 1
    return {"xp": xp, "missions_completed": missions_done, "quests_completed": quests_done}
