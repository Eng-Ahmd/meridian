"""Thin client for any OpenAI-compatible chat completions endpoint."""
from __future__ import annotations

import httpx

from meridian.core.config import Settings
from meridian.core.logging import get_logger

log = get_logger("meridian.llm")


class LlmClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        s = self.settings
        return s.llm_provider == "openai-compatible" and bool(s.llm_base_url and s.llm_model)

    def complete(self, *, system: str, user: str, max_tokens: int = 300) -> str | None:
        """Return the model text, or None on any failure. Callers must fall back
        to the deterministic template so a dead LLM never breaks a run."""
        if not self.enabled:
            return None
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        try:
            resp = httpx.post(
                url,
                headers=headers,
                json={
                    "model": self.settings.llm_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.2,
                },
                timeout=20.0,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 - LLM failure is non-fatal by design
            log.warning("LLM call failed, using template fallback: %s", exc)
            return None
