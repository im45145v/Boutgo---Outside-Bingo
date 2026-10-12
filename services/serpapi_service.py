"""Destination discovery through SerpApi's Google Maps engine (server-side only)."""
from urllib.parse import quote_plus

import requests

SEARCH_URL = "https://serpapi.com/search.json"
TIMEOUT = 15

QUERY_BY_ACTIVITY = {
    "nature": "parks and nature trails",
    "birds": "bird watching parks and wetlands",
    "plants": "botanical gardens and parks",
    "photography": "scenic parks and gardens",
    "mindful walking": "quiet parks and gardens",
    "surprise me": "parks gardens and public green spaces",
}


class SerpApiError(Exception):
    """Raised with a user-safe message; never includes the API key."""


def build_query(location, activity):
    return f"{QUERY_BY_ACTIVITY.get(activity, 'parks')} in {location}"


def parse_results(payload, limit=4):
    """Convert a SerpApi response into destination dicts using only returned fields."""
    places = []
    for item in (payload or {}).get("local_results") or []:
        name = item.get("title")
        if not name:
            continue
        place_id = item.get("place_id")
        gps = item.get("gps_coordinates") or {}
        if place_id:
            link = ("https://www.google.com/maps/search/?api=1&query="
                    f"{quote_plus(name)}&query_place_id={quote_plus(place_id)}")
        elif gps.get("latitude") is not None and gps.get("longitude") is not None:
            link = f"https://www.google.com/maps/search/?api=1&query={gps['latitude']},{gps['longitude']}"
        else:
            link = f"https://www.google.com/maps/search/?api=1&query={quote_plus(name)}"
        rating = item.get("rating")
        places.append({
            "name": str(name),
            "address": item.get("address"),
            "rating": rating if isinstance(rating, (int, float)) else None,
            "reviews": item.get("reviews") if isinstance(item.get("reviews"), int) else None,
            "type": item.get("type"),
            "link": link,
        })
        if len(places) >= limit:
            break
    return places


def search_destinations(api_key, location, activity, session=requests):
    """Return a list of destinations (possibly empty). Raises SerpApiError on failure."""
    params = {
        "engine": "google_maps",
        "q": build_query(location, activity),
        "type": "search",
        "hl": "en",
        "api_key": api_key,
    }
    try:
        resp = session.get(SEARCH_URL, params=params, timeout=TIMEOUT)
    except requests.Timeout:
        raise SerpApiError("The destination search timed out.")
    except requests.RequestException:
        raise SerpApiError("Could not reach SerpApi. Check your connection.")
    if resp.status_code in (401, 403):
        raise SerpApiError("SerpApi rejected the API key.")
    if resp.status_code == 429:
        raise SerpApiError("SerpApi rate limit or quota reached.")
    if resp.status_code != 200:
        raise SerpApiError(f"SerpApi returned an error (HTTP {resp.status_code}).")
    try:
        payload = resp.json()
    except ValueError:
        raise SerpApiError("SerpApi returned an unreadable response.")
    if payload.get("error") and not payload.get("local_results"):
        msg = str(payload["error"])
        if "hasn't returned any results" in msg or "no results" in msg.lower():
            return []
        if "api key" in msg.lower():
            raise SerpApiError("SerpApi rejected the API key.")
        raise SerpApiError("SerpApi reported an error.")
    return parse_results(payload)
