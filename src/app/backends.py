"""Backend skeletons for future multi-runtime z3cli support."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from core.config import ModelConfig
from core.provider import SSHOpenAIProvider, create_provider
from protocol.lmstudio import (
    available_models_async,
    estimate_model_memory_async,
    ensure_model_loaded,
    loaded_models,
    loaded_models_async,
    loaded_request_name,
    normalize_loaded_model_entry,
    resolve_available_model_id,
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

    def _openai_model_entries(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(base_url=self.api_base, timeout=5.0) as client:
                response = client.get("/models")
            if response.status_code != 200:
                return []
            data = response.json().get("data", [])
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        entries: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            entries.append({
                "identifier": model_id.strip(),
                "modelKey": model_id.strip(),
                "displayName": item.get("owned_by") if isinstance(item.get("owned_by"), str) else model_id.strip(),
            })
        return entries

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
        try:
            request_name = loaded_request_name(target.name, target.model_id, loaded_models(self.host, self.port))
            if request_name:
                return request_name
        except Exception:
            pass

        api_entries = self._openai_model_entries()
        if api_entries:
            api_model_id = resolve_available_model_id(target.model_id, api_entries)
            if api_model_id and api_model_id != target.model_id:
                return api_model_id
            target_model_keys = {target.name, target.model_id, *target.aliases}
            for entry in api_entries:
                identifier = entry.get("identifier")
                if isinstance(identifier, str) and identifier in target_model_keys:
                    return identifier
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

    def _uses_ssh_provider(self) -> bool:
        return self.api_base.startswith(("ssh://", "ssh+http://"))

    async def check_connection(self) -> BackendStatus:
        if self._uses_ssh_provider():
            provider = create_provider("llamacpp", api_base=self.api_base, timeout=10.0)
            try:
                connected = await provider.check_connection()
                return BackendStatus(name=self.name, connected=connected, detail=self.api_base)
            except Exception as exc:
                return BackendStatus(name=self.name, connected=False, detail=f"{self.api_base} ({exc})")
            finally:
                await provider.close()
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
        if self._uses_ssh_provider():
            provider = create_provider("llamacpp", api_base=self.api_base, timeout=10.0)
            try:
                if isinstance(provider, SSHOpenAIProvider):
                    return await provider.list_model_ids()
                return []
            except Exception:
                return []
            finally:
                await provider.close()
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
