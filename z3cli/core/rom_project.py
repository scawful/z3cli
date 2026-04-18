"""Session-scoped project coordinator for Zelda ROM-hacking tools.

A ``RomProject`` is the single source of truth for "where is everything"
during a z3cli session: workspace, ROM, config, symbol files, external
binaries, and the mesen2-oos socket path. Construction runs filesystem
discovery once; subsequent access is pure reads. To rediscover, build a
new ``RomProject`` via :meth:`discover`.

Discovery order for each field (first hit wins):
  1. Explicit override passed to :meth:`discover` (CLI arg).
  2. Environment variable.
  3. Workspace-relative config (``z3dk.toml``).
  4. Standard filesystem / PATH lookup.
  5. Known default.

ROM bytes are summarised by SHA-256 on demand (``rom_sha256``) so write
tools can invalidate bridge caches (schemas, label files, disasm output)
keyed on the previous checksum.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping


DEFAULT_WORKSPACE = Path.home() / "src/hobby/oracle-of-secrets"
DEFAULT_ROM = Path.home() / "src/hobby/roms/oracle.sfc"
DEFAULT_Z3DK_ROOT = Path.home() / "src/hobby/z3dk"
DEFAULT_YAZE_ROOT = Path.home() / "src/hobby/yaze"


def _coerce_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        path = value
    else:
        text = str(value).strip()
        if not text:
            return None
        path = Path(text)
    return path.expanduser().resolve()


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p and p.exists():
            return p
    return None


def _discover_executable(
    env_var: str,
    override: Path | None,
    *candidates: Path,
) -> Path | None:
    if override is not None and override.exists():
        return override
    env_val = os.environ.get(env_var)
    if env_val:
        p = Path(env_val).expanduser()
        if p.exists():
            return p.resolve()
    for cand in candidates:
        if cand.exists():
            return cand.resolve()
    return None


def _discover_mesen_socket(override: str | None = None) -> str | None:
    """Follow the mesen2-oos socket discovery order."""
    if override:
        return override
    env_val = os.environ.get("MESEN2_SOCKET_PATH")
    if env_val:
        return env_val
    tmp = Path("/tmp")
    # Status files contain JSON with a ``socketPath`` key.
    status_files = sorted(
        tmp.glob("mesen2-*.status"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    for sf in status_files:
        try:
            meta = json.loads(sf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sock = meta.get("socketPath")
        if isinstance(sock, str) and sock and Path(sock).exists():
            return sock
    # Fallback: newest bare .sock file.
    sock_files = sorted(
        tmp.glob("mesen2-*.sock"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    for sf in sock_files:
        if sf.exists():
            return str(sf)
    return None


@dataclass(frozen=True)
class RomProject:
    """Immutable coordinator for Zelda-hacking tool paths and runtime state.

    Construct via :meth:`discover`. All path fields are absolute when set;
    optional fields are ``None`` when not found. ``rom_sha256`` is lazily
    computed by :meth:`compute_rom_sha256`.
    """

    workspace: Path
    rom_path: Path | None
    z3dk_root: Path | None
    yaze_root: Path | None
    z3dk_toml: Path | None
    symbols_mlb: Path | None
    mesen_socket: str | None
    yaze_bin: Path | None
    z3asm_bin: Path | None
    z3disasm_bin: Path | None
    z3lsp_bin: Path | None
    # Free-form environment overrides we applied (for diagnostics/debug).
    overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def discover(
        cls,
        workspace: str | Path,
        *,
        rom_path: str | Path | None = None,
        z3dk_root: str | Path | None = None,
        yaze_root: str | Path | None = None,
        mesen_socket: str | None = None,
        z3dk_toml: str | Path | None = None,
        yaze_bin: str | Path | None = None,
        z3asm_bin: str | Path | None = None,
        z3disasm_bin: str | Path | None = None,
        z3lsp_bin: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "RomProject":
        """Build a RomProject by running filesystem discovery once."""
        # NOTE: *env* is accepted for tests; production uses os.environ.
        if env is not None:
            # Temporarily swap environ for the lookups.
            old_env = os.environ.copy()
            os.environ.clear()
            os.environ.update(env)
            try:
                return cls.discover(
                    workspace,
                    rom_path=rom_path,
                    z3dk_root=z3dk_root,
                    yaze_root=yaze_root,
                    mesen_socket=mesen_socket,
                    z3dk_toml=z3dk_toml,
                    yaze_bin=yaze_bin,
                    z3asm_bin=z3asm_bin,
                    z3disasm_bin=z3disasm_bin,
                    z3lsp_bin=z3lsp_bin,
                    env=None,
                )
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        ws = _coerce_path(workspace) or DEFAULT_WORKSPACE
        rom_override = _coerce_path(rom_path)
        z3dk_override = _coerce_path(z3dk_root)
        yaze_override = _coerce_path(yaze_root)
        z3dk_toml_override = _coerce_path(z3dk_toml)
        yaze_bin_override = _coerce_path(yaze_bin)
        z3asm_bin_override = _coerce_path(z3asm_bin)
        z3disasm_bin_override = _coerce_path(z3disasm_bin)
        z3lsp_bin_override = _coerce_path(z3lsp_bin)

        # z3dk / yaze roots
        z3dk_root_final = z3dk_override
        if z3dk_root_final is None:
            env_val = os.environ.get("Z3DK_ROOT")
            if env_val:
                candidate = Path(env_val).expanduser()
                if candidate.exists():
                    z3dk_root_final = candidate.resolve()
        if z3dk_root_final is None and DEFAULT_Z3DK_ROOT.exists():
            z3dk_root_final = DEFAULT_Z3DK_ROOT

        yaze_root_final = yaze_override
        if yaze_root_final is None:
            env_val = os.environ.get("YAZE_ROOT")
            if env_val:
                candidate = Path(env_val).expanduser()
                if candidate.exists():
                    yaze_root_final = candidate.resolve()
        if yaze_root_final is None and DEFAULT_YAZE_ROOT.exists():
            yaze_root_final = DEFAULT_YAZE_ROOT

        # z3dk.toml — workspace-first.
        z3dk_toml_final: Path | None = z3dk_toml_override
        if z3dk_toml_final is None:
            candidate = ws / "z3dk.toml"
            if candidate.exists():
                z3dk_toml_final = candidate.resolve()

        # ROM path
        rom_final = rom_override
        if rom_final is None:
            env_val = os.environ.get("Z3CLI_ROM")
            if env_val:
                candidate = Path(env_val).expanduser()
                if candidate.exists():
                    rom_final = candidate.resolve()
        if rom_final is None and DEFAULT_ROM.exists():
            rom_final = DEFAULT_ROM

        # Symbols.mlb — workspace build dir fallback.
        symbols_mlb: Path | None = None
        for cand in (
            ws / "build" / "symbols.mlb",
            ws / "symbols.mlb",
        ):
            if cand.exists():
                symbols_mlb = cand.resolve()
                break

        # Binaries
        z3asm = _discover_executable(
            "Z3ASM_PATH",
            z3asm_bin_override,
            *(_asm_candidates(z3dk_root_final)),
        )
        z3disasm = _discover_executable(
            "Z3DISASM_PATH",
            z3disasm_bin_override,
            *(_disasm_candidates(z3dk_root_final)),
        )
        z3lsp = _discover_executable(
            "Z3LSP_PATH",
            z3lsp_bin_override,
            *(_lsp_candidates(z3dk_root_final)),
        )
        yaze_b = _discover_executable(
            "YAZE_BIN",
            yaze_bin_override,
            *(_yaze_candidates(yaze_root_final)),
        )

        # PATH fallback
        if z3asm is None:
            found = shutil.which("z3asm")
            if found:
                z3asm = Path(found).resolve()
        if z3disasm is None:
            found = shutil.which("z3disasm")
            if found:
                z3disasm = Path(found).resolve()
        if z3lsp is None:
            found = shutil.which("z3lsp")
            if found:
                z3lsp = Path(found).resolve()
        if yaze_b is None:
            found = shutil.which("z3ed")
            if found:
                yaze_b = Path(found).resolve()

        # Mesen socket
        socket_path = _discover_mesen_socket(mesen_socket)

        overrides: dict[str, str] = {}
        if rom_override:
            overrides["rom_path"] = str(rom_override)
        if z3dk_override:
            overrides["z3dk_root"] = str(z3dk_override)
        if mesen_socket:
            overrides["mesen_socket"] = mesen_socket

        return cls(
            workspace=ws,
            rom_path=rom_final,
            z3dk_root=z3dk_root_final,
            yaze_root=yaze_root_final,
            z3dk_toml=z3dk_toml_final,
            symbols_mlb=symbols_mlb,
            mesen_socket=socket_path,
            yaze_bin=yaze_b,
            z3asm_bin=z3asm,
            z3disasm_bin=z3disasm,
            z3lsp_bin=z3lsp,
            overrides=overrides,
        )

    def compute_rom_sha256(self, max_bytes: int = 0) -> str | None:
        """Return the hex SHA-256 of the current ROM bytes, or None."""
        if self.rom_path is None or not self.rom_path.exists():
            return None
        h = hashlib.sha256()
        try:
            with self.rom_path.open("rb") as f:
                if max_bytes > 0:
                    h.update(f.read(max_bytes))
                else:
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        h.update(chunk)
        except OSError:
            return None
        return h.hexdigest()

    def diagnostics(self) -> dict[str, object]:
        """Return a small dict summarising what was discovered."""
        return {
            "workspace": str(self.workspace),
            "rom_path": str(self.rom_path) if self.rom_path else None,
            "z3dk_toml": str(self.z3dk_toml) if self.z3dk_toml else None,
            "symbols_mlb": str(self.symbols_mlb) if self.symbols_mlb else None,
            "mesen_socket": self.mesen_socket,
            "yaze_bin": str(self.yaze_bin) if self.yaze_bin else None,
            "z3asm_bin": str(self.z3asm_bin) if self.z3asm_bin else None,
            "z3disasm_bin": str(self.z3disasm_bin) if self.z3disasm_bin else None,
            "z3lsp_bin": str(self.z3lsp_bin) if self.z3lsp_bin else None,
            "overrides": dict(self.overrides),
        }

    def with_rom_path(self, rom_path: str | Path | None) -> "RomProject":
        """Return a copy of the project that targets a different ROM path."""
        return replace(self, rom_path=_coerce_path(rom_path))

    def with_mesen_socket(self, mesen_socket: str | None) -> "RomProject":
        """Return a copy of the project with a different active Mesen socket."""
        return replace(self, mesen_socket=mesen_socket or None)

    def refresh_mesen_socket(self) -> "RomProject":
        """Return a copy with socket discovery re-run against current env/tmp state."""
        return replace(self, mesen_socket=_discover_mesen_socket())

    def preferred_mesen_rom_path(self) -> Path | None:
        """Return the preferred ROM to launch in Mesen2.

        If the current target is an unpatched ROM and a patched sibling with an
        ``x`` suffix exists (for example ``oos168.sfc`` -> ``oos168x.sfc``),
        prefer the patched sibling for emulator work. Otherwise keep the current
        ROM when it exists. As a final workspace fallback, prefer
        ``workspace/Roms/oos168x.sfc`` when present.
        """
        candidates: list[Path] = []
        if self.rom_path is not None:
            current = self.rom_path.expanduser().resolve()
            stem = current.stem
            if stem and not stem.endswith("x"):
                patched = current.with_name(f"{stem}x{current.suffix}")
                candidates.append(patched)
            candidates.append(current)

        candidates.extend([
            self.workspace / "Roms" / "oos168x.sfc",
            self.workspace / "Roms" / "oos168.sfc",
        ])
        return _first_existing([candidate.resolve() for candidate in candidates])

    def mesen_launch_script(self) -> Path | None:
        """Return the canonical launcher script for isolated Mesen2 sessions."""
        return _first_existing([
            self.workspace / "Scripts" / "Mesen2" / "mesen2_launch_instance.sh",
            self.workspace / "Scripts" / "mesen2_launch_instance.sh",
        ])


def _asm_candidates(root: Path | None) -> list[Path]:
    if root is None:
        return []
    return [
        root / "build" / "z3asm" / "z3asm",
        root / "build" / "bin" / "z3asm",
        root / "build" / "src" / "z3asm" / "z3asm",
    ]


def _disasm_candidates(root: Path | None) -> list[Path]:
    if root is None:
        return []
    return [
        root / "build" / "z3disasm" / "z3disasm",
        root / "build" / "bin" / "z3disasm",
        root / "build" / "src" / "z3disasm" / "z3disasm",
    ]


def _lsp_candidates(root: Path | None) -> list[Path]:
    if root is None:
        return []
    return [
        root / "build" / "z3lsp" / "z3lsp",
        root / "build" / "bin" / "z3lsp",
        root / "build" / "src" / "z3lsp" / "z3lsp",
        root / "build-z3dk-foundation" / "z3lsp" / "z3lsp",
        root / "build-z3dk-asan" / "z3lsp" / "z3lsp",
    ]


def _yaze_candidates(root: Path | None) -> list[Path]:
    if root is None:
        return []
    return [
        root / "build" / "bin" / "z3ed",
        root / "build" / "z3ed" / "z3ed",
    ]
