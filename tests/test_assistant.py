"""Sky guide endpoint: Gemini is replaced by an httpx MockTransport (no key, no network)."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from spherex_ingest.api import app, get_assistant, get_assistant_limiter
from spherex_ingest.assistant import (
    AssistantDisabled,
    AssistantRateLimited,
    AssistantTurn,
    AssistantUpstreamError,
    GeminiAssistant,
    SlidingWindowLimiter,
    build_system_prompt,
    parse_gemini_response,
)


def _gemini_payload(reply: str, mood: str) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "private reasoning", "thought": True},
                        {"text": json.dumps({"reply": reply, "mood": mood})},
                    ],
                }
            }
        ]
    }


def _assistant(handler) -> GeminiAssistant:
    return GeminiAssistant(
        api_key="test-key",
        model="gemini-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def overrides():
    yield app.dependency_overrides
    app.dependency_overrides.clear()


def test_request_carries_key_in_header_and_history(overrides) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_gemini_payload("RA is like longitude.", "explaining"))

    overrides[get_assistant] = lambda: _assistant(handler)
    overrides[get_assistant_limiter] = lambda: SlidingWindowLimiter(10, 10)
    response = TestClient(app).post(
        "/api/v1/assistant",
        json={
            "message": "What are right ascension and declination?",
            "history": [{"role": "user", "text": "Hi"}, {"role": "model", "text": "Hello!"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "RA is like longitude.",
        "mood": "explaining",
        "model": "gemini-test",
    }
    assert seen["url"].endswith("/models/gemini-test:generateContent")
    assert "key=" not in seen["url"], "the key must travel in a header, not in the URL"
    assert seen["key"] == "test-key"
    roles = [c["role"] for c in seen["body"]["contents"]]
    assert roles == ["user", "model", "user"]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_without_key_the_endpoint_says_disabled(overrides) -> None:
    overrides[get_assistant] = lambda: None
    response = TestClient(app).post("/api/v1/assistant", json={"message": "Hello"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "assistant_disabled"
    with pytest.raises(AssistantDisabled):
        GeminiAssistant(api_key="")


def test_upstream_error_is_sanitized(overrides) -> None:
    overrides[get_assistant] = lambda: _assistant(lambda r: httpx.Response(500, text="boom"))
    overrides[get_assistant_limiter] = lambda: SlidingWindowLimiter(10, 10)
    response = TestClient(app).post("/api/v1/assistant", json={"message": "Hello"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "assistant_unavailable"
    assert "boom" not in response.text


def test_message_length_and_rate_limit(overrides) -> None:
    ok = _assistant(lambda r: httpx.Response(200, json=_gemini_payload("Hi!", "happy")))
    limiter = SlidingWindowLimiter(per_client=2, global_limit=100)
    overrides[get_assistant] = lambda: ok
    overrides[get_assistant_limiter] = lambda: limiter
    client = TestClient(app)

    assert client.post("/api/v1/assistant", json={"message": "x" * 501}).status_code == 422
    assert client.post("/api/v1/assistant", json={"message": "Hi"}).status_code == 200
    assert client.post("/api/v1/assistant", json={"message": "Hi"}).status_code == 200
    third = client.post("/api/v1/assistant", json={"message": "Hi"})
    assert third.status_code == 429
    assert "Retry-After" in third.headers


def test_limiter_window_frees_up() -> None:
    limiter = SlidingWindowLimiter(per_client=1, global_limit=5, window=60)
    limiter.check("a", now=0)
    limiter.check("b", now=1)
    with pytest.raises(AssistantRateLimited):
        limiter.check("a", now=30)
    limiter.check("a", now=61)


def test_parse_falls_back_on_unknown_mood_and_rejects_bad_json() -> None:
    reply = parse_gemini_response(_gemini_payload("Wow!", "dancing"), "m")
    assert reply.mood == "explaining"
    with pytest.raises(AssistantUpstreamError):
        parse_gemini_response({"candidates": []}, "m")
    bad = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    with pytest.raises(AssistantUpstreamError):
        parse_gemini_response(bad, "m")


def test_system_prompt_lists_the_five_test_objects() -> None:
    prompt = build_system_prompt()
    for name in ("Barnard's Star", "Epsilon Indi B", "RW Aurigae", "R Draconis"):
        assert name in prompt
    assert "269.4485" in prompt
    assert AssistantTurn(role="user", text="x").role == "user"


def test_env_file_fills_missing_variables_only(tmp_path, monkeypatch) -> None:
    from spherex_ingest.assistant import load_env_file

    env = tmp_path / ".env"
    env.write_text(
        '# comment\nGEMINI_API_KEY="from-file"\nexport GEMINI_MODEL=m-file\nASSISTANT_X=keep\n\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("ASSISTANT_X", "from-shell")
    load_env_file(env)
    import os

    assert os.environ["GEMINI_API_KEY"] == "from-file"
    assert os.environ["GEMINI_MODEL"] == "m-file"
    assert os.environ["ASSISTANT_X"] == "from-shell", "the shell wins over the file"
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("GEMINI_MODEL")


def test_daily_limit_resets_with_the_quota_day() -> None:
    limiter = SlidingWindowLimiter(per_client=100, global_limit=100, daily_limit=2)
    limiter.check("a", now=0, day="2026-11-15")
    limiter.check("b", now=1, day="2026-11-15")
    with pytest.raises(AssistantRateLimited) as info:
        limiter.check("c", now=2, day="2026-11-15")
    assert info.value.daily
    limiter.check("c", now=3, day="2026-11-16")


def test_gemini_quota_exhausted_becomes_a_friendly_429(overrides) -> None:
    quota = {"error": {"status": "RESOURCE_EXHAUSTED"}}
    exhausted = _assistant(lambda r: httpx.Response(429, json=quota))
    overrides[get_assistant] = lambda: exhausted
    overrides[get_assistant_limiter] = lambda: SlidingWindowLimiter(10, 10)
    response = TestClient(app).post("/api/v1/assistant", json={"message": "Hi"})
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "rate_limited"


def test_daily_limit_reaches_the_page_as_its_own_code(overrides) -> None:
    ok = _assistant(lambda r: httpx.Response(200, json=_gemini_payload("Hi!", "happy")))
    limiter = SlidingWindowLimiter(per_client=10, global_limit=10, daily_limit=1)
    overrides[get_assistant] = lambda: ok
    overrides[get_assistant_limiter] = lambda: limiter
    client = TestClient(app)
    assert client.post("/api/v1/assistant", json={"message": "Hi"}).status_code == 200
    second = client.post("/api/v1/assistant", json={"message": "Hi"})
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "daily_limit"
