from __future__ import annotations

import copy
import unittest

from eagle.generation.framework_slots import (
    FRAMEWORK_BUNDLE_SCHEMA_VERSION,
    canonical_genome_json,
    canonical_slot_marker,
    genome_sha256,
    render_framework,
    sample_initial_genome,
    validate_framework_bundle,
    validate_genome,
)
from eagle.operators.framework_slots import (
    crossover_framework_slots,
    mutate_framework_slot,
)


def bundle_payload() -> dict:
    return {
        "schema_version": FRAMEWORK_BUNDLE_SCHEMA_VERSION,
        "framework_id": "test_framework_v1",
        "java_template": (
            "final class CandidateAgent {\n"
            "  int horizon = {{EAGLE_SLOT:horizon}};\n"
            "  double aggression = {{EAGLE_SLOT:aggression}};\n"
            "  boolean engage = {{EAGLE_SLOT:target_formula}};\n"
            "}\n"
        ),
        "slots": [
            {
                "slot_id": "horizon",
                "kind": "integer",
                "marker": "{{EAGLE_SLOT:horizon}}",
                "default": 4,
                "minimum": 2,
                "maximum": 8,
                "step": 2,
                "choices": [],
                "purpose": "Bound the planning horizon.",
            },
            {
                "slot_id": "aggression",
                "kind": "number",
                "marker": "{{EAGLE_SLOT:aggression}}",
                "default": 0.5,
                "minimum": 0.0,
                "maximum": 1.0,
                "step": 0.25,
                "choices": [],
                "purpose": "Weight attack utility.",
            },
            {
                "slot_id": "target_formula",
                "kind": "expression_choice",
                "marker": "{{EAGLE_SLOT:target_formula}}",
                "default": "nearest",
                "minimum": None,
                "maximum": None,
                "step": None,
                "choices": [
                    {
                        "choice_id": "nearest",
                        "java_expression": "distance <= 4",
                        "description": "Engage a nearby target.",
                    },
                    {
                        "choice_id": "weakest",
                        "java_expression": "targetHp < actorHp",
                        "description": "Engage a weaker target.",
                    },
                ],
                "purpose": "Choose the engagement formula.",
            },
        ],
        "slot_generation_prompt": "Return values for the declared typed slots only.",
        "report": {
            "architecture_summary": "A small deterministic decision framework.",
            "decision_flow": ["Observe", "Score", "Act"],
            "invariants": ["No runtime LLM"],
            "slot_rationale": {
                "horizon": "Controls bounded lookahead.",
                "aggression": "Controls a numeric tradeoff.",
                "target_formula": "Controls one allowlisted expression.",
            },
            "assumptions": ["Inputs are finite"],
            "risks": ["A coarse domain may limit diversity"],
        },
    }


