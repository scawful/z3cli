"""Backend skeletons for future multi-runtime z3cli support."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from z3cli.core.config import ModelConfig
from z3cli.protocol.lmstudio import (
    available_models_async,
    estimate_model_memory_async,
    ensure_model_loaded,
    loaded_models_async,
    normalize_loaded_model_entry,
    server_status_async,
    unload_model_async,
)


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

    async def list_loaded_model_details(self) -> list[dict[str, Any]]:
        ...

    async def unload_model(self, target: str = "", *, all_models: bool = False) -> dict[str, Any]:
        ...

    def resolve_request_model(
        self,
        target: ModelConfig,
        auto_load: bool,
        *,
        manual_load: bool = False,
    ) -> str:
        ...


class LMStudioBackend:
    name = "studio"

    def __init__(self, api_base: str, host: str, port: int):
        self.api_base = api_base.rstrip("/")
        self.host = host
        self.port = port

    async def check_connection(self) -> BackendStatus:
        try:
            status = await server_status_async(self.host, self.port)
        except Exception as exc:
            return BackendStatus(
                name=self.name, connected=False, detail=str(exc)[:120],
            )
        return BackendStatus(
            name=self.name,
            connected=bool(status.get("running")),
            detail=f"port={status.get('port', self.port)}",
        )

    async def list_loaded_models(self) -> list[str]:
        names: list[str] = []
        try:
            entries = await loaded_models_async(self.host, self.port)
        except Exception:
            return names
        for entry in entries:
            for key in ("identifier", "modelKey", "name", "model", "id"):
                value = entry.get(key)
                if isinstance(value, str) and value not in names:
                    names.append(value)
        return names

    async def list_loaded_model_details(self) -> list[dict[str, Any]]:
        try:
            available_entries = await available_models_async(self.host, self.port)
            loaded_entries = await loaded_models_async(self.host, self.port)
        except Exception:
            return []
        lookup: dict[str, dict[str, Any]] = {}
        for entry in available_entries:
            if not isinstance(entry, dict):
                continue
            for key in ("modelKey", "indexedModelIdentifier", "path", "displayName"):
                value = entry.get(key)
                if isinstance(value, str) and value:
                    lookup.setdefault(value, entry)
        details = [
            normalize_loaded_model_entry(entry, available_lookup=lookup)
            for entry in loaded_entries
            if isinstance(entry, dict)
        ]
        estimates = await asyncio.gather(
            *[
                estimate_model_memory_async(
                    self.host,
                    self.port,
                    str(item.get("model_key", "") or item.get("identifier", "")),
                    context_length=int(item.get("context_length", 0) or 0),
                )
                for item in details
            ],
            return_exceptions=True,
        )
        for item, estimate in zip(details, estimates):
            if isinstance(estimate, dict):
                item.update(estimate)
        return details

    async def unload_model(self, target: str = "", *, all_models: bool = False) -> dict[str, Any]:
        return await unload_model_async(self.host, self.port, target, all_models=all_models)

    def resolve_request_model(
        self,
        target: ModelConfig,
        auto_load: bool,
        *,
        manual_load: bool = False,
    ) -> str:
        return ensure_model_loaded(
            alias=target.name,
            model_id=target.model_id,
            host=self.host,
            port=self.port,
            auto_load=auto_load,
            allow_auto_load=target.allow_auto_load,
            manual_load=manual_load,
            context_length=target.lmstudio_context_length or None,
            parallel=target.lmstudio_parallel or None,
            gpu=target.lmstudio_gpu or None,
            ttl=target.lmstudio_ttl or None,
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

    async def list_loaded_model_details(self) -> list[dict[str, Any]]:
        names = await self.list_loaded_models()
        return [{"identifier": name, "model_key": name, "display_name": name, "status": "loaded"} for name in names]

    async def unload_model(self, target: str = "", *, all_models: bool = False) -> dict[str, Any]:
        del target, all_models
        raise RuntimeError("/unload is only available on the studio backend.")

    def resolve_request_model(
        self,
        target: ModelConfig,
        auto_load: bool,
        *,
        manual_load: bool = False,
    ) -> str:
        del auto_load, manual_load
        return self.model or target.model_id or target.name
