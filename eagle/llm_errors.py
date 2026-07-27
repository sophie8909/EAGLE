"""Errors that must abort an evolution run when the LLM service is unavailable."""

from __future__ import annotations


class LLMServerError(RuntimeError):
    """A request could not be completed by the configured LLM server."""
