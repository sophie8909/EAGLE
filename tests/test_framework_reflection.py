from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from eagle.generation.framework_reflection import (
    FRAMEWORK_COACH_MIGRATION_SCHEMA_VERSION,
    FRAMEWORK_STRATEGY_REVISION_SCHEMA_VERSION,
    reflect_framework,
    revise_strategy_descriptions,
    select_reflected_genomes,
)
from eagle.generation.framework_slots import validate_framework_bundle
from eagle.llm import DEFAULT_MAX_PROMPT_CHARS, LLMCallLogger, LLMClient
from test_framework_slots import bundle_payload


class FrameworkReflectionTests(unittest.TestCase):
    def setUp(self):
        self.previous = validate_framework_bundle(bundle_payload())
        self.client = LLMClient("http://localhost:8080", "local-qwen")
        self.config = SimpleNamespace(execution_mode="openai")
        self.evidence = [
            {"candidate_id": "one", "control_genome": {"horizon": 2}, "fitness": [0.2, 0.3]},
            {"candidate_id": "two", "control_genome": {"horizon": 8}, "fitness": [0.7, 0.6]},
        ]

    def reflect(self, path, backend, validator, **kwargs):
        with patch.object(LLMClient, "prompt_backend", return_value=backend) as factory:
            result = reflect_framework(
                previous_bundle=self.previous,
                population_evidence=self.evidence,
                client=self.client,
                config=self.config,
                artifact_dir=path,
                validate_bundle=validator,
                **kwargs,
            )
        self.assertIsNone(factory.call_args.kwargs["max_prompt_chars"])
        return result

    def backend(self, responses):
        return SimpleNamespace(model="local-qwen", generate=Mock(side_effect=responses))

    def test_accepts_complete_redesign_and_preserves_all_evidence_before_parse(self):
        redesigned = bundle_payload()
        redesigned["framework_id"] = "redesigned"
        redesigned["slots"] = redesigned["slots"][:1]
        redesigned["slots"][0]["slot_id"] = "lookahead"
        redesigned["slots"][0]["marker"] = "{{EAGLE_SLOT:lookahead}}"
        redesigned["java_template"] = "class CandidateAgent { int changed = {{EAGLE_SLOT:lookahead}}; }"
        redesigned["report"]["slot_rationale"] = {"lookahead": "A new planning architecture."}
        raw = json.dumps(redesigned)
        backend = self.backend([raw])
        self.evidence.append({"candidate_id": "large", "control_genome": {}, "fitness": [1], "details": "x" * 90_000})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)

            def validate(bundle):
                self.assertEqual((path / "attempts/attempt_001/response_raw.txt").read_text(encoding="utf-8"), raw)
                self.assertTrue((path / "attempts/attempt_001/request.txt").exists())
                self.assertEqual(bundle.slot_ids, ("lookahead",))

            result = self.reflect(path, backend, validate)
            prompt = backend.generate.call_args.args[0]
            self.assertIn(json.dumps(self.previous.to_json_dict(), ensure_ascii=False), prompt)
            self.assertIn(json.dumps(self.evidence, ensure_ascii=False), prompt)
            self.assertGreater(len(prompt), DEFAULT_MAX_PROMPT_CHARS)
            self.assertEqual(result.framework_id, "redesigned")
            self.assertEqual(json.loads((path / "previous_bundle.json").read_text()), self.previous.to_json_dict())
            record = json.loads((path / "result.json").read_text())
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["attempts"][0]["model"], "local-qwen")
            self.assertEqual(record["attempts"][0]["backend"], "openai")
            self.assertGreaterEqual(record["attempts"][0]["duration_seconds"], 0)

    def test_schema_and_compile_repairs_use_immediately_previous_output_and_exact_errors(self):
        first = "not JSON"
        second = json.dumps(bundle_payload())
        final = bundle_payload()
        final["framework_id"] = "repaired"
        backend = self.backend([first, second, json.dumps(final)])
        compiler_error = "CandidateAgent.java:42: error: cannot find symbol\n  missingSymbol"
        validator = Mock(side_effect=[ValueError(compiler_error), None])
        with tempfile.TemporaryDirectory() as temp:
            result = self.reflect(Path(temp), backend, validator)
            prompts = [call.args[0] for call in backend.generate.call_args_list]
            self.assertIn("Previous output:\n" + first, prompts[1])
            self.assertIn("Expecting value", prompts[1])
            self.assertIn("Previous output:\n" + second, prompts[2])
            self.assertIn(compiler_error, prompts[2])
            self.assertNotIn("Previous output:\n" + first, prompts[2])
            self.assertEqual(result.framework_id, "repaired")
            self.assertEqual(validator.call_count, 2)

    def test_four_failed_calls_roll_back_without_mutating_previous_bundle(self):
        original = self.previous.to_json_dict()
        backend = self.backend([json.dumps(original)] * 4)
        validator = Mock(side_effect=RuntimeError("exact javac failure"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            self.assertIsNone(self.reflect(path, backend, validator))
            self.assertEqual(backend.generate.call_count, 4)
            self.assertEqual(self.previous.to_json_dict(), original)
            self.assertFalse((path / "bundle.json").exists())
            record = json.loads((path / "result.json").read_text())
            self.assertEqual(record["status"], "rollback")
            self.assertEqual(record["selected_bundle_sha256"], self.previous.bundle_sha256)
            self.assertEqual(len(record["attempts"]), 4)
            self.assertTrue(all(item["error"] == "exact javac failure" for item in record["attempts"]))

    def test_transport_failure_also_uses_bounded_fallback(self):
        backend = self.backend([RuntimeError("Qwen unavailable")] * 4)
        validator = Mock()
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(self.reflect(Path(temp), backend, validator))
        self.assertEqual(backend.generate.call_count, 4)
        validator.assert_not_called()

    def test_request_timing_logs_once_per_call_and_excludes_compile_duration(self):
        backend = self.backend([json.dumps(bundle_payload())] * 2)
        validator = Mock(side_effect=[ValueError("compile failure"), None])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            logger = LLMCallLogger(path / "llm_logs", run_id="run-one", timing_path=path / "timing.jsonl")
            with patch("eagle.generation.framework_reflection.time.monotonic", side_effect=[0, 1, 10, 11, 12, 21]):
                self.reflect(path / "reflection", backend, validator, timing_logger=logger, generation=5)
            events = [json.loads(line) for line in (path / "timing.jsonl").read_text().splitlines()]
            self.assertEqual(len(events), 2)
            self.assertEqual([event["duration_seconds"] for event in events], [1, 1])
            self.assertEqual([event["generation"] for event in events], [5, 5])
            self.assertTrue(all(event["candidate_id"] is None for event in events))
            self.assertTrue(all(event["operation_stage"] == "framework_reflection" for event in events))
            self.assertTrue(all(event["status"] == "success" for event in events))
            self.assertNotEqual(events[0]["request_correlation_id"], events[1]["request_correlation_id"])
            attempt = json.loads((path / "reflection/attempts/attempt_001/result.json").read_text())
            self.assertEqual(attempt["duration_seconds"], 10)

    def test_backend_prompt_limit_can_be_disabled_without_changing_default(self):
        prompt = "x" * (DEFAULT_MAX_PROMPT_CHARS + 1)
        for limit in (DEFAULT_MAX_PROMPT_CHARS, None):
            with self.subTest(limit=limit):
                backend = self.client.prompt_backend(operation="framework_reflection", max_prompt_chars=limit)
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                with patch("eagle.operators.reflection.urllib.request.urlopen", return_value=response) as request, patch(
                    "eagle.operators.reflection.read_chat_completion_content", return_value="{}"
                ):
                    backend.generate(prompt)
                payload = json.loads(request.call_args.args[0].data)
                actual = payload["messages"][0]["content"]
                if limit is None:
                    self.assertEqual(actual, prompt)
                else:
                    self.assertEqual(len(actual), DEFAULT_MAX_PROMPT_CHARS)
                    self.assertIn("prompt truncated", actual)
        self.assertEqual(self.client.prompt_backend(operation="other").max_prompt_chars, DEFAULT_MAX_PROMPT_CHARS)

    def test_replayed_generation_requests_keep_distinct_correlations(self):
        backend = self.backend([json.dumps(bundle_payload())] * 2)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            logger = LLMCallLogger(path / "llm_logs", run_id="replayed", timing_path=path / "timing.jsonl")
            for invocation in (1, 2):
                self.reflect(path / f"invocation_{invocation:03d}", backend, Mock(),
                             timing_logger=logger, generation=6)
            events = [json.loads(line) for line in (path / "timing.jsonl").read_text().splitlines()]
            self.assertEqual(len({event["request_correlation_id"] for event in events}), 2)

    def coach_payload(self):
        return {
            "schema_version": FRAMEWORK_COACH_MIGRATION_SCHEMA_VERSION,
            "framework_bundle_sha256": "f" * 64,
            "selections": {
                "one": {"horizon": 8, "aggression": 0.75, "target_formula": "weakest"},
                "two": {"horizon": 6, "aggression": 0.25, "target_formula": "nearest"},
            },
        }

    def select_coach(self, path, backend, **kwargs):
        with patch.object(LLMClient, "prompt_backend", return_value=backend) as factory:
            result = select_reflected_genomes(
                bundle=self.previous,
                framework_bundle_sha256="f" * 64,
                previous_bundle=self.previous,
                population_evidence=self.evidence,
                client=self.client,
                config=self.config,
                artifact_dir=path,
                **kwargs,
            )
        self.assertIsNone(factory.call_args.kwargs["max_prompt_chars"])
        schema = factory.call_args.kwargs["response_schema"]
        self.assertEqual(set(schema["properties"]["selections"]["required"]), {"one", "two"})
        return result

    def test_coach_fills_every_individuals_complete_genome_without_defaulting(self):
        payload = self.coach_payload()
        raw = json.dumps(payload)
        backend = self.backend([raw])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = LLMCallLogger(root / "llm_logs", run_id="coach", timing_path=root / "timing.jsonl")
            result = self.select_coach(root / "coach/attempt_001", backend, timing_logger=logger, generation=6)
            self.assertEqual(result, payload["selections"])
            self.assertEqual((root / "coach/attempt_001/response_raw.txt").read_text(), raw)
            prompt = backend.generate.call_args.args[0]
            self.assertIn("ROLE: framework_coach", prompt)
            self.assertIn(json.dumps(self.evidence, ensure_ascii=False), prompt)
            self.assertIn("Previous framework", prompt)
            self.assertIn("New framework", prompt)
            self.assertIn("fresh values for every slot", prompt)
            events = [json.loads(line) for line in (root / "timing.jsonl").read_text().splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["operation_stage"], "framework_coach_migration")
            self.assertEqual(events[0]["generation"], 6)
            self.assertIsNone(events[0]["candidate_id"])
        backend.generate.assert_called_once()

    def test_coach_rejects_incomplete_candidates_slots_illegal_values_hash_and_duplicates(self):
        cases = []
        missing_candidate = self.coach_payload()
        del missing_candidate["selections"]["two"]
        cases.append(json.dumps(missing_candidate))
        extra_candidate = self.coach_payload()
        extra_candidate["selections"]["three"] = extra_candidate["selections"]["one"]
        cases.append(json.dumps(extra_candidate))
        missing_slot = self.coach_payload()
        del missing_slot["selections"]["one"]["aggression"]
        cases.append(json.dumps(missing_slot))
        bad_value = self.coach_payload()
        bad_value["selections"]["one"]["horizon"] = 7
        cases.append(json.dumps(bad_value))
        bad_hash = self.coach_payload()
        bad_hash["framework_bundle_sha256"] = "a" * 64
        cases.append(json.dumps(bad_hash))
        raw = json.dumps(self.coach_payload())
        cases.append(raw.replace('"horizon": 8', '"horizon": 8, "horizon": 6'))
        for raw in cases:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temp:
                backend = self.backend([raw])
                path = Path(temp) / "coach"
                with self.assertRaises(ValueError) as error:
                    self.select_coach(path, backend)
                self.assertIn(raw, str(error.exception))
                self.assertEqual(backend.generate.call_count, 1)
                record = json.loads((path / "result.json").read_text())
                self.assertEqual(record["status"], "failed")
                self.assertEqual((path / "response_raw.txt").read_text(), raw)

    def test_coach_failure_uses_only_outer_framework_repair_budget(self):
        framework_backend = self.backend([json.dumps(bundle_payload())] * 4)
        coach_backend = self.backend(["invalid Coach output"] * 4)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            validations = 0

            def validate(_bundle):
                nonlocal validations
                validations += 1
                self.select_coach(path / "coach" / f"attempt_{validations:03d}", coach_backend)

            self.assertIsNone(self.reflect(path / "framework", framework_backend, validate))
            self.assertEqual(framework_backend.generate.call_count, 4)
            self.assertEqual(coach_backend.generate.call_count, 4)
            self.assertIn("invalid Coach output", framework_backend.generate.call_args_list[1].args[0])

    def revision_payload(self):
        return {
            "schema_version": FRAMEWORK_STRATEGY_REVISION_SCHEMA_VERSION,
            "strategy_descriptions": {
                "one": "  Expand economy\n then   overwhelm with workers.  ",
                "two": "Defend with ranged units and counterattack.",
            },
        }

    def revise(self, path, backend, **kwargs):
        with patch.object(LLMClient, "prompt_backend", return_value=backend) as factory:
            result = revise_strategy_descriptions(
                bundle=self.previous,
                previous_bundle=self.previous,
                population_evidence=self.evidence,
                client=self.client,
                config=self.config,
                artifact_dir=path,
                **kwargs,
            )
        self.assertIsNone(factory.call_args.kwargs["max_prompt_chars"])
        self.assertEqual(factory.call_args.kwargs["operation"], "framework_strategy_revision")
        return result

    def test_strategy_revision_preserves_complete_evidence_and_precedes_slot_filling(self):
        self.evidence[0]["strategy_description"] = "Rush with workers."
        self.evidence[1]["strategy_description"] = "Build a ranged defense."
        prior = [dict(item) for item in self.evidence]
        revision_backend = self.backend([json.dumps(self.revision_payload())])
        coach_backend = self.backend([json.dumps(self.coach_payload())])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = LLMCallLogger(root / "llm_logs", run_id="strategies", timing_path=root / "timing.jsonl")
            revised = self.revise(root / "revision/attempt_001", revision_backend,
                                  timing_logger=logger, generation=6)
            self.assertEqual(revised["one"], "Expand economy then overwhelm with workers.")
            self.assertEqual(self.evidence, prior)
            prompt = revision_backend.generate.call_args.args[0]
            self.assertIn(json.dumps(prior, ensure_ascii=False), prompt)
            self.assertIn("Do not return slot values", prompt)
            self.evidence = [{
                **item,
                "previous_strategy_description": item["strategy_description"],
                "strategy_description": revised[item["candidate_id"]],
            } for item in prior]
            self.select_coach(root / "coach/attempt_001", coach_backend,
                              timing_logger=logger, generation=6)
            fill_prompt = coach_backend.generate.call_args.args[0]
            self.assertIn(json.dumps(self.evidence, ensure_ascii=False), fill_prompt)
            self.assertIn("Follow EACH individual's supplied strategy_description", fill_prompt)
            self.assertIn("historical evidence only", fill_prompt)
            record = json.loads((root / "revision/attempt_001/result.json").read_text())
            self.assertEqual(record["strategy_descriptions"], revised)
            events = [json.loads(line) for line in (root / "timing.jsonl").read_text().splitlines()]
            self.assertEqual([event["operation_stage"] for event in events], [
                "framework_strategy_revision", "framework_coach_migration",
            ])
            self.assertTrue(all(event["candidate_id"] is None and event["generation"] == 6 for event in events))
        revision_backend.generate.assert_called_once()
        coach_backend.generate.assert_called_once()

    def test_strategy_revision_accepts_converged_descriptions_after_initialization(self):
        payload = self.revision_payload()
        payload["strategy_descriptions"]["two"] = payload["strategy_descriptions"]["one"]
        backend = self.backend([json.dumps(payload)])
        with tempfile.TemporaryDirectory() as temp:
            revised = self.revise(Path(temp) / "revision", backend)
            self.assertEqual(revised["one"], revised["two"])
        self.assertIn("Strategies may converge", backend.generate.call_args.args[0])
        backend.generate.assert_called_once()

    def test_option_reflection_prompts_freeze_framework_and_include_repair_error(self):
        repair_error = "Selected horizon did not compile."
        revision_backend = self.backend([json.dumps(self.revision_payload())])
        selection_backend = self.backend([json.dumps(self.coach_payload())])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(LLMClient, "prompt_backend", return_value=revision_backend) as revision_factory:
                revise_strategy_descriptions(
                    bundle=self.previous,
                    previous_bundle=self.previous,
                    population_evidence=self.evidence,
                    client=self.client,
                    config=self.config,
                    artifact_dir=root / "revision",
                    option_only=True,
                    repair_error=repair_error,
                )
            self.assertEqual(
                revision_factory.call_args.kwargs["operation"],
                "framework_option_strategy_revision",
            )
            revision_prompt = revision_backend.generate.call_args.args[0]
            self.assertIn("framework is immutable", revision_prompt)
            self.assertIn("SAME frozen framework", revision_prompt)
            self.assertIn(repair_error, revision_prompt)

            with patch.object(LLMClient, "prompt_backend", return_value=selection_backend) as selection_factory:
                select_reflected_genomes(
                    bundle=self.previous,
                    framework_bundle_sha256="f" * 64,
                    previous_bundle=self.previous,
                    population_evidence=self.evidence,
                    client=self.client,
                    config=self.config,
                    artifact_dir=root / "selection",
                    option_only=True,
                    repair_error=repair_error,
                )
            self.assertEqual(
                selection_factory.call_args.kwargs["operation"],
                "framework_option_selection",
            )
            selection_prompt = selection_backend.generate.call_args.args[0]
            self.assertIn("framework is immutable", selection_prompt)
            self.assertIn("SAME frozen slot domain", selection_prompt)
            self.assertIn(repair_error, selection_prompt)

    def test_strategy_revision_rejects_incomplete_blank_duplicate_json_and_slot_outputs(self):
        cases = []
        missing = self.revision_payload()
        del missing["strategy_descriptions"]["two"]
        cases.append(json.dumps(missing))
        extra = self.revision_payload()
        extra["strategy_descriptions"]["three"] = "Build only heavy units."
        cases.append(json.dumps(extra))
        blank = self.revision_payload()
        blank["strategy_descriptions"]["one"] = " \n  \t "
        cases.append(json.dumps(blank))
        slots = self.revision_payload()
        slots["selections"] = self.coach_payload()["selections"]
        cases.append(json.dumps(slots))
        raw = json.dumps(self.revision_payload())
        cases.append(raw.replace('"one":', '"two": "Duplicate key", "one":'))
        for raw in cases:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "revision"
                backend = self.backend([raw])
                with self.assertRaises(ValueError) as error:
                    self.revise(path, backend)
                self.assertIn(raw, str(error.exception))
                self.assertEqual(backend.generate.call_count, 1)
                record = json.loads((path / "result.json").read_text())
                self.assertEqual(record["status"], "failed")
                self.assertIsNone(record["strategy_descriptions"])
                self.assertEqual((path / "response_raw.txt").read_text(), raw)


if __name__ == "__main__":
    unittest.main()
