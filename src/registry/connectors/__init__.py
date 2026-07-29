"""Public-only source connectors for the model-evidence registry PoC."""

from registry.connectors.base import Connector
from registry.connectors.huggingface import HuggingFaceConnector
from registry.connectors.models_dev import ModelsDevConnector
from registry.connectors.openrouter import OpenRouterConnector
from registry.connectors.swebench import SweBenchConnector
from registry.connectors.terminal_bench import TerminalBenchConnector

__all__ = [
    "Connector",
    "HuggingFaceConnector",
    "ModelsDevConnector",
    "OpenRouterConnector",
    "SweBenchConnector",
    "TerminalBenchConnector",
]


def default_connectors() -> list[Connector]:
    """The PoC connector set (public sources only, no credentials)."""
    return [
        ModelsDevConnector(),
        OpenRouterConnector(),
        HuggingFaceConnector(),
        SweBenchConnector(),
        TerminalBenchConnector(),
    ]
