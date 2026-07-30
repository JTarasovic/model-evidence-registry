"""Public-only source connectors for the model-evidence registry PoC."""

import os

from registry.connectors.anthropic_docs import AnthropicDocsConnector
from registry.connectors.artificial_analysis import (
    API_KEY_ENV as ARTIFICIAL_ANALYSIS_API_KEY_ENV,
)
from registry.connectors.artificial_analysis import ArtificialAnalysisConnector
from registry.connectors.base import Connector
from registry.connectors.cerebras_models import CerebrasModelsConnector
from registry.connectors.cohere_docs import CohereDocsConnector
from registry.connectors.github_models import GitHubModelsConnector
from registry.connectors.google_gemini_docs import GoogleGeminiDocsConnector
from registry.connectors.groq_docs import GroqDocsConnector
from registry.connectors.hf_model_cards import HfModelCardsConnector
from registry.connectors.huggingface import HuggingFaceConnector
from registry.connectors.mistral_docs import MistralDocsConnector
from registry.connectors.models_dev import ModelsDevConnector
from registry.connectors.openai_docs import OpenAIDocsConnector
from registry.connectors.openrouter import OpenRouterConnector
from registry.connectors.swebench import SweBenchConnector
from registry.connectors.terminal_bench import TerminalBenchConnector

__all__ = [
    "ArtificialAnalysisConnector",
    "AnthropicDocsConnector",
    "CerebrasModelsConnector",
    "CohereDocsConnector",
    "Connector",
    "GoogleGeminiDocsConnector",
    "GitHubModelsConnector",
    "GroqDocsConnector",
    "HuggingFaceConnector",
    "HfModelCardsConnector",
    "ModelsDevConnector",
    "MistralDocsConnector",
    "OpenAIDocsConnector",
    "OpenRouterConnector",
    "SweBenchConnector",
    "TerminalBenchConnector",
]


def default_connectors() -> list[Connector]:
    """The PoC connector set (public sources only, no credentials)."""
    return [
        AnthropicDocsConnector(),
        OpenAIDocsConnector(),
        GoogleGeminiDocsConnector(),
        CohereDocsConnector(),
        GroqDocsConnector(),
        MistralDocsConnector(),
        GitHubModelsConnector(),
        CerebrasModelsConnector(),
        ModelsDevConnector(),
        OpenRouterConnector(),
        HuggingFaceConnector(),
        HfModelCardsConnector(),
        SweBenchConnector(),
        TerminalBenchConnector(),
    ]


def credentialed_connectors() -> list[Connector]:
    """Optional connectors for *credentialed* sources, appended only when their key is present.

    Kept out of :func:`default_connectors` on purpose: these sources carry redistribution-restricted
    terms and must not enter the public nightly artifact until a human has completed the licensing
    review (Phase 4 plan, ADR 0028). Artificial Analysis is included here only when
    ``ARTIFICIAL_ANALYSIS_API_KEY`` is set, so the default public build never calls it unkeyed.
    """
    connectors: list[Connector] = []
    if os.environ.get(ARTIFICIAL_ANALYSIS_API_KEY_ENV):
        connectors.append(ArtificialAnalysisConnector())
    return connectors
