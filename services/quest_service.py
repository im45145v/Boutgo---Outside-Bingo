"""Input validation, prompt construction, and mission-output validation."""
import json
import re

TIMES = (10, 20, 30)
ACTIVITIES = ("nature", "birds", "plants", "photography", "mindful walking", "surprise me")
ENERGIES = ("chill", "curious", "adventurous")
MISSION_COUNT = 5
MAX_TITLE = 60
MAX_TEXT = 200
MIN_XP, MAX_XP = 5, 50

SAFETY_RULES = (
    "No equipment purchases, no entering private property, no disturbing or touching wildlife, "
    "no climbing or other risky actions, no tasting plants, and never ask the user to identify "
    "a species with certainty. Tasks must be doable on foot in public space."
)

_TAG_RE = re.compile(r"<[^>]*>")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ValidationError(ValueError):
    pass


def clean_text(value, limit):
    """Strip markup and control characters, collapse whitespace, cap length."""
    text = _CTRL_RE.sub("", _TAG_RE.sub("", str(value)))
    text = text.replace("<", "").replace(">", "")
    return " ".join(text.split())[:limit]


def validate_preferences(data):
    if not isinstance(data, dict):
        raise ValidationError("Invalid request body.")
    location = clean_text(data.get("location", ""), 80)
    if len(location) < 2:
        raise ValidationError("Please enter a city or locality.")
    try:
        minutes = int(data.get("minutes"))
    except (TypeError, ValueError):
        raise ValidationError("Choose 10, 20 or 30 minutes.")
    if minutes not in TIMES:
        raise ValidationError("Choose 10, 20 or 30 minutes.")
    activity = str(data.get("activity", "")).lower()
    if activity not in ACTIVITIES:
        raise ValidationError("Choose one of the listed adventure types.")
    energy = str(data.get("energy", "")).lower()
    if energy not in ENERGIES:
        raise ValidationError("Choose chill, curious or adventurous.")
    return {"location": location, "minutes": minutes, "activity": activity, "energy": energy}


def build_prompt(prefs, destination, recent_titles=()):
    dest_lines = "No verified destination was found; keep tasks generic to any public outdoor space."
    if destination:
        parts = [f"Name: {destination['name']}"]
        if destination.get("address"):
            parts.append(f"Address: {destination['address']}")
        if destination.get("rating") is not None:
            parts.append(f"Rating: {destination['rating']}")
        if destination.get("type"):
            parts.append(f"Type: {destination['type']}")
        dest_lines = "Verified destination (from live search):\n" + "\n".join(parts)
    recent = "; ".join(recent_titles) if recent_titles else "none"
    return (
        "Create a personalised outdoor bingo card.\n"
        f"{dest_lines}\n"
        f"Locality: {prefs['location']}\n"
        f"Time available: {prefs['minutes']} minutes\n"
        f"Preferred adventure: {prefs['activity']}\n"
        f"Energy level: {prefs['energy']}\n"
        f"Recent missions to avoid repeating: {recent}\n"
        "Use anything you remember about this user's likes, dislikes and completed quests.\n"
        f"Safety rules: {SAFETY_RULES}\n"
        f"Return ONLY a JSON object, no markdown, of the form "
        '{"missions":[{"id":"m1","title":"...","instruction":"...","xp":10}]} '
        f"with exactly {MISSION_COUNT} missions. Titles max {MAX_TITLE} characters, "
        f"instructions max {MAX_TEXT} characters, xp an integer between {MIN_XP} and {MAX_XP}. "
        "Do not invent facts about the destination beyond those listed."
    )


def _extract_json(raw):
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValidationError("Model output was not JSON.")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise ValidationError("Model output was not valid JSON.")


def parse_missions(raw):
    """Validate model output; return exactly five sanitised missions or raise."""
    data = _extract_json(raw)
    missions = data.get("missions") if isinstance(data, dict) else data
    if not isinstance(missions, list) or len(missions) != MISSION_COUNT:
        raise ValidationError(f"Expected exactly {MISSION_COUNT} missions.")
    result = []
    for index, item in enumerate(missions, start=1):
        if not isinstance(item, dict):
            raise ValidationError("Mission entries must be objects.")
        title = clean_text(item.get("title", ""), MAX_TITLE)
        instruction = clean_text(item.get("instruction", item.get("description", "")), MAX_TEXT)
        xp = item.get("xp")
        if isinstance(xp, bool) or not isinstance(xp, (int, float)):
            raise ValidationError("Mission xp must be a number.")
        if not title or not instruction:
            raise ValidationError("Mission needs a title and instruction.")
        result.append({
            "id": f"m{index}",
            "title": title,
            "instruction": instruction,
            "xp": max(MIN_XP, min(MAX_XP, int(xp))),
        })
    return result


_FALLBACK = {
    "nature": [
        ("Shades of green", "Find three different shades of green and notice how they differ.", 10),
        ("Odd leaf", "Find a leaf with an unusual shape. Look, don't pick.", 10),
        ("Through the crack", "Spot something growing through a crack in the pavement.", 15),
        ("One quiet minute", "Stand or sit still for one minute and observe your surroundings.", 15),
        ("Sky check", "Look up and describe the shape of one cloud or patch of sky.", 10),
    ],
    "birds": [
        ("Listen up", "Pause for one minute and listen for a bird call.", 10),
        ("Spot a bird", "Spot any bird, from a distance, without disturbing it.", 15),
        ("Perch spotting", "Notice where birds choose to perch.", 10),
        ("Sound count", "Count how many different sounds you can hear.", 10),
        ("Feather-free zone", "Find a tree with branches that look like a good bird lookout.", 10),
    ],
    "plants": [
        ("Leaf edges", "Find a leaf with smooth edges and one with jagged edges.", 10),
        ("Tiny flower", "Find the smallest flower you can see. Look, don't pick.", 15),
        ("Bark texture", "Gently look at the bark of a tree and describe its pattern.", 10),
        ("Shades of green", "Find three different shades of green.", 10),
        ("Growing up", "Find a plant growing somewhere surprising.", 15),
    ],
    "photography": [
        ("Frame a leaf", "Take a photo of a leaf against the sky.", 10),
        ("Shadow play", "Photograph an interesting shadow.", 10),
        ("Smallest thing", "Take a close-up of the tiniest interesting thing you can find.", 15),
        ("Lines", "Photograph a path or line that leads the eye.", 10),
        ("Colour hunt", "Photograph something in the colour of your choice.", 10),
    ],
    "mindful walking": [
        ("Slow steps", "Walk slowly for one minute, noticing each footstep.", 10),
        ("Five senses", "Name one thing you see, hear, feel and smell.", 15),
        ("One quiet minute", "Sit quietly and observe your surroundings for one minute.", 15),
        ("Breathe", "Take five slow breaths of fresh air.", 10),
        ("Soft sounds", "Find the quietest sound you can hear.", 10),
    ],
}
_FALLBACK["surprise me"] = [_FALLBACK["nature"][0], _FALLBACK["birds"][0], _FALLBACK["plants"][2],
                            _FALLBACK["mindful walking"][2], _FALLBACK["photography"][1]]


def fallback_missions(activity):
    """Static fallback card. Callers must label it as a fallback, never as AI output."""
    rows = _FALLBACK.get(activity, _FALLBACK["nature"])
    return [{"id": f"m{i}", "title": t, "instruction": d, "xp": x}
            for i, (t, d, x) in enumerate(rows, start=1)]
