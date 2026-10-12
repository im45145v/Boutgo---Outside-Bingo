# Outside Bingo 🌿
*Less scrolling. More strolling.* Enter a locality, time, energy and activity; get a five-task outdoor bingo card based on a real destination.

Built for Hacktoberfest ("Touch Grass") for the **SerpApi** and **Backboard** tracks. Flask + vanilla JS + SQLite.

## What uses what
- **SerpApi** (`services/serpapi_service.py`): Google Maps engine (`engine=google_maps`) finds parks, gardens and trails for the user's locality. Name, address, rating and a Google Maps link come only from the returned data. The recommended place is passed into the prompt. Requests are server-side.
- **Backboard** (`services/backboard_service.py`): each anonymous browser id gets its own Backboard assistant (isolating memory between users). Missions are generated through Backboard with `memory: "Auto"`, and enjoyed/disliked/completed missions are also written as explicit memories. Recent mission titles stored in SQLite are added to the prompt to avoid repeats.
- **Open-weight model**: configured by `BACKBOARD_LLM_PROVIDER` / `BACKBOARD_MODEL`; default `meta-llama/llama-3.3-70b-instruct` via the `openrouter` provider. **This default has not been run against a live Backboard account** (no credentials were available while building); confirm it is available to you and change it if needed. Open-weight models let you swap models and compare outputs, since the prompt and validation are model-agnostic.
- **Validation**: model output must be JSON with exactly five missions; text is stripped of markup, XP is clamped, and the browser renders it with `textContent` only.

## Failure behaviour
- No `SERPAPI_API_KEY`: demo mode, no destination is searched or invented. Bad key, rate limit, timeout, network error or empty results: a notice is shown and the card is still generated without a destination.
- No `BACKBOARD_API_KEY`: a built-in card labelled **"demo card (not AI)"**. Backboard error or malformed output: a card labelled **"fallback card (not AI)"** plus a notice.
- Completion is self-reported; nothing verifies real-world activity.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then add SERPAPI_API_KEY and BACKBOARD_API_KEY
python app.py                      # http://localhost:5000
```
Keys: SerpApi at https://serpapi.com/manage-api-key, Backboard at https://app.backboard.io. Leave them blank to use demo mode. Run tests with `pytest`. Health check: `GET /health`.

## Arduino UNO Q (Debian)
The app uses only pure-Python packages, binds to `HOST` (default `0.0.0.0`) and `PORT` (default `5000`).
```bash
scp -r Boutgo---Outside-Bingo arduino@<board-ip>:~/outside-bingo
ssh arduino@<board-ip>
cd ~/outside-bingo && sudo apt install -y python3-venv
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && nano .env
python app.py                      # open http://<board-ip>:5000
```
**Not tested on an actual UNO Q.** The built-in Flask server is for demos, not hardened production use.

## Status
- Implemented and covered by automated tests with mocked network: validation, SerpApi parsing/errors/empty results, Backboard request flow, output validation and fallback, SQLite progress, per-user isolation.
- Verified manually: server starts, `/health`, and the demo-mode API flow.
- Not tested: live SerpApi calls, live Backboard calls (model name, and the `/assistants/{id}/memories` endpoint used for explicit memory writes, which is best-effort), real memory-driven personalisation, UNO Q deployment, browser/mobile rendering.
- Anonymous identity is a random id in `localStorage`; it is not authentication.
