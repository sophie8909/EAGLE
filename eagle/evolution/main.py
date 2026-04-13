"""Compatibility wrapper for the top-level `eagle.main` module."""

from ..main import OPPONENT_LIST, main

__all__ = ["OPPONENT_LIST", "main"]


if __name__ == "__main__":
    main()
