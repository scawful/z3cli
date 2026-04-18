"""Din adapter — optimization and cycle analysis tools.

Din specializes in performance analysis: profiling routines, reading
memory, tracing execution, and understanding cycle costs.
"""

from __future__ import annotations

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


class DinAdapter(ToolAdapter):
    PROFILE_NAME = "din"

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="profile_routine",
                description="Disassemble a routine and read surrounding memory to analyze its performance characteristics.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "SNES address (e.g. '$02:A3B0' or '0x02A3B0')",
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of disassembly lines to show",
                            "default": 20,
                        },
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="read_memory",
                description="Read bytes from emulator memory at a given address.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Memory address to read from",
                        },
                        "length": {
                            "type": "integer",
                            "description": "Number of bytes to read",
                            "default": 16,
                        },
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="step_trace",
                description="Step the emulator forward and return CPU state after each step.",
                parameters={
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of instructions to step",
                            "default": 1,
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["into", "over", "out"],
                            "description": "Step mode",
                            "default": "into",
                        },
                    },
                },
            ),
            AdapterTool(
                name="disasm_at",
                description="Get disassembly listing at a specific address.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Address to disassemble at",
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of lines",
                            "default": 30,
                        },
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="lookup_symbol",
                description="Look up a symbol, address, or label in the ALTTP disassembly.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Symbol name, hex address, or RAM label to look up",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="read_context",
                description="Read a workspace source file before proposing optimizations.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path relative to the workspace root",
                        },
                    },
                    "required": ["path"],
                },
            ),
            AdapterTool(
                name="check_diagnostics",
                description="Get language-server diagnostics for an ASM source file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Path to the ASM file to inspect",
                        },
                    },
                    "required": ["file"],
                },
            ),
            AdapterTool(
                name="set_breakpoint",
                description="Set a breakpoint at an address to pause execution for analysis.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Address to break at",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["execute", "read", "write"],
                            "description": "Breakpoint type",
                            "default": "execute",
                        },
                    },
                    "required": ["address"],
                },
            ),
        ]

    async def _dispatch(self, name: str, arguments: dict) -> str:
        if name == "profile_routine":
            addr = arguments["address"]
            lines = arguments.get("lines", 20)
            disasm, mem = await self._call_many_on([
                ("emulator", "mesen_disasm", {"address": addr, "count": lines}),
                ("emulator", "mesen_memory_read", {"address": addr, "length": 64}),
            ])
            return f"## Disassembly at {addr}\n{disasm}\n\n## Raw bytes\n{mem}"

        if name == "read_memory":
            return await self._call_on("emulator", "mesen_memory_read", {
                "address": arguments["address"],
                "length": arguments.get("length", 16),
            })

        if name == "step_trace":
            # mesen-control action=step runs a single instruction. into/over
            # semantics collapse to the same single-step call; step count
            # is emulated by looping.
            count = int(arguments.get("count", 1) or 1)
            parts: list[str] = []
            for i in range(count):
                step_result = await self._call_on("emulator", "mesen_control", {"action": "step"})
                state = await self._call_on("emulator", "mesen_cpu", {})
                parts.append(f"Step {i + 1}:\n{step_result}\n{state}")
            return "\n---\n".join(parts)

        if name == "disasm_at":
            return await self._call_on("emulator", "mesen_disasm", {
                "address": arguments["address"],
                "count": arguments.get("lines", 30),
            })

        if name == "lookup_symbol":
            return await self._call_on("symbols", "z3lsp_symbols", {"query": arguments["query"]})

        if name == "read_context":
            return await self._call_on("workspace", "workspace_read", {"path": arguments["path"]})

        if name == "check_diagnostics":
            return await self._call_on("symbols", "z3lsp_diagnostics", {"file": arguments["file"]})

        if name == "set_breakpoint":
            bp_type_map = {"execute": "exec", "read": "read", "write": "write"}
            return await self._call_on("emulator", "mesen_breakpoint", {
                "action": "add",
                "address": arguments["address"],
                "type": bp_type_map.get(arguments.get("type", "execute"), "exec"),
            })

        return await super()._dispatch(name, arguments)
