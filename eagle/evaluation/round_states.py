"""Read the buffered MicroRTS snapshot transport used by compact matches."""

from collections.abc import Iterator
from pathlib import Path
from struct import Struct


ROUND_STATE_STREAM_NAME = "round_states-v1.bin"
# Older buffered builds require this flag. The stream format is unchanged.
ROUND_STATE_STREAM_PROPERTY = "microrts.round_state_stream"
_FRAME_HEADER = Struct(">II")


def require_buffered_round_states(microrts_dir: Path) -> None:
    """Reject a compiled runtime that would silently write a file per tick."""
    game_class = microrts_dir / "bin/rts/Game.class"
    try:
        compiled = game_class.read_bytes()
    except OSError as exc:
        raise ValueError(f"MicroRTS is not compiled at {game_class}. Build the vendored runtime before starting.") from exc
    if ROUND_STATE_STREAM_NAME.encode("ascii") not in compiled:
        raise ValueError(
            f"MicroRTS at {game_class} lacks buffered round-state support. "
            "Rebuild it from the current vendored Java source before starting evaluation."
        )


def read_round_state_stream(path: Path) -> Iterator[tuple[str, str]]:
    """Yield complete snapshots, retaining the valid prefix after a killed JVM."""
    with path.open("rb") as stream:
        while len(header := stream.read(_FRAME_HEADER.size)) == _FRAME_HEADER.size:
            tick, byte_count = _FRAME_HEADER.unpack(header)
            payload = stream.read(byte_count)
            if len(payload) != byte_count:
                break
            yield f"round_{tick:06d}.log", payload.decode("utf-8")
