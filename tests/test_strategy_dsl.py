import copy
import json
import unittest
from pathlib import Path

from eagle.strategy_dsl import (
    VERSION,
    extract_strategy_jsonl_record,
    normalize_strategy_dsl,
    validate_strategy_dsl,
    worker_rush_policy,
)
from eagle.operators.strategy_compliance import validate_strategy_prompt_contract
from eagle.operators.strategy import (
    _parse_coach,
    _validate_coach_structure_response,
    _validate_strategy_contract_rewrite_response,
)


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
        _, normalized, _ = _validate_strategy_contract_rewrite_response(json.dumps({'revised_strategy_prompt':policy}))
        self.assertEqual(normalized, worker_rush_policy())
        with self.assertRaises(ValueError):
            _validate_strategy_contract_rewrite_response(json.dumps({'revised_strategy_prompt':policy+' '*20000}))

    def test_jsonl_keeps_valid_rules_and_discards_everything_else(self):
        rules = json.loads(worker_rush_policy())["rules"]
        raw = "\n".join((
            json.dumps({
                "record_type": "coach_metadata",
                "strategy_changes": {"preserved": ["opening"]},
            }),
            "analysis that is not JSON",
            json.dumps({
                "record_type": "strategy_rule",
                "field": "new_strategy_prompt",
                "rule": rules[0],
            }),
            json.dumps({
                "record_type": "strategy_rule",
                "field": "new_strategy_prompt",
                "rule": {"actor": "Base", "when": True, "action": {"type": "attack"}},
            }),
            '{"record_type":"strategy_rule","field":"new_strategy_prompt","rule":',
            json.dumps({
                "record_type": "strategy_rule",
                "field": "new_strategy_prompt",
                "rule": rules[1],
            }),
        ))

        payload, coach, extraction = _validate_coach_structure_response(
            raw,
            parent_strategy_prompt=worker_rush_policy(2),
        )

        self.assertIsInstance(payload["new_strategy_prompt"], str)
        self.assertEqual(
            validate_strategy_dsl(coach.new_strategy_prompt)["rules"],
            rules[:2],
        )
        self.assertEqual(extraction["valid_rule_lines"], [3, 6])
        self.assertEqual(extraction["valid_rule_count"], 2)
        self.assertEqual(extraction["discarded_line_count"], 3)

    def test_jsonl_fails_only_when_no_legal_rule_remains(self):
        parent_record = json.dumps({"parent_strategy_prompt": worker_rush_policy()})
        truncated_child = '{"record_type":"strategy_rule","field":"new_strategy_prompt","rule":'
        raw = parent_record + "\n" + truncated_child

        self.assertIsNone(
            extract_strategy_jsonl_record(raw, field_name="new_strategy_prompt")
        )
        with self.assertRaises(ValueError) as caught:
            _validate_coach_structure_response(
                raw,
                parent_strategy_prompt=worker_rush_policy(),
            )
        self.assertEqual(caught.exception.report["status"], "failed")
        self.assertEqual(caught.exception.report["valid_rule_count"], 0)

    def test_jsonl_rejects_ambiguous_target_records(self):
        record = json.dumps({"new_strategy_prompt": json.loads(worker_rush_policy())})
        with self.assertRaisesRegex(ValueError, "multiple JSONL records"):
            extract_strategy_jsonl_record(
                record + "\n" + record,
                field_name="new_strategy_prompt",
            )
        duplicate_field = (
            '{"new_strategy_prompt":"first",'
            '"new_strategy_prompt":"second"}'
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
            extract_strategy_jsonl_record(
                duplicate_field,
                field_name="new_strategy_prompt",
            )

    def test_jsonl_contract_rewriter_accepts_object_and_validates_entire_dsl(self):
        valid = json.dumps({
            "revised_strategy_prompt": json.loads(worker_rush_policy()),
        }, separators=(",", ":"))
        payload, normalized, extraction = _validate_strategy_contract_rewrite_response(
            "non-JSON explanation\n" + valid + "\nmore prose"
        )
        self.assertEqual(normalized, worker_rush_policy())
        self.assertEqual(normalize_strategy_dsl(payload["revised_strategy_prompt"]), normalized)
        self.assertEqual(extraction["mode"], "legacy_object")

        invalid_policy = json.loads(worker_rush_policy())
        invalid_policy["illegal_sentence"] = "drop me"
        invalid = json.dumps({"revised_strategy_prompt": invalid_policy})
        with self.assertRaises(ValueError):
            _validate_strategy_contract_rewrite_response(invalid)
        with self.assertRaises(ValueError):
            _validate_strategy_contract_rewrite_response(json.dumps({
                "revised_strategy_prompt": worker_rush_policy() + " trailing prose",
            }))

    def test_jsonl_contract_rewriter_keeps_legal_subset_in_order(self):
        rules = json.loads(worker_rush_policy())["rules"]
        lines = [
            json.dumps({
                "record_type": "strategy_rule",
                "field": "revised_strategy_prompt",
                "rule": rules[2],
            }),
            json.dumps({
                "record_type": "strategy_rule",
                "field": "revised_strategy_prompt",
                "rule": {"actor": "Base", "when": True, "action": {"type": "move"}},
            }),
            json.dumps({
                "record_type": "strategy_rule",
                "field": "revised_strategy_prompt",
                "rule": rules[0],
            }),
        ]
        _, normalized, extraction = _validate_strategy_contract_rewrite_response(
            "\n".join(lines)
        )
        self.assertEqual(validate_strategy_dsl(normalized)["rules"], [rules[2], rules[0]])
        self.assertEqual(extraction["valid_rule_lines"], [1, 3])
        self.assertEqual(extraction["discarded_line_count"], 1)
        self.assertEqual(extraction["status"], "partial")

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
