import unittest
from eagle.operators.strategy_compliance import validate_strategy_prompt_contract
from eagle.strategy_dsl import worker_rush_policy


class StrategyComplianceTests(unittest.TestCase):
    def test_shared_validator_accepts_dsl_and_rejects_prose(self):
        validate_strategy_prompt_contract(worker_rush_policy())
        with self.assertRaises(ValueError):
            validate_strategy_prompt_contract("If a Worker is idle, harvest resources.")
