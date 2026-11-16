"""Sky guide: a friendly educational assistant backed by the Google Gemini API.

The browser never sees the Gemini API key. The static viewer posts the visitor's message to
``POST /api/v1/assistant``; this module adds the guide's instructions, calls Gemini's
``generateContent`` REST method with ``httpx`` and returns a short reply plus a ``mood`` that the
page uses to pick the animated character's reaction.

Configuration (environment variables, or a ``.env`` file in the directory the API starts from;
a variable already set in the environment wins over the file):

- ``GEMINI_API_KEY``: required. Without it the endpoint answers 503 ``assistant_disabled``.
- ``GEMINI_MODEL``: optional, defaults to ``DEFAULT_GEMINI_MODEL``.
- ``ASSISTANT_PER_CLIENT_PER_MINUTE`` / ``ASSISTANT_GLOBAL_PER_MINUTE`` /
  ``ASSISTANT_DAILY_LIMIT``: request caps, kept below the Gemini free tier so the key is never
  blocked for overuse.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx

from spherex_ingest.domain.targets import BENCHMARK_TARGETS

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"

# The reactions the character can show after an answer. The page adds two of its own while it
# works: "idle" (nothing asked yet) and "thinking" (waiting for this endpoint).
MOODS: tuple[str, ...] = ("happy", "explaining", "excited", "curious", "sorry")
Mood = Literal["happy", "explaining", "excited", "curious", "sorry"]

MAX_MESSAGE_CHARS = 500
MAX_HISTORY_TURNS = 10
MAX_REPLY_CHARS = 2000

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": "The answer shown to the visitor, plain text, at most about 120 words.",
        },
        "mood": {
            "type": "string",
            "enum": list(MOODS),
            "description": "The guide's facial reaction while giving this answer.",
        },
    },
    "required": ["reply", "mood"],
}


def _benchmark_lines() -> str:
    lines = []
    for target in BENCHMARK_TARGETS.values():
        lines.append(
            f"- {target.name}: RA {target.ra_deg:.4f} deg, Dec {target.dec_deg:+.4f} deg "
            f"(epoch J{target.ref_epoch_jyear:g})"
        )
    return "\n".join(lines)


def build_system_prompt() -> str:
    """Instructions for the guide. The five test objects come from the curated target table."""
    return f"""\
You are the friendly animated sky guide of STARPHERE, a public web tool by team Bortle Cero for the
NASA Space Apps Challenge 2026. On STARPHERE a visitor picks a spot in the sky (a test object, an
object name, or Right Ascension and Declination) and watches NASA SPHEREx infrared images of that
spot "blink" through time, to notice stars that move or change brightness.

Your audience is curious people, not astronomers. Explain simply, with everyday analogies, in short
sentences and active voice. Keep each answer under about 120 words. Answer in the language the
visitor writes in. Plain text only: no Markdown, no lists with symbols, no links.

How to use the tool, if asked: in tab "01 / Your patch of sky" choose a test object, or type an
object name (it is looked up in SIMBAD), or type RA and Dec, then press "Go there".

Coordinates you may state with confidence (Gaia DR3 or literature values used by the tool):
{_benchmark_lines()}

For any other object, give only rounded, well-known coordinates if you are sure, say they are
approximate, and suggest typing the name in the "Object name" field, which looks up the exact
position in SIMBAD. Never invent precise numbers. If you do not know something, say so.

Stay on astronomy, the sky, SPHEREx, NASA missions and how to use this tool. Politely steer other
topics back to the sky. Never ask for personal information. Content must be suitable for all ages.

Pick a mood for your face: "happy" for greetings and thanks, "explaining" for most answers,
"excited" for amazing facts, "curious" when you ask the visitor something back, "sorry" when you
cannot help or must decline."""


@dataclass(frozen=True)
class AssistantTurn:
    role: Literal["user", "model"]
    text: str


@dataclass(frozen=True)
class AssistantReply:
    reply: str
    mood: Mood
    model: str


class AssistantDisabled(RuntimeError):
    """No Gemini API key is configured."""


class AssistantUpstreamError(RuntimeError):
    """Gemini failed or returned something unusable."""


class AssistantRateLimited(RuntimeError):
    """Our own caps were reached, or Gemini said the key's free quota is used up (HTTP 429)."""

    def __init__(self, retry_after_seconds: int, daily: bool = False) -> None:
        super().__init__("Too many assistant requests")
        self.retry_after_seconds = retry_after_seconds
        self.daily = daily


