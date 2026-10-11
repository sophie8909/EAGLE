"""Closed grammar validation at the strategy mutation boundary."""
from eagle.strategy_dsl import validate_strategy_dsl


def validate_strategy_prompt_contract(prompt: str) -> None:
    validate_strategy_dsl(prompt)
