import copy
import json
import unittest
from pathlib import Path

from eagle.strategy_dsl import VERSION, normalize_strategy_dsl, validate_strategy_dsl, worker_rush_policy
from eagle.operators.strategy_compliance import validate_strategy_prompt_contract
from eagle.operators.strategy import _validate_strategy_contract_rewrite_response, _parse_coach


class StrategyDSLTests(unittest.TestCase):
    def test_checked_in_seeds_and_mock_policy_validate(self):
        for path in Path('seeds').glob('*.txt'):
            policy = validate_strategy_dsl(path.read_text(encoding='utf-8'))
            self.assertEqual(policy['version'], VERSION)
        self.assertEqual(validate_strategy_dsl(Path('seeds/blank_policy.txt').read_text())['rules'], [])
        validate_strategy_prompt_contract(worker_rush_policy())

    def test_canonicalization_preserves_rule_priority(self):
        data = validate_strategy_dsl(worker_rush_policy())
        normalized = normalize_strategy_dsl(json.dumps(data, indent=2))
        self.assertEqual(normalized, worker_rush_policy())
        self.assertEqual(json.loads(normalized)['rules'], data['rules'])

    def test_rejects_unknown_fields_versions_legacy_and_duplicate_keys(self):
        for source in ['train workers', '{"version":"eagle-strategy-dsl-v1","version":"eagle-strategy-dsl-v1","rules":[]}', {'version':'future','rules':[]}, {'version':VERSION,'rules':[],'description':'rush'}]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_strategy_dsl(source)

    def test_rejects_illegal_actor_action_target_and_fields(self):
        data = validate_strategy_dsl(worker_rush_policy())
        for rule in [
            {'actor':'Resource','when':True,'action':{'type':'idle'}},
            {'actor':'Worker','when':True,'action':{'type':'train','unit':'Worker','target':{'kind':'cell','selector':'first_free_adjacent'}}},
            {'actor':'Base','when':True,'action':{'type':'move','target':{'kind':'cell','selector':'first_free_adjacent'}}},
            {'actor':'Worker','when':True,'action':{'type':'attack','target':{'kind':'entity','owner':'neutral','types':['Resource'],'selector':'nearest'}}},
            {'actor':'Worker','when':True,'action':{'type':'idle','code':'x'}},
            {'actor':'Worker','when':{'compare':{'metric':'enemy_intent','op':'==','value':1}},'action':{'type':'idle'}},
        ]:
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                validate_strategy_dsl({'version':VERSION,'rules':[rule]})
        malformed = copy.deepcopy(data)
        malformed['rules'][1]['action']['target']['types'] = [{}]
        with self.assertRaises(ValueError):
            validate_strategy_dsl(malformed)

    def test_size_depth_count_numeric_and_choice_are_bounded(self):
        condition = True
        for _ in range(8): condition = {'not':condition}
        for policy in [
            {'version':VERSION,'rules':[{'actor':'Worker','when':condition,'action':{'type':'idle'}}]},
            {'version':VERSION,'rules':[{'actor':'Worker','when':True,'action':{'type':'idle'}}]*33},
            {'version':VERSION,'rules':[{'actor':'Worker','when':{'compare':{'metric':'time','op':'>','value':float('nan')}},'action':{'type':'idle'}}]},
            {'version':VERSION,'rules':[{'actor':'Worker','when':True,'action':{'type':'choose','options':[{'type':'choose','options':[{'type':'idle'}]}]}}]},
        ]:
            with self.assertRaises(ValueError): validate_strategy_dsl(policy)
        with self.assertRaises(ValueError): normalize_strategy_dsl(worker_rush_policy(), max_chars=50)
        with self.assertRaises(ValueError): validate_strategy_dsl('['*10000+']'*10000)

    def test_boolean_count_distance_conditions_accept_observable_state(self):
        condition = {'all':[{'compare':{'metric':'count','op':'<','value':3,'entities':{'owner':'friendly','types':['Worker']},'radius':5}}, {'any':[{'not':False},{'compare':{'metric':'distance','op':'<=','value':8,'entities':{'owner':'enemy','types':['Worker']}}}]}]}
        policy = {'version':VERSION,'rules':[{'actor':'Base','when':condition,'action':{'type':'train','unit':'Worker','target':{'kind':'cell','selector':'first_free_adjacent'}}}]}
        validate_strategy_dsl(policy)

    def test_rewrite_boundary_canonicalizes_without_truncation(self):
        policy = json.dumps(validate_strategy_dsl(worker_rush_policy()), indent=2)
        _, normalized = _validate_strategy_contract_rewrite_response(json.dumps({'revised_strategy_prompt':policy}))
        self.assertEqual(normalized, worker_rush_policy())
        with self.assertRaises(ValueError):
            _validate_strategy_contract_rewrite_response(json.dumps({'revised_strategy_prompt':policy+' '*20000}))

    def test_coach_keeps_raw_policy_size_and_requires_string(self):
        oversized = worker_rush_policy() + " " * 20000
        coach = _parse_coach(json.dumps({"new_strategy_prompt": oversized}), parent_strategy_prompt=worker_rush_policy())
        self.assertEqual(coach.new_strategy_prompt, oversized)
        with self.assertRaises(ValueError):
            normalize_strategy_dsl(coach.new_strategy_prompt)
        with self.assertRaises(ValueError):
            _parse_coach(json.dumps({"new_strategy_prompt": {"version": VERSION, "rules": []}}), parent_strategy_prompt=worker_rush_policy())

    def test_callers_cannot_raise_normative_size_and_rule_caps(self):
        with self.assertRaises(ValueError):
            normalize_strategy_dsl(worker_rush_policy() + " " * 20000, max_chars=100000)
        with self.assertRaises(ValueError):
            validate_strategy_dsl({"version": VERSION, "rules": [{"actor": "Worker", "when": True, "action": {"type": "idle"}}] * 33}, max_rules=100)
