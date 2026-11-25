import os
import json
import time
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional

import litellm
from litellm.caching import Cache

from database import init_db, save_message, get_session_messages, session_exists

LLM_API_KEYS: list[str] = []
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini/gemini-2.0-flash")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///app.db")
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
ENABLE_FAILURE_SIMULATION = (
    os.environ.get("ENABLE_FAILURE_SIMULATION", "false").lower() == "true"
)
DEFAULT_SYSTEM_PROMPT = os.environ.get(
    "DEFAULT_SYSTEM_PROMPT", "You are a helpful assistant."
)

litellm.cache = Cache(type="local")

_response_cache: dict[str, dict] = {}
_session_system_prompts: dict[str, str] = {}


def _get_db_path() -> str:
    return DATABASE_URL.replace("sqlite:///", "", 1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global LLM_API_KEYS
    raw = os.environ.get("LLM_API_KEYS", "")
    LLM_API_KEYS = [k.strip() for k in raw.split(",") if k.strip()]
    await init_db(_get_db_path())
    yield


app = FastAPI(title="LLM Chatbot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500, content={"detail": "internal server error"}
    )


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str
    system_prompt: Optional[str] = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > 4000:
            raise ValueError("message must be at most 4000 characters")
        return v


def _make_cache_key(model: str, messages: list[dict]) -> str:
    data = json.dumps({"model": model, "messages": messages}, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


def _parse_simulate_failure(header_value: str) -> dict[str, int]:
    failures: dict[str, int] = {}
    for pair in header_value.split(","):
        pair = pair.strip()
        if "=" in pair:
            key_id, status = pair.split("=", 1)
            try:
                failures[key_id.strip()] = int(status.strip())
            except ValueError:
                continue
    return failures


def _call_llm_sync(
    messages: list[dict], simulated_failures: dict[str, int] | None = None
) -> dict:
    model = LLM_MODEL
    cache_key = _make_cache_key(model, messages)

    if cache_key in _response_cache:
        cached = _response_cache[cache_key]
        return {
            "reply": cached["reply"],
            "resolution_source": "LLM_CACHE",
            "model": cached["model"],
            "input_tokens": cached["input_tokens"],
            "output_tokens": cached["output_tokens"],
            "key_id": None,
            "fallback_attempts": 0,
        }

    fallback_attempts = 0

    for i, key in enumerate(LLM_API_KEYS):
        key_id = f"key_{i + 1}"

        if simulated_failures:
            sim_status = simulated_failures.get(key_id) or simulated_failures.get("*")
            if sim_status:
                fallback_attempts += 1
                continue

        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                api_key=key,
                num_retries=0,
            )

            reply = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

            _response_cache[cache_key] = {
                "reply": reply,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

            return {
                "reply": reply,
                "resolution_source": "LIVE_INFERENCE",
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "key_id": key_id,
                "fallback_attempts": fallback_attempts,
            }
        except Exception as e:
            status_code = getattr(e, "status_code", 0)
            err_str = str(e).lower()
            if (
                status_code in (429, 500, 502, 503)
                or "quota" in err_str
                or "rate" in err_str
                or "resource" in err_str
            ):
                fallback_attempts += 1
                continue
            fallback_attempts += 1
            continue

    raise HTTPException(status_code=503, detail="all providers unavailable")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "keys_configured": len(LLM_API_KEYS),
        "cache_enabled": True,
    }


@app.post("/chat")
async def chat(request: Request, body: ChatRequest):
    start_time = time.time()

    simulated_failures = None
    sim_header = request.headers.get("x-simulate-failure")
    if sim_header and ENABLE_FAILURE_SIMULATION:
        simulated_failures = _parse_simulate_failure(sim_header)

    if body.system_prompt is not None:
        _session_system_prompts[body.session_id] = body.system_prompt
    system_prompt = _session_system_prompts.get(
        body.session_id, DEFAULT_SYSTEM_PROMPT
    )

    db_path = _get_db_path()
    history = await get_session_messages(db_path, body.session_id)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": body.message})

    result = _call_llm_sync(messages, simulated_failures)

    latency_ms = int((time.time() - start_time) * 1000)

    metadata = {
        "resolution_source": result["resolution_source"],
        "model": result["model"],
        "latency_ms": latency_ms,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "key_id": result["key_id"],
        "fallback_attempts": result["fallback_attempts"],
    }

    await save_message(db_path, body.session_id, "user", body.message)
    await save_message(
        db_path, body.session_id, "assistant", result["reply"], metadata
    )

    return {
        "session_id": body.session_id,
        "reply": result["reply"],
        "metadata": metadata,
    }


@app.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    db_path = _get_db_path()

    if not await session_exists(db_path, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    history = await get_session_messages(db_path, session_id)

    messages = []
    for msg in history:
        entry: dict = {"role": msg["role"], "content": msg["content"]}
        if msg["role"] == "assistant" and msg.get("metadata"):
            entry["metadata"] = msg["metadata"]
        messages.append(entry)

    return {"session_id": session_id, "messages": messages}
