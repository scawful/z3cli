"""Rich rendering layer for z3cli.

Markdown streaming, tool call panels, welcome banner, status bar, and stats.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Avoid hard prompt_toolkit dependency — only used for type hints
_to_toolbar_html: Any = lambda s: s
try:
    from prompt_toolkit.formatted_text import HTML as _HTML
    _to_toolbar_html = lambda s: _HTML(s)
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Markdown streamer
# ---------------------------------------------------------------------------

class MarkdownStreamer:
    """Buffers streaming tokens and renders via Rich Live + Markdown.

    Usage::

        streamer = MarkdownStreamer(console)
        streamer.start()
        streamer.feed("# Hello")
        streamer.feed(" world")
        text = streamer.finish()  # returns full buffer
    """

    # Above this size, skip incremental Markdown re-parse during streaming
    _LARGE_THRESHOLD = 50_000

    def __init__(self, console: Console):
        self._console = console
        self._buffer = ""
        self._live: Live | None = None

    def start(self) -> None:
        self._buffer = ""
        self._live = Live(
            Text(""),
            console=self._console,
            refresh_per_second=8,
            vertical_overflow="visible",
        )
        self._live.__enter__()

    def feed(self, text: str) -> None:
        self._buffer += text
        if self._live is None:
            return
        if len(self._buffer) < self._LARGE_THRESHOLD:
            self._live.update(Markdown(self._buffer))
        else:
            # For very long outputs, show plain text during streaming
            self._live.update(Text(self._buffer))

    def feed_error(self, message: str) -> None:
        self._buffer += f"\n\n**Error:** {message}\n"
        if self._live is not None:
            self._live.update(Markdown(self._buffer))

    def finish(self) -> str:
        """End streaming and print final rendered markdown. Returns full text."""
        if self._live is not None:
            self._live.__exit__(None, None, None)
            self._live = None
        if self._buffer.strip():
            self._console.print(Markdown(self._buffer))
        return self._buffer

    @property
    def has_content(self) -> bool:
        return bool(self._buffer.strip())


# ---------------------------------------------------------------------------
# Thinking panel
# ---------------------------------------------------------------------------

class ThinkingStreamer:
    """Buffers streaming thinking tokens and renders as a dim Rich panel.

    Usage::

        ts = ThinkingStreamer(console)
        ts.start()
        ts.feed("reasoning about which tool to use...")
        ts.finish()
    """

    def __init__(self, console: Console):
        self._console = console
        self._buffer = ""
        self._live: Live | None = None

    def start(self) -> None:
        self._buffer = ""
        self._live = Live(
            Text(""),
            console=self._console,
            refresh_per_second=6,
            vertical_overflow="visible",
        )
        self._live.__enter__()

    def feed(self, text: str) -> None:
        self._buffer += text
        if self._live is None:
            return
        panel = Panel(
            Text(self._buffer, style="dim italic"),
            title="[dim]thinking[/dim]",
            border_style="dim blue",
            padding=(0, 1),
        )
        self._live.update(panel)

    def finish(self) -> str:
        """End streaming and print final thinking panel. Returns full text."""
        if self._live is not None:
            self._live.__exit__(None, None, None)
            self._live = None
        if self._buffer.strip():
            self._console.print(Panel(
                Text(self._buffer.strip(), style="dim italic"),
                title="[dim]thinking[/dim]",
                border_style="dim blue",
                padding=(0, 1),
            ))
        return self._buffer

    @property
    def has_content(self) -> bool:
        return bool(self._buffer.strip())


# ---------------------------------------------------------------------------
# Tool call panels
# ---------------------------------------------------------------------------

class ToolPanel:
    """Renders tool calls and results as Rich Panels."""

    @staticmethod
    def render_call(name: str, server: str, arguments: str) -> Panel:
        title = f"{server}:{name}" if server and server != "unknown" else name
        # Truncate long argument strings
        args_display = arguments if len(arguments) <= 200 else arguments[:197] + "..."
        body = Text(args_display, style="dim")
        return Panel(
            body,
            title=f"[bold yellow]tool[/bold yellow] {title}",
            border_style="yellow",
            padding=(0, 1),
        )

    @staticmethod
    def render_result(name: str, result: str, max_lines: int = 10) -> Panel:
        lines = result.splitlines()
        is_error = result.startswith("Error")
        if len(lines) > max_lines:
            display = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
        else:
            display = result
        border = "red" if is_error else "green"
        return Panel(
            Text(display, style="dim"),
            title=f"[dim]{name} result[/dim]",
            border_style=border,
            padding=(0, 1),
        )


# ---------------------------------------------------------------------------
# Welcome banner
# ---------------------------------------------------------------------------

def render_welcome_banner(
    version: str,
    model: str,
    mode: str,
    servers: list[str],
    tool_count: int,
    workspace: str,
) -> Panel:
    lines = [
        f"[bold]z3cli[/bold] v{version}",
        "",
        f"  Model:     [cyan]{model}[/cyan]",
        f"  Mode:      {mode}",
        f"  Workspace: {workspace}",
        f"  Servers:   {', '.join(servers) if servers else '(none)'}",
        f"  Tools:     {tool_count}",
        "",
        "Type [bold]/help[/bold] for commands. Ctrl+C or /exit to quit.",
    ]
    return Panel(
        "\n".join(lines),
        border_style="blue",
        padding=(0, 2),
    )


# ---------------------------------------------------------------------------
# Bottom toolbar for prompt_toolkit
# ---------------------------------------------------------------------------

def build_bottom_toolbar(
    model: str,
    mode: str,
    server_count: int,
    tool_count: int,
    msg_count: int,
) -> Any:
    """Returns an HTML toolbar string for prompt_toolkit (or plain str fallback)."""
    return _to_toolbar_html(
        f" <b>{model}</b> | {mode} | "
        f"{server_count} servers | {tool_count} tools | "
        f"{msg_count} msgs"
    )


# ---------------------------------------------------------------------------
# Stats table
# ---------------------------------------------------------------------------

def render_stats_table(
    messages: int,
    tool_calls: int,
    prompt_tokens: int,
    completion_tokens: int,
) -> Table:
    table = Table(title="Session Stats", show_header=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Messages", str(messages))
    table.add_row("Tool calls", str(tool_calls))
    if prompt_tokens > 0 or completion_tokens > 0:
        table.add_row("Prompt tokens", str(prompt_tokens))
        table.add_row("Completion tokens", str(completion_tokens))
        table.add_row("Total tokens", str(prompt_tokens + completion_tokens))
    else:
        table.add_row("Tokens", "N/A")
    return table
