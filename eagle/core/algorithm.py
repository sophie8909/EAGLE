"""Base algorithm interface for evolutionary prompt-search experiments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAlgorithm(ABC):
    """Required lifecycle for reusable evolutionary algorithms."""

    @abstractmethod
    def initialize(self) -> Any:
        """Initialize algorithm state before search begins."""

    @abstractmethod
    def step(self) -> Any:
        """Execute one evolutionary step or generation."""

    @abstractmethod
    def run(self) -> Any:
        """Run the algorithm until its configured stopping condition."""

    @abstractmethod
    def select_parents(self) -> Any:
        """Select parent individuals from the current population."""

    @abstractmethod
    def variation(self, parents: Any = None) -> Any:
        """Create offspring from selected parents."""

    @abstractmethod
    def evaluate(self, individuals: Any = None) -> Any:
        """Evaluate one or more individuals."""

    @abstractmethod
    def environmental_select(self, population: Any = None, offspring: Any = None) -> Any:
        """Choose survivors for the next population."""
