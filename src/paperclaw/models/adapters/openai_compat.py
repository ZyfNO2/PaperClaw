from __future__ import annotations

import json
import os
import platform
import socket
import urllib.error
import urllib.request

from paperclaw.models.base import ModelTurn


class OpenAICompatibleModel:
    """Small stdlib adapter for an OpenAI-compatible chat completions endpoint."""

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout: float = 60) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAICompatibleModel":
        required = {name: os.getenv(name) for name in ("PAPERCLAW_API_KEY", "PAPERCLAW_BASE_URL", "PAPERCLAW_MODEL")}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing environment variables: {', '.join(missing)}")
        timeout = float(os.getenv("PAPERCLAW_TIMEOUT_SECONDS", "120"))
        return cls(api_key=required["PAPERCLAW_API_KEY"], base_url=required["PAPERCLAW_BASE_URL"], model=required["PAPERCLAW_MODEL"], timeout=timeout)

    def complete(self, prompt: str) -> ModelTurn:
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"PaperClaw/0.0.1 ({platform.system()} {platform.release()})",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model request failed with HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise RuntimeError(f"model request timed out or failed to connect within {self.timeout:g}s") from exc
        message = data["choices"][0]["message"]
        return ModelTurn(content=message.get("content", ""), reasoning=message.get("reasoning_content", ""))
