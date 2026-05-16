import json
from pathlib import Path
from typing import Any


class PromptHistory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.history: dict[str, dict[str, Any]] = {}
        self._load()

    # ---------- hash ----------
    def _hash_prompt(self, prompt: str) -> str:
        import hashlib
        normalized = "\n".join(line.rstrip() for line in prompt.strip().splitlines())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    # ---------- load ----------
    def _load(self) -> None:
        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"Prompt history row must be an object: {self.path}:{line_number}")
                key = record["prompt_hash"]
                self.history[key] = record

    # ---------- get ----------
    def get(self, prompt: str) -> list[float] | None:
        key = self._hash_prompt(prompt)
        entry = self.history.get(key)
        if entry is None:
            return None
        return entry["fitness"]

    def get_record(self, prompt: str) -> dict[str, Any] | None:
        key = self._hash_prompt(prompt)
        entry = self.history.get(key)
        if entry is None:
            return None
        return dict(entry)

    # ---------- save ----------
    def save(
        self,
        prompt: str,
        fitness: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        key = self._hash_prompt(prompt)

        record = {
            "prompt_hash": key,
            "prompt": prompt,
            "fitness": fitness,
            "metadata": metadata or {},
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)

        print(f"[PromptHistory] saving to: {self.path.resolve()}")

        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

        self.history[key] = record
