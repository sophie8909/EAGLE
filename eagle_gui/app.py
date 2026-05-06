"""Native desktop entrypoint for the EAGLE GUI."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from .desktop_app import main
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from desktop_app import main


if __name__ == "__main__":
    main()