class FrameworkBundleValidationTests(unittest.TestCase):
    def test_accepts_exact_bundle_and_computes_stable_hashes(self):
        payload = bundle_payload()
        bundle = validate_framework_bundle(payload)
        reordered = {key: payload[key] for key in reversed(tuple(payload))}
        second = validate_framework_bundle(reordered)

        self.assertEqual(bundle.slot_ids, ("horizon", "aggression", "target_formula"))
        self.assertEqual(bundle.bundle_sha256, second.bundle_sha256)
        self.assertEqual(len(bundle.bundle_sha256), 64)
        self.assertEqual(bundle.report.slot_rationale[0][0], "horizon")

    def test_rejects_unknown_or_missing_keys_at_every_schema_level(self):
        cases = []
        top_unknown = bundle_payload()
        top_unknown["extra"] = True
        cases.append(top_unknown)
        top_missing = bundle_payload()
        del top_missing["report"]
        cases.append(top_missing)
        slot_unknown = bundle_payload()
        slot_unknown["slots"][0]["extra"] = True
        cases.append(slot_unknown)
        choice_missing = bundle_payload()
        del choice_missing["slots"][2]["choices"][0]["description"]
        cases.append(choice_missing)
        report_unknown = bundle_payload()
        report_unknown["report"]["extra"] = []
        cases.append(report_unknown)

        for index, payload in enumerate(cases):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "keys must be exactly"):
                validate_framework_bundle(payload)

    def test_rejects_noncanonical_duplicate_and_undeclared_markers(self):
        bad_framework_id = bundle_payload()
        bad_framework_id["framework_id"] = "Not.Controlled"
        with self.assertRaisesRegex(ValueError, "Invalid framework_id"):
            validate_framework_bundle(bad_framework_id)

        wrong = bundle_payload()
        wrong["slots"][0]["marker"] = "HORIZON"
        with self.assertRaisesRegex(ValueError, "canonical marker"):
            validate_framework_bundle(wrong)

        duplicate = bundle_payload()
        duplicate["java_template"] += "{{EAGLE_SLOT:horizon}}"
        with self.assertRaisesRegex(ValueError, "exactly once"):
            validate_framework_bundle(duplicate)

        undeclared = bundle_payload()
        undeclared["java_template"] += "{{EAGLE_SLOT:unknown}}"
        with self.assertRaisesRegex(ValueError, "marker set mismatch"):
            validate_framework_bundle(undeclared)

        malformed = bundle_payload()
        malformed["java_template"] += "{{EAGLE_SLOT:Bad}}"
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_framework_bundle(malformed)

    def test_rejects_invalid_kind_specific_contracts(self):
        bad_integer = bundle_payload()
        bad_integer["slots"][0]["default"] = True
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            validate_framework_bundle(bad_integer)

        bad_number = bundle_payload()
        bad_number["slots"][1]["maximum"] = 0.9
        with self.assertRaisesRegex(ValueError, "divisible by step"):
            validate_framework_bundle(bad_number)

        bad_choice = bundle_payload()
        bad_choice["slots"][2]["minimum"] = 0
        with self.assertRaisesRegex(ValueError, "must be null"):
            validate_framework_bundle(bad_choice)

        bad_rationale = bundle_payload()
        del bad_rationale["report"]["slot_rationale"]["horizon"]
        with self.assertRaisesRegex(ValueError, "keys must be exactly"):
            validate_framework_bundle(bad_rationale)

    def test_canonical_marker_rejects_uncontrolled_ids(self):
        self.assertEqual(canonical_slot_marker("alpha_2"), "{{EAGLE_SLOT:alpha_2}}")
        for value in ("Alpha", "has-dash", "", "2start"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_slot_marker(value)


class FrameworkGenomeTests(unittest.TestCase):
    def setUp(self):
        self.bundle = validate_framework_bundle(bundle_payload())
        self.genome = {
            "target_formula": "weakest",
            "aggression": 0.75,
            "horizon": 6,
        }

    def test_genome_is_exact_typed_and_canonical(self):
        normalized = validate_genome(self.bundle, self.genome)
        self.assertEqual(tuple(normalized), self.bundle.slot_ids)
        self.assertEqual(normalized["aggression"], 0.75)
        self.assertEqual(
            canonical_genome_json(self.bundle, self.genome),
            '{"aggression":0.75,"horizon":6,"target_formula":"weakest"}',
        )
        self.assertEqual(genome_sha256(self.bundle, self.genome), genome_sha256(self.bundle, normalized))

        unknown = dict(self.genome, extra=1)
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_genome(self.bundle, unknown)
        missing = dict(self.genome)
        del missing["horizon"]
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_genome(self.bundle, missing)
        off_grid = dict(self.genome, aggression=0.6)
        with self.assertRaisesRegex(ValueError, "align to step"):
            validate_genome(self.bundle, off_grid)
        bool_integer = dict(self.genome, horizon=True)
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            validate_genome(self.bundle, bool_integer)

    def test_render_is_deterministic_and_hashes_every_input_and_output(self):
        rendered = render_framework(self.bundle, self.genome)
        again = render_framework(self.bundle, dict(reversed(tuple(self.genome.items()))))

        self.assertEqual(rendered, again)
        self.assertIn("int horizon = 6;", rendered.source)
        self.assertIn("double aggression = 0.75;", rendered.source)
        self.assertIn("boolean engage = targetHp < actorHp;", rendered.source)
        self.assertNotIn("{{EAGLE_SLOT:", rendered.source)
        self.assertEqual(rendered.bundle_sha256, self.bundle.bundle_sha256)
        self.assertEqual(rendered.genome_sha256, genome_sha256(self.bundle, self.genome))
        for digest in (
            rendered.bundle_sha256,
            rendered.template_sha256,
            rendered.genome_sha256,
            rendered.source_sha256,
        ):
            self.assertEqual(len(digest), 64)

    def test_initial_sampling_is_reproducible_valid_and_sample_specific(self):
        first = sample_initial_genome(self.bundle, random_seed=81, sample_index=3)
        second = sample_initial_genome(self.bundle, random_seed=81, sample_index=3)
        self.assertEqual(first, second)
        self.assertEqual(first, validate_genome(self.bundle, first))

        population = {
            canonical_genome_json(
                self.bundle,
                sample_initial_genome(self.bundle, random_seed=81, sample_index=index),
            )
            for index in range(8)
        }
        self.assertGreater(len(population), 1)


class FrameworkSlotOperatorTests(unittest.TestCase):
    def setUp(self):
        self.bundle = validate_framework_bundle(bundle_payload())
        self.parent_a = {
            "horizon": 2,
            "aggression": 0.0,
            "target_formula": "nearest",
        }
        self.parent_b = {
            "horizon": 8,
            "aggression": 1.0,
            "target_formula": "weakest",
        }

    def test_crossover_is_deterministic_and_records_every_slot_parent(self):
        first = crossover_framework_slots(
            self.bundle,
            self.parent_a,
            self.parent_b,
            parent_a_id="parent-a",
            parent_b_id="parent-b",
            random_seed=19,
            generation=2,
            child_index=4,
        )
        second = crossover_framework_slots(
            self.bundle,
            self.parent_a,
            self.parent_b,
            parent_a_id="parent-a",
            parent_b_id="parent-b",
            random_seed=19,
            generation=2,
            child_index=4,
        )
        self.assertEqual(first, second)
        self.assertEqual(set(first.slot_parent_ids), set(self.bundle.slot_ids))
        self.assertEqual(first.source_parent_ids, tuple(dict.fromkeys(first.slot_parent_ids.values())))
        for slot_id, parent_id in first.slot_parent_ids.items():
            expected = self.parent_a if parent_id == "parent-a" else self.parent_b
            self.assertEqual(first.genome[slot_id], expected[slot_id])
            self.assertEqual(first.slot_provenance[slot_id]["operation"], "crossover")

    def test_mutation_changes_only_selected_slot_and_preserves_provenance(self):
        provenance = {
            "horizon": "parent-a",
            "aggression": "parent-b",
            "target_formula": "parent-a",
        }
        result = mutate_framework_slot(
            self.bundle,
            self.parent_a,
            slot_parent_ids=provenance,
            random_seed=23,
            generation=3,
            child_index=1,
            slot_id="aggression",
        )
        self.assertTrue(result.applied)
        self.assertEqual(result.mutated_slot_id, "aggression")
        self.assertNotEqual(result.new_value, result.previous_value)
        self.assertEqual(result.slot_parent_ids, provenance)
        self.assertEqual(result.genome["horizon"], self.parent_a["horizon"])
        self.assertEqual(result.genome["target_formula"], self.parent_a["target_formula"])
        self.assertEqual(result.slot_provenance["aggression"]["operation"], "mutation")
        self.assertEqual(result.slot_provenance["horizon"]["operation"], "copy")
        self.assertEqual(result.genome, validate_genome(self.bundle, result.genome))

    def test_mutation_selection_is_reproducible_and_requires_exact_provenance(self):
        first = mutate_framework_slot(
            self.bundle,
            self.parent_a,
            parent_id="parent-a",
            random_seed=31,
            generation=1,
            child_index=0,
        )
        second = mutate_framework_slot(
            self.bundle,
            self.parent_a,
            parent_id="parent-a",
            random_seed=31,
            generation=1,
            child_index=0,
        )
        self.assertEqual(first, second)
        self.assertTrue(first.applied)
        self.assertEqual(sum(first.genome[key] != self.parent_a[key] for key in self.parent_a), 1)
        self.assertEqual(set(first.slot_parent_ids.values()), {"parent-a"})

        incomplete = {"horizon": "parent-a"}
        with self.assertRaisesRegex(ValueError, "exactly the framework slot IDs"):
            mutate_framework_slot(
                self.bundle,
                self.parent_a,
                slot_parent_ids=incomplete,
                random_seed=31,
                generation=1,
                child_index=0,
            )

    def test_singleton_slot_mutation_is_explicit_noop(self):
        payload = bundle_payload()
        payload["slots"] = [copy.deepcopy(payload["slots"][0])]
        payload["slots"][0].update(default=2, minimum=2, maximum=2, step=1)
        payload["java_template"] = "int horizon = {{EAGLE_SLOT:horizon}};"
        payload["report"]["slot_rationale"] = {
            "horizon": payload["report"]["slot_rationale"]["horizon"]
        }
        bundle = validate_framework_bundle(payload)
        result = mutate_framework_slot(
            bundle,
            {"horizon": 2},
            parent_id="parent-a",
            random_seed=1,
            generation=1,
            child_index=0,
            slot_id="horizon",
        )
        self.assertFalse(result.applied)
        self.assertEqual(result.mutated_slot_id, "horizon")
        self.assertEqual(result.genome, {"horizon": 2})


if __name__ == "__main__":
    unittest.main()
