from __future__ import annotations

import unittest

from eagle.config import ExperimentConfig
from eagle.evaluation.determinism import derive_match_seed
from eagle.operators.initialization import initialize_population
from eagle.operators.strategy import _role_request_id
from eagle.candidate import Candidate


class DeterminismTests(unittest.TestCase):
    def test_match_seed_is_stable_and_identity_specific(self):
        arguments = {
            "random_seed": 7,
            "candidate_id": "candidate-a",
            "opponent_id": "lightrush",
            "map_id": "map_1",
            "round_index": 2,
            "candidate_player": 1,
            "match_index": 17,
        }
        first = derive_match_seed(**arguments)
        self.assertEqual(first, derive_match_seed(**arguments))
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 2**63)
        self.assertNotEqual(
            first,
            derive_match_seed(**{**arguments, "random_seed": 8}),
        )

    def test_deterministic_population_ids_do_not_use_uuid4(self):
        config = ExperimentConfig.from_mapping({
            "model": {
                "name": "test",
                "gpu_layers": 0,
                "threads": 1,
                "batch_size": 512,
                "parallel": 1,
            },
            "llm": {
                "temperature": 0,
                "initial_policy_temperature": 0,
                "match_commentator": {"temperature": 0},
            },
            "evaluation": {"match_workers": 1},
            "candidate_java_mode": "inherited_genotype",
            "population_size": 2,
            "random_seed": 37,
        })
        first = [candidate.id for candidate in initialize_population(config)]
        second = [candidate.id for candidate in initialize_population(config)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))

    def test_strategy_role_request_id_is_stable(self):
        candidate = Candidate(id="candidate-a", generation=3)
        arguments = {
            "candidate": candidate,
            "role": "coach",
            "match_id": "match-2",
            "suffix": "attempt-1",
        }
        first = _role_request_id(**arguments)
        self.assertEqual(first, _role_request_id(**arguments))
        self.assertNotEqual(
            first,
            _role_request_id(**{**arguments, "suffix": "attempt-2"}),
        )


if __name__ == "__main__":
    unittest.main()
