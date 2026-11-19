"""Optional LLM fallback for jobs the matcher barely covers.

The client reads LLM_API_KEY and LLM_MODEL from config. With no key, build_llm
returns a disabled client and extract returns nothing. Tests inject a transport
so this module never calls the network unless that default transport is used.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol
from urllib.parse import quote

import requests

from config import Settings
from extraction.skills import SkillHit

log = logging.getLogger(__name__)

LLM_CONFIDENCE = Decimal("0.6500")
_MAX_JOB_CHARS = 8_000
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class SkillLLM(Protocol):
    """Something that can propose taxonomy skills for one job."""

    enabled: bool

    def extract(
        self,
        title: str,
        description: str | None,
        allowed: dict[str, str],
    ) -> list[SkillHit]:
        """Return catalog skills. allowed maps a lowercased phrase to its canonical name."""


class DisabledSkillLLM:
    """Used when LLM_API_KEY is unset. extract is a no-op."""

    enabled = False

    def extract(
        self,
        title: str,
        description: str | None,
        allowed: dict[str, str],
    ) -> list[SkillHit]:
        return []


class GeminiSkillLLM:
    """Ask Gemini for catalog skill names. Failures return an empty list."""

    enabled = True

    def __init__(
        self,
        api_key: str,
        model: str,
        transport: Callable[[str], str] | None = None,
    ):
        self._api_key = api_key
        self._model = model or "gemini-1.5-flash"
        self._transport = transport or self._post

    def extract(
        self,
        title: str,
        description: str | None,
        allowed: dict[str, str],
    ) -> list[SkillHit]:
        prompt = _prompt(title, description, allowed)
        try:
            raw = self._transport(prompt)
        except Exception as exc:
            log.warning("LLM skill fallback failed (%s)", type(exc).__name__)
            return []
        return parse_skill_response(raw, allowed)

    def _post(self, prompt: str) -> str:
        url = _GEMINI_URL.format(model=quote(self._model, safe=""))
        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0},
            },
            timeout=30,
        )
        response.raise_for_status()
        return _text_from_gemini(response.json())


def build_llm(settings: Settings) -> SkillLLM:
    """Return a live client only when the API key is non-blank."""
    key = (settings.llm_api_key or "").strip()
    if not key:
        return DisabledSkillLLM()
    return GeminiSkillLLM(api_key=key, model=settings.llm_model)


def parse_skill_response(raw: str, allowed: dict[str, str]) -> list[SkillHit]:
    """Keep catalog names from a JSON object or list. Unknown names are dropped."""
    payload = _load_json(raw)
    if isinstance(payload, dict):
        items = payload.get("skills", [])
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    if not isinstance(items, list):
        return []
    hits: list[SkillHit] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        canonical = allowed.get(" ".join(item.lower().split()))
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        hits.append(SkillHit(name=canonical, method="llm", confidence=LLM_CONFIDENCE))
    return hits


def _prompt(title: str, description: str | None, allowed: dict[str, str]) -> str:
    names = ", ".join(sorted(set(allowed.values())))
    body = f"{title or ''}\n\n{description or ''}".strip()
    if len(body) > _MAX_JOB_CHARS:
        body = body[:_MAX_JOB_CHARS]
    return (
        "Extract technical skills from the job posting. "
        'Return JSON only, shaped as {"skills": ["Name"]}. '
        "Use names from the catalog exactly. Return an empty list when none apply.\n\n"
        f"Catalog:\n{names}\n\n"
        f"Job:\n{body}"
    )


def _load_json(raw: str):
    text = raw.strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None


def _text_from_gemini(body: dict) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts:
        return ""
    return parts[0].get("text") or ""