def _quota_day() -> str:
    """The Gemini free tier resets its daily quota at midnight Pacific time; count days the same."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # no time zone data in the image: UTC is close enough
        return datetime.now(UTC).date().isoformat()


class SlidingWindowLimiter:
    """At most ``per_client`` requests per client and ``global_limit`` overall in ``window`` s,
    and ``daily_limit`` per quota day.

    In memory, per instance: enough to keep a public demo inside the Gemini free tier.
    """

    def __init__(
        self,
        per_client: int,
        global_limit: int,
        window: float = 60.0,
        daily_limit: int | None = None,
    ) -> None:
        self._per_client = per_client
        self._global = global_limit
        self._window = window
        self._daily_limit = daily_limit
        self._day = ""
        self._day_count = 0
        self._lock = threading.Lock()
        self._all: deque[float] = deque()
        self._clients: dict[str, deque[float]] = {}

    def check(self, client_id: str, now: float | None = None, day: str | None = None) -> None:
        now = time.monotonic() if now is None else now
        cutoff = now - self._window
        with self._lock:
            if self._daily_limit is not None:
                day = day or _quota_day()
                if day != self._day:
                    self._day, self._day_count = day, 0
                if self._day_count >= self._daily_limit:
                    raise AssistantRateLimited(3600, daily=True)
            while self._all and self._all[0] <= cutoff:
                self._all.popleft()
            mine = self._clients.setdefault(client_id, deque())
            while mine and mine[0] <= cutoff:
                mine.popleft()
            for stamps, cap in ((self._all, self._global), (mine, self._per_client)):
                if len(stamps) >= cap:
                    raise AssistantRateLimited(max(1, int(stamps[0] - cutoff) + 1))
            self._all.append(now)
            mine.append(now)
            self._day_count += 1
            if len(self._clients) > 10_000:  # forget idle clients
                self._clients = {k: v for k, v in self._clients.items() if v}


class GeminiAssistant:
    """Calls Gemini ``generateContent`` and turns the JSON answer into an ``AssistantReply``."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        client: httpx.Client | None = None,
        timeout_seconds: float = 25.0,
    ) -> None:
        if not api_key:
            raise AssistantDisabled("GEMINI_API_KEY is not set")
        self._api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._system_prompt = build_system_prompt()

    def build_request(self, message: str, history: list[AssistantTurn]) -> dict:
        contents = [
            {"role": turn.role, "parts": [{"text": turn.text}]}
            for turn in history[-MAX_HISTORY_TURNS:]
        ]
        contents.append({"role": "user", "parts": [{"text": message}]})
        return {
            "systemInstruction": {"parts": [{"text": self._system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": _RESPONSE_SCHEMA,
                "maxOutputTokens": 800,
            },
        }

    def answer(self, message: str, history: list[AssistantTurn]) -> AssistantReply:
        body = self.build_request(message, history)
        try:
            response = self._client.post(
                GEMINI_ENDPOINT.format(model=self.model),
                headers={"x-goog-api-key": self._api_key},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise AssistantUpstreamError(f"Gemini request failed: {type(exc).__name__}") from exc
        if response.status_code == 429:
            # The free quota of the key is used up for now. Google does not charge for this; it
            # only refuses until the window resets, so tell the visitor to come back later.
            logger.warning("Gemini quota exhausted (HTTP 429) for model %s", self.model)
            raise AssistantRateLimited(60)
        if response.status_code != 200:
            # Never log the key; the body of an error response does not contain it.
            logger.warning("Gemini answered %s: %s", response.status_code, response.text[:300])
            raise AssistantUpstreamError(f"Gemini answered HTTP {response.status_code}")
        return parse_gemini_response(response.json(), self.model)


def parse_gemini_response(payload: dict, model: str) -> AssistantReply:
    """Read ``{"reply", "mood"}`` from a ``generateContent`` response, skipping thought parts."""
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AssistantUpstreamError("Gemini returned no answer") from exc
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    try:
        data = json.loads(text)
        reply = str(data["reply"]).strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise AssistantUpstreamError("Gemini answer was not the expected JSON") from exc
    if not reply:
        raise AssistantUpstreamError("Gemini answer was empty")
    mood = data.get("mood")
    if mood not in MOODS:
        mood = "explaining"
    return AssistantReply(reply=reply[:MAX_REPLY_CHARS], mood=mood, model=model)


def load_env_file(path: Path | str = ".env") -> None:
    """Copy ``NAME=value`` lines of a local ``.env`` file into ``os.environ``.

    Variables already set in the environment are kept. Blank lines and ``#`` comments are
    skipped; surrounding quotes are removed. The file is git-ignored and never enters the image.
    """
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and name not in os.environ:
            os.environ[name] = value


def assistant_from_environment() -> GeminiAssistant:
    """Build the assistant from ``GEMINI_API_KEY`` / ``GEMINI_MODEL``; raises if no key."""
    load_env_file()
    return GeminiAssistant(
        api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        model=os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
    )


def limiter_from_environment() -> SlidingWindowLimiter:
    """Defaults stay under the Gemini free tier: few requests a minute and a daily ceiling."""
    load_env_file()
    return SlidingWindowLimiter(
        per_client=int(os.environ.get("ASSISTANT_PER_CLIENT_PER_MINUTE", "4")),
        global_limit=int(os.environ.get("ASSISTANT_GLOBAL_PER_MINUTE", "10")),
        daily_limit=int(os.environ.get("ASSISTANT_DAILY_LIMIT", "200")),
    )
