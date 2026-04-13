"""Keyword-based model routing.

Routes user messages to the best model based on keyword matching
against rules defined in chat_registry.toml routers.
"""

from __future__ import annotations

from z3cli.core.config import RouterConfig, ModelConfig


def route_message(
    message: str,
    router: RouterConfig,
    models: dict[str, ModelConfig],
) -> tuple[str | None, str | None]:
    """Route a message to a model based on keywords.

    Returns:
        (model_name, matched_keyword) or (None, None) if no match.
    """
    if router.router_type != "keyword":
        return None, None

    msg_lower = message.lower()

    for rule in router.rules:
        for keyword in rule.keywords:
            if keyword.lower() in msg_lower:
                if rule.model in models:
                    return rule.model, keyword

    return None, None
