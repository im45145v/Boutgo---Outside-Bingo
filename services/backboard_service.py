"""Backboard integration: open-weight model generation plus per-user persistent memory.

Each anonymous browser gets its own Backboard assistant, so assistant memory is isolated per user.
Endpoints/fields follow Backboard's REST API (X-API-Key header, form-encoded messages).
"""
import requests

TIMEOUT = 60


class BackboardError(Exception):
    """Raised with a user-safe message; never includes the API key."""


class BackboardClient:
    def __init__(self, api_key, base_url, provider, model, session=requests):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.model = model
        self.session = session

    def _request(self, method, path, **kwargs):
        try:
            resp = self.session.request(
                method, f"{self.base_url}{path}",
                headers={"X-API-Key": self.api_key}, timeout=TIMEOUT, **kwargs,
            )
        except requests.Timeout:
            raise BackboardError("Backboard timed out.")
        except requests.RequestException:
            raise BackboardError("Could not reach Backboard.")
        if resp.status_code in (401, 403):
            raise BackboardError("Backboard rejected the API key.")
        if resp.status_code == 429:
            raise BackboardError("Backboard rate limit reached.")
        if resp.status_code >= 400:
            raise BackboardError(f"Backboard returned an error (HTTP {resp.status_code}).")
        try:
            return resp.json()
        except ValueError:
            raise BackboardError("Backboard returned an unreadable response.")

    def create_assistant(self):
        data = self._request("POST", "/assistants", json={
            "name": "Outside Bingo buddy",
            "system_prompt": (
                "You are a friendly outdoor adventure buddy. You remember the user's preferred "
                "activities, missions they enjoyed or disliked and quests they completed. "
                "Never store sensitive personal information. When asked for a bingo card, reply "
                "with strict JSON only."
            ),
        })
        assistant_id = data.get("assistant_id") or data.get("id")
        if not assistant_id:
            raise BackboardError("Backboard did not return an assistant id.")
        return str(assistant_id)

    def generate(self, assistant_id, prompt):
        """Create a thread, send the prompt with memory enabled; return the model's text."""
        thread = self._request("POST", f"/assistants/{assistant_id}/threads", json={})
        thread_id = thread.get("thread_id") or thread.get("id")
        if not thread_id:
            raise BackboardError("Backboard did not return a thread id.")
        data = self._request("POST", f"/threads/{thread_id}/messages", data={
            "content": prompt,
            "memory": "Auto",
            "stream": "false",
            "llm_provider": self.provider,
            "model_name": self.model,
        })
        content = data.get("content")
        if not content:
            raise BackboardError("Backboard returned an empty reply.")
        return content

    def remember(self, assistant_id, text):
        """Store an explicit memory (preferences, completions, feedback) for this user."""
        self._request("POST", f"/assistants/{assistant_id}/memories", json={"content": text})
