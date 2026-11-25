# LLM Chatbot with Key Failover and Response Caching

A full-stack AI chatbot application built with **FastAPI** (Python) and **React**, featuring automatic API key failover, response caching via LiteLLM, and per-request token tracking. All conversation history is stored in **SQLite**.

---

## 1. Live URLs

| Tier     | URL                              |
| -------- | -------------------------------- |
| Frontend | `<your-frontend-url>`            |
| Backend  | `<your-backend-url>`             |

---

## 2. Run Locally

### With Docker (recommended)

```bash
# 1. Clone the repository
git clone <repo-url>
cd lyftr-chatbot

# 2. Copy the env file and add your API keys
cp .env.example .env
# Edit .env and set LLM_API_KEYS with at least 2 keys

# 3. Start everything
make up
```

- Frontend: http://localhost:3000
- Backend:  http://localhost:8000

To stop:

```bash
make down
```

### Without Docker

**Backend:**

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set environment variables
export LLM_API_KEYS="key1,key2"
export DATABASE_URL="sqlite:///app.db"
export ALLOWED_ORIGINS="http://localhost:3000"
export ENABLE_FAILURE_SIMULATION="true"

uvicorn main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install

# Set the backend URL
echo "VITE_API_URL=http://localhost:8000" > .env

npm run dev
```

**Run backend tests:**

```bash
cd backend
pytest tests/ -v
```

---

## 3. Design Decisions

### Key Fallback

API keys are loaded from `LLM_API_KEYS` (comma-separated) and assigned sequential IDs (`key_1`, `key_2`, ...). On each chat request the backend tries keys in order. If a key returns HTTP 429, a quota error, or a 5xx status, it is skipped and the next key is tried. The number of skipped keys is returned as `fallback_attempts`. When every key fails, the endpoint returns `503 {"detail": "all providers unavailable"}` and the failed message is **not** stored in history.

The `X-Simulate-Failure` header (enabled via `ENABLE_FAILURE_SIMULATION=true`) lets you trigger artificial failures per key per request for demo purposes.

### Caching

LiteLLM's built-in in-memory cache is enabled on startup. Additionally, the backend maintains its own cache keyed on `SHA-256(model + full messages JSON)`. When the same model + message sequence is seen again (even in a different session), the cached reply, token counts, and model name are returned instantly. The response reports `LLM_CACHE` with `key_id: null` and `fallback_attempts: 0`.

### SQLite Session Storage

All messages are stored in a single `messages` table with an index on `session_id`. Assistant messages carry a JSON `metadata` column with resolution source, model, latency, tokens, key ID, and fallback count. The database file lives under a Docker volume at `/data/app.db` so history survives container restarts. The schema is created automatically on first startup.

---

## 4. Verification

### Failover

```bash
# Key 1 fails with 429 → key 2 answers
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"demo","message":"Hello"}'
# → key_id: "key_2", fallback_attempts: 1

# All keys fail
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id":"demo2","message":"Hello"}'
# → 503 {"detail": "all providers unavailable"}
```

### Cache Hits

```bash
# First call → LIVE_INFERENCE
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"a","message":"What is 2+2?"}'

# Same first message in a new session → LLM_CACHE
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"b","message":"What is 2+2?"}'
```

### Per-Message Token Usage

Each AI reply in the UI shows metadata pills: `LIVE_INFERENCE` or `LLM_CACHE`, the model name, latency in milliseconds, and input/output token counts for that individual request.

### Session History

```bash
curl http://localhost:8000/sessions/demo/messages
```

---

## 5. Setup Used

- **Editor:** VS Code / Claude Code (Anthropic CLI)
- **AI Tools:** Claude (Anthropic) for code generation and review
- **Backend:** Python 3.12, FastAPI, LiteLLM, aiosqlite
- **Frontend:** React 18, Vite 5
- **Deployment:** Docker, docker-compose, multi-stage builds

---

## 6. Bonus Features

- **System prompt override:** An optional input lets you set a custom system prompt per session. The prompt persists for the session's lifetime.
- **Loading animation:** A three-dot pulse animation shows while the LLM is responding.
- **Keyboard shortcut:** Press Enter to send (Shift+Enter for newline).
- **Session badge:** The current session ID is shown in the header for transparency.
- **Graceful error display:** Network errors and API failures appear as styled error messages in the chat, never a blank screen.
