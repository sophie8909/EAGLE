from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.generation.codex_framework import (
    CODEX_BOOTSTRAP_SCHEMA_VERSION,
    CodexFrameworkError,
    generate_codex_framework_bundle,
)
from eagle.generation.groq_framework import FRAMEWORK_RESPONSE_SCHEMA
from tests.test_groq_framework import _bundle


class CodexFrameworkTests(unittest.TestCase):
    def test_success_runs_one_read_only_ephemeral_codex_command_and_persists_evidence(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            message_path = Path(command[command.index("--output-last-message") + 1])
            message_path.write_text(json.dumps(_bundle()), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "codex stdout", "codex stderr")

        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.generation.codex_framework.subprocess.run", side_effect=run
        ):
            output = Path(directory) / "codex_primary"
            result = generate_codex_framework_bundle(
                output,
                model="gpt-6.1-sol",
                design_brief="Build a bounded economy and combat controller.",
                timeout_seconds=12.0,
            )
            self.assertEqual(result.bundle, _bundle())
            self.assertEqual(len(calls), 1)
            command, kwargs = calls[0]
            self.assertEqual(command[:2], ["codex", "exec"])
            self.assertEqual(command[command.index("--model") + 1], "gpt-6.1-sol")
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertIn("--ephemeral", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertIn("--output-schema", command)
            self.assertIn("--output-last-message", command)
            self.assertEqual(command[-1], "-")
            self.assertTrue(kwargs["text"])
            self.assertEqual(kwargs["timeout"], 12.0)
            self.assertIn("Build a bounded economy", str(kwargs["input"]))
            self.assertEqual(
                json.loads((output / "response_schema.json").read_text(encoding="utf-8")),
                FRAMEWORK_RESPONSE_SCHEMA,
            )
            self.assertEqual((output / "stdout.txt").read_text(encoding="utf-8"), "codex stdout")
            self.assertEqual((output / "stderr.txt").read_text(encoding="utf-8"), "codex stderr")
            result_record = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result_record["schema_version"], CODEX_BOOTSTRAP_SCHEMA_VERSION)
            self.assertEqual(result_record["status"], "success")
            self.assertEqual(result_record["provider"], "codex")
            self.assertEqual(result_record["framework_id"], _bundle()["framework_id"])
            self.assertIsNone(result_record["error"])

    def test_missing_executable_records_failure_before_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.generation.codex_framework.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            output = Path(directory) / "codex_primary"
            with self.assertRaisesRegex(CodexFrameworkError, "not found") as caught:
                generate_codex_framework_bundle(
                    output, model="gpt-6.1-sol", design_brief="Build a framework."
                )

            record = json.loads((output / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(caught.exception.reason, record["error"])
            self.assertEqual(record["status"], "failed")
            self.assertFalse((output / "bundle.json").exists())

    def test_timeout_retains_process_output_and_records_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.generation.codex_framework.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                ["codex", "exec"], 4.0, output=b"partial stdout", stderr=b"partial stderr"
            ),
        ):
            output = Path(directory) / "codex_primary"
            with self.assertRaisesRegex(CodexFrameworkError, "timed out after 4 seconds"):
                generate_codex_framework_bundle(
                    output,
                    model="gpt-6.1-sol",
                    design_brief="Build a framework.",
                    timeout_seconds=4.0,
                )

            self.assertEqual((output / "stdout.txt").read_text(encoding="utf-8"), "partial stdout")
            self.assertEqual((output / "stderr.txt").read_text(encoding="utf-8"), "partial stderr")
            record = json.loads((output / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertIn("timed out", record["error"])

    def test_nonzero_and_invalid_last_message_are_safe_failures(self) -> None:
        cases = (
            (
                "nonzero",
                lambda command: subprocess.CompletedProcess(command, 7, "", "unavailable"),
                "exited with status 7",
            ),
            (
                "malformed",
                lambda command: self._write_invalid_message(command),
                "response validation failed",
            ),
        )
        for name, factory, reason in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, patch(
                "eagle.generation.codex_framework.subprocess.run",
                side_effect=lambda command, **kwargs: factory(command),
            ):
                output = Path(directory) / "codex_primary"
                with self.assertRaisesRegex(CodexFrameworkError, reason):
                    generate_codex_framework_bundle(
                        output, model="gpt-6.1-sol", design_brief="Build a framework."
                    )
                record = json.loads((output / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(record["status"], "failed")
                self.assertIn(reason, str(record["error"]))

    @staticmethod
    def _write_invalid_message(command: list[str]) -> subprocess.CompletedProcess[str]:
        message_path = Path(command[command.index("--output-last-message") + 1])
        message_path.write_text("{not json", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")


if __name__ == "__main__":
    unittest.main()
