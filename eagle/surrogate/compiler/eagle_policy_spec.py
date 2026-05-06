"""Map fixed prompt policies onto deterministic eaglePolicy specs."""

from __future__ import annotations

from .prompt_to_eagle_policy import Policy, compile_prompt_to_policy


def policy_to_eagle_policy_spec(policy: Policy) -> dict:
    """Convert a validated fixed policy into the eaglePolicy Java spec format."""

    strategy_identity = policy["strategy_identity"]
    opening_plan = policy["opening_plan"]
    unit_preference = policy["unit_preference"]
    attack_timing = policy["attack_timing"]

    spec = {
        "enabled": True,
        "worker_target_before_barracks": 2,
        "worker_target_after_barracks": 2,
        "harvester_target": 2,
        "desired_barracks": 1,
        "worker_harass_enabled": False,
        "attack_workers_first": False,
        "attack_structures_first": False,
        "protect_barracks": False,
        "min_lights": 0,
        "min_ranged": 0,
        "min_heavies": 0,
        "production_priority": [],
    }

    if strategy_identity == "economic":
        spec["worker_target_before_barracks"] = 3
        spec["worker_target_after_barracks"] = 4
        spec["harvester_target"] = 3
    elif strategy_identity == "aggressive":
        spec["worker_target_before_barracks"] = 1
        spec["worker_target_after_barracks"] = 2
        spec["harvester_target"] = 1
        spec["attack_workers_first"] = True
    elif strategy_identity == "defensive":
        spec["worker_target_before_barracks"] = 2
        spec["worker_target_after_barracks"] = 3
        spec["harvester_target"] = 2
        spec["protect_barracks"] = True
        spec["attack_structures_first"] = True

    if opening_plan == "worker_first":
        spec["worker_target_before_barracks"] = max(spec["worker_target_before_barracks"], 3)
        spec["harvester_target"] = max(spec["harvester_target"], 2)
    elif opening_plan == "barracks_first":
        spec["desired_barracks"] = 1
        spec["worker_target_before_barracks"] = min(spec["worker_target_before_barracks"], 1)
        spec["harvester_target"] = min(spec["harvester_target"], 1)
    elif opening_plan == "harvest_first":
        spec["harvester_target"] = max(spec["harvester_target"], 2)

    if unit_preference == "worker":
        spec["worker_harass_enabled"] = True
        spec["production_priority"] = []
    elif unit_preference == "light":
        spec["min_lights"] = 2
        spec["production_priority"] = ["Light", "Light", "Ranged"]
    elif unit_preference == "heavy":
        spec["min_heavies"] = 2
        spec["production_priority"] = ["Heavy", "Heavy", "Ranged"]
    elif unit_preference == "ranged":
        spec["min_ranged"] = 2
        spec["production_priority"] = ["Ranged", "Ranged", "Light"]
    else:
        spec["min_lights"] = 1
        spec["min_ranged"] = 1
        spec["min_heavies"] = 1
        spec["production_priority"] = ["Light", "Ranged", "Heavy"]

    if attack_timing == "early":
        spec["desired_barracks"] = max(spec["desired_barracks"], 1)
        spec["worker_target_after_barracks"] = min(spec["worker_target_after_barracks"], 2)
        if not spec["production_priority"]:
            spec["worker_harass_enabled"] = True
    elif attack_timing == "late":
        spec["worker_target_after_barracks"] = max(spec["worker_target_after_barracks"], 3)
        spec["harvester_target"] = max(spec["harvester_target"], 2)
        spec["protect_barracks"] = True

    return spec


def compile_prompt_to_eagle_policy_spec(prompt: str) -> tuple[Policy, dict]:
    """Compile a prompt into a validated policy and then into an eaglePolicy spec."""

    policy = compile_prompt_to_policy(prompt)
    return policy, policy_to_eagle_policy_spec(policy)
