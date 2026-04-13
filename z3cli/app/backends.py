"""Backend skeletons for future multi-runtime z3cli support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from z3cli.core.config import ModelConfig
from z3cli.protocol.lmstudio import ensure_model_loaded, loaded_models, server_status


DEFAULT_LLAMACPP_API_BASE = "http://127.0.0.1:8080/v1"


@dataclass
class BackendStatus:
    name: str
    connected: bool
    detail: str = ""


class ChatBackend(Protocol):
    name: str
    api_base: str

    async def check_connection(self) -> BackendStatus:
        ...

    async def list_loaded_models(self) -> list[str]:
        ...

    def resolve_request_model(self, target: ModelConfig, auto_load: bool) -> str:
        ...


class LMStudioBackend:
    name = "studio"

    def __init__(self, api_base: str, host: str, port: int):
        self.api_base = api_base.rstrip("/")
        self.host = host
        self.port = port

    async def check_connection(self) -> BackendStatus:
        status = server_status(self.host, self.port)
        return BackendStatus(
            name=self.name,
            connected=bool(status.get("running")),
            detail=f"port={status.get('port', self.port)}",
        )

    async def list_loaded_models(self) -> list[str]:
        names: list[str] = []
        for entry in loaded_models(self.host, self.port):
            for key in ("identifier", "modelKey", "name", "model", "id"):
                value = entry.get(key)
                if isinstance(value, str) and value not in names:
                    names.append(value)
        return names

    def resolve_request_model(self, target: ModelConfig, auto_load: bool) -> str:
        return ensure_model_loaded(
            alias=target.name,
            model_id=target.model_id,
            host=self.host,
            port=self.port,
            auto_load=auto_load,
        )


class LlamaCppBackend:
    name = "llamacpp"

    def __init__(self, api_base: str = DEFAULT_LLAMACPP_API_BASE, model: str = ""):
        self.api_base = api_base.rstrip("/")
        self.model = model

    async def check_connection(self) -> BackendStatus:
        try:
            async with httpx.AsyncClient(base_url=self.api_base, timeout=5.0) as client:
                response = await client.get("/models")
            connected = response.status_code == 200
            return BackendStatus(name=self.name, connected=connected, detail=self.api_base)
        except Exception as exc:
            detail = str(exc).strip()
            if detail:
                detail = f"{self.api_base} ({detail})"
            else:
                detail = self.api_base
            return BackendStatus(name=self.name, connected=False, detail=detail)

    async def list_loaded_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(base_url=self.api_base, timeout=5.0) as client:
                response = await client.get("/models")
            if response.status_code != 200:
                return []
            return [item["id"] for item in response.json().get("data", []) if isinstance(item.get("id"), str)]
        except Exception:
            return []

    def resolve_request_model(self, target: ModelConfig, auto_load: bool) -> str:
        del auto_load
        return self.model or target.model_id or target.name
