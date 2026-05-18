"""Local llama.cpp helpers used by mutation, evaluation, and surrogate workflows."""

import os
import re
import ast
import json
from pathlib import Path
from typing import Any

import requests

from eagle.utils.llm_debug import append_llm_debug_record


DEFAULT_MODEL = os.getenv("LLAMA_CPP_MODEL", "local")
DEFAULT_MAX_TOKENS = int(os.getenv("LLAMA_CPP_MAX_TOKENS", "2048"))


def _normalize_base_url(raw_url: str | None) -> str:
    """Normalize llama.cpp's OpenAI-compatible base URL."""
    base_url = (raw_url or "http://127.0.0.1:8080/v1").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        base_url = "http://" + base_url
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return base_url


DEFAULT_BASE_URL = _normalize_base_url(os.getenv("LLAMA_CPP_BASE_URL"))


class LLM:
    """Local llama.cpp endpoint helpers used by the EA pipeline."""

    @staticmethod
    def _resolve_model(model: str | None) -> str:
        """Resolve the model name sent to llama.cpp's OpenAI-compatible API."""
        return os.getenv("LLAMA_CPP_MODEL") or model or DEFAULT_MODEL

    @classmethod
    def _generate_text(
        cls,
        *,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        debug_log_dir: str | Path | None = None,
        debug_context: dict[str, Any] | None = None,
        debug_record: dict[str, Any] | None = None,
        defer_debug_write: bool = False,
    ) -> str:
        """Generate one non-streaming chat completion through llama.cpp."""
        resolved_model = cls._resolve_model(model)
        request_payload = {
            "model": resolved_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        context = dict(debug_context or {})
        debug_values: dict[str, Any] = {
            "generation": context.get("generation", ""),
            "individual_id": context.get("individual_id", ""),
            "mode": context.get("mode", ""),
            "opponent": context.get("opponent", ""),
            "model": resolved_model,
            "prompt": prompt,
            "request_payload": request_payload,
            "raw_response_body": "",
            "parsed_response": "",
            "fallback_response": "",
            "error": None,
        }
        if debug_record is not None:
            debug_record.update(debug_values)
        response = None
        try:
            response = requests.post(
                f"{DEFAULT_BASE_URL}/chat/completions",
                json=request_payload,
                timeout=120,
            )
            raw_response_body = response.text
            debug_values["raw_response_body"] = raw_response_body
            if debug_record is not None:
                debug_record.update(debug_values)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            if response is not None:
                debug_values["raw_response_body"] = response.text
            debug_values["error"] = exc
            if debug_record is not None:
                debug_record.update(debug_values)
            append_llm_debug_record(debug_log_dir, **debug_values)
            raise
        except json.JSONDecodeError as exc:
            debug_values["error"] = exc
            if debug_record is not None:
                debug_record.update(debug_values)
            append_llm_debug_record(debug_log_dir, **debug_values)
            raise
        choices = data.get("choices") or []
        if not choices:
            debug_values["error"] = "llama.cpp returned no chat completion choices."
            if debug_record is not None:
                debug_record.update(debug_values)
            append_llm_debug_record(debug_log_dir, **debug_values)
            raise ValueError("llama.cpp returned no chat completion choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            debug_values["error"] = "llama.cpp returned an empty response."
            if debug_record is not None:
                debug_record.update(debug_values)
            append_llm_debug_record(debug_log_dir, **debug_values)
            raise ValueError("llama.cpp returned an empty response.")
        parsed_response = str(content).strip()
        debug_values["parsed_response"] = parsed_response
        if debug_record is not None:
            debug_record.update(debug_values)
        if not defer_debug_write:
            append_llm_debug_record(debug_log_dir, **debug_values)
        return parsed_response

    @staticmethod
    def _extract_first_json_object(raw_output: str) -> dict | None:
        """Parse one JSON object from model output, tolerating surrounding text."""
        if not raw_output:
            raise ValueError("llama.cpp response was empty; expected one JSON object.")
        try:
            parsed = json.loads(raw_output)
            if not isinstance(parsed, dict):
                raise ValueError(f"llama.cpp JSON response must be an object, got {type(parsed).__name__}.")
            return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if not match:
            raise ValueError("llama.cpp response did not contain a JSON object.")

        try:
            parsed = json.loads(match.group(0))
            if not isinstance(parsed, dict):
                raise ValueError(f"llama.cpp JSON response must be an object, got {type(parsed).__name__}.")
            return parsed
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON object from llama.cpp response: {exc}") from exc

    @staticmethod
    def llama_cpp_generate_json_response(
        prompt: str,
        model: str = "local",
        temperature: float = 0.2,
    ) -> dict | None:
        """Ask llama.cpp for a JSON move response and fail when the request or parse fails."""
        raw_output = LLM._generate_text(prompt=prompt, model=model, temperature=temperature)
        return LLM._extract_first_json_object(raw_output)

    @staticmethod
    def llama_cpp_generate_strict_json(
        prompt: str,
        model: str = "local",
        temperature: float = 0.1,
    ) -> dict | None:
        """Ask llama.cpp for one strict JSON object and fail when the call is invalid."""
        raw_output = LLM._generate_text(prompt=prompt, model=model, temperature=temperature)
        return LLM._extract_first_json_object(raw_output)

    @staticmethod
    def llama_cpp_generate_surrogate_strategy_spec(
        strategy_prompt: str,
        model: str = "local",
        temperature: float = 0.1,
    ) -> dict:
        """Convert a strategy prompt into a constrained eaglePolicy spec."""
        generation_prompt = f"""
        You are translating an RTS strategy prompt into a deterministic eaglePolicy configuration.

        Your job is to STRICTLY follow the strategy prompt and convert only explicitly supported behaviors into the schema below.
        Do not invent tactics that are not grounded in the prompt.
        If the prompt does not clearly justify a behavior, keep the conservative default.

        Supported schema and rules:
        {{
          "enabled": boolean,
          "worker_target_before_barracks": integer,
          "worker_target_after_barracks": integer,
          "harvester_target": integer,
          "desired_barracks": integer,
          "worker_harass_enabled": boolean,
          "attack_workers_first": boolean,
          "attack_structures_first": boolean,
          "protect_barracks": boolean,
          "min_lights": integer,
          "min_ranged": integer,
          "min_heavies": integer,
          "production_priority": ["light" | "ranged" | "heavy", ...]
        }}

        Mapping guidance:
        - "enabled" should be true when the strategy prompt contains actionable strategy content.
        - Use small stable integers only. Keep worker/harvester counts in the 0..6 range and desired_barracks in the 0..2 range.
        - Only set worker_harass_enabled if the prompt clearly wants workers to pressure, scout-harass, or punish exposed workers.
        - Only set attack_structures_first if the prompt clearly prioritizes production buildings or bases.
        - Only set protect_barracks if the prompt explicitly says to keep barracks safe or defend production.
        - "production_priority" must include only the unit types explicitly supported by the prompt. Preserve prompt order when clear.
        - If a unit type is mentioned as something to train, set its corresponding min_* to at least 1.
        - If the prompt is vague, return conservative values instead of guessing.

        Output rules:
        - Return JSON only.
        - Do not include explanations.
        - Do not include fields outside the schema.

        Strategy prompt:
        {strategy_prompt}
        """.strip()

        fallback = {
            "enabled": False,
            "worker_target_before_barracks": 0,
            "worker_target_after_barracks": 0,
            "harvester_target": 0,
            "desired_barracks": 0,
            "worker_harass_enabled": False,
            "attack_workers_first": False,
            "attack_structures_first": False,
            "protect_barracks": False,
            "min_lights": 0,
            "min_ranged": 0,
            "min_heavies": 0,
            "production_priority": [],
        }

        raw_output = LLM._generate_text(prompt=generation_prompt, model=model, temperature=temperature)
        parsed = LLM._extract_first_json_object(raw_output)
        return LLM._normalize_surrogate_strategy_spec(parsed, fallback)

    @staticmethod
    def _normalize_surrogate_strategy_spec(spec: dict, fallback: dict | None = None) -> dict:
        """Clamp one generated surrogate strategy spec into the supported stable schema."""
        fallback = dict(fallback or {})

        def clamp_int(key: str, minimum: int, maximum: int) -> int:
            """Clamp one integer field from a generated surrogate spec."""
            try:
                value = int(spec.get(key, fallback.get(key, minimum)))
            except (TypeError, ValueError):
                value = int(fallback.get(key, minimum))
            return max(minimum, min(maximum, value))

        normalized = {
            "enabled": bool(spec.get("enabled", fallback.get("enabled", False))),
            "worker_target_before_barracks": clamp_int("worker_target_before_barracks", 0, 6),
            "worker_target_after_barracks": clamp_int("worker_target_after_barracks", 0, 6),
            "harvester_target": clamp_int("harvester_target", 0, 6),
            "desired_barracks": clamp_int("desired_barracks", 0, 2),
            "worker_harass_enabled": bool(spec.get("worker_harass_enabled", fallback.get("worker_harass_enabled", False))),
            "attack_workers_first": bool(spec.get("attack_workers_first", fallback.get("attack_workers_first", False))),
            "attack_structures_first": bool(spec.get("attack_structures_first", fallback.get("attack_structures_first", False))),
            "protect_barracks": bool(spec.get("protect_barracks", fallback.get("protect_barracks", False))),
            "min_lights": clamp_int("min_lights", 0, 10),
            "min_ranged": clamp_int("min_ranged", 0, 10),
            "min_heavies": clamp_int("min_heavies", 0, 10),
            "production_priority": [],
        }

        allowed_types = {"light", "ranged", "heavy"}
        for raw_value in spec.get("production_priority", fallback.get("production_priority", [])) or []:
            name = str(raw_value).strip().lower()
            if name in allowed_types and name not in normalized["production_priority"]:
                normalized["production_priority"].append(name)

        if not normalized["enabled"]:
            return fallback

        if normalized["worker_target_after_barracks"] < normalized["worker_target_before_barracks"]:
            normalized["worker_target_after_barracks"] = normalized["worker_target_before_barracks"]

        return normalized

    @staticmethod
    def llama_cpp_rewrite_component(
            original_text: str,
            instruction: str,
            model: str = "local",
            temperature: float = 0.7,
        ) -> str:
        """Rewrite one prompt component using an instruction-guided LLM call."""
        prompt = f"""
        You are rewriting one component of a prompt for an RTS game-playing agent.

        Requirements:
        - Preserve the original semantic intent unless the instruction explicitly changes it.
        - Return ONLY the rewritten component text.
        - Do not add explanations, bullets, or quotation marks.

        Rewrite instruction:
        {instruction}

        Original component:
        {original_text}
        """.strip()

        return LLM._generate_text(prompt=prompt, model=model, temperature=temperature)
    
    @staticmethod
    def llama_cpp_combine_components(
            component1: str,
            component2: str,
            instruction: str,
            model: str = "local",
            temperature: float = 0.7,
        ) -> str:
        """Merge two component texts into one combined component suggestion."""
        prompt = f"""
        You are combining two components of a prompt for an RTS game-playing agent.

        Requirements:
        - Integrate the key elements of both components while following the instruction.
        - Ensure the combined component is coherent and maintains the original intent.
        - Return ONLY the combined component text without explanations or formatting.

        Combine instruction:
        {instruction}

        Component 1:
        {component1}

        Component 2:
        {component2}
        """.strip()

        return LLM._generate_text(prompt=prompt, model=model, temperature=temperature)


    @staticmethod
    def llama_cpp_evaluate_fitness(
        prompt: str,
        example=None,
        model: str = "local",
    ) -> list[float]:
        """Score a prompt with the prompt-only surrogate evaluator."""
        if example is None:
            example = []

        example_str = "\n\n".join(
            [f"Input:\n{inp}\nOutput:\n{out}" for inp, out in example]
        )

        evaluation_prompt = f"""
        You are evaluating a prompt used to instruct an LLM-based MicroRTS agent.

        Your task is NOT to assume the agent will win just because the prompt sounds strategic.
        You must be conservative.

        Evaluate the prompt on the following four dimensions:

        1. estimated_power:
        - Estimate how likely this prompt is to produce useful in-game decisions in MicroRTS.
        - Consider whether it gives actionable, executable, and game-relevant guidance.
        - Do NOT assume high power unless the prompt contains concrete and operational strategy guidance.
        - Score between 0 and 1.

        2. uncertainty:
        - Estimate how uncertain you are about the power prediction based on prompt text alone.
        - High uncertainty means the prompt might sound good but there is insufficient evidence that it will perform well in practice.
        - Score between 0 and 1, where 1 means highly uncertain.

        3. simplicity:
        - Is the prompt concise and free of unnecessary wording?
        - Score between 0 and 1.

        4. clarity:
        - Is the prompt precise, unambiguous, and easy for an LLM to follow?
        - Score between 0 and 1.

        Scoring rules:
        - Be conservative.
        - Do not give estimated_power > 0.8 unless the prompt contains concrete operational instructions that are directly useful for MicroRTS decision-making.
        - If the prompt is vague, generic, verbose, or only superficially strategic, reduce estimated_power and increase uncertainty.
        - Use the full range of scores, but avoid extreme values unless strongly justified.
        - Output only a Python-style list:
        [estimated_power, uncertainty, simplicity, clarity]

        {example_str}

        Input:
        {prompt}
        Output:
        """.strip()

        def clamp01(x: float) -> float:
            """Clamp one parsed surrogate score into the valid [0, 1] range."""
            return max(0.0, min(1.0, float(x)))

        def normalize_fitness(values) -> list[float]:
            """Normalize parsed surrogate outputs to four bounded dimensions."""
            if not isinstance(values, (list, tuple)):
                raise ValueError(f"llama.cpp fitness response must be a list, got {type(values).__name__}.")

            values = list(values)

            if len(values) < 4:
                values = values + [0.0] * (4 - len(values))
            elif len(values) > 4:
                values = values[:4]

            normalized = [clamp01(v) for v in values]

            return normalized

        raw_output = LLM._generate_text(prompt=evaluation_prompt, model=model, temperature=0.2)

        try:
            parsed = ast.literal_eval(raw_output)
            return normalize_fitness(parsed)
        except (ValueError, SyntaxError):
            pass

        matches = re.findall(r"-?\d*\.\d+|-?\d+", raw_output)
        if matches:
            parsed = [float(x) for x in matches[:4]]
            return normalize_fitness(parsed)
        raise ValueError("llama.cpp fitness response did not contain parseable numeric scores.")

    @staticmethod
    def llama_cpp_evaluate_game_round_fitness(
        prompt: str,
        dynamic_prompt: str,
        example=None,
        model: str = "local",
    ) -> list[float]:
        """Score a prompt against one sampled Dynamic Prompt using the LLM surrogate."""
        if example is None:
            example = []

        example_str = "\n\n".join(
            [f"Prompt:\n{inp}\nObserved score:\n{out}" for inp, out in example]
        )

        evaluation_prompt = f"""
        You are evaluating a strategy prompt for an LLM-based MicroRTS agent on a single sampled game round.

        You are given:
        1. a strategy prompt
        2. one gameplay Dynamic Prompt captured from a previous MicroRTS log

        Be conservative. Judge whether the strategy prompt is likely to help the agent produce legal, relevant, and useful actions for THIS game state.

        Evaluate the prompt on these four dimensions:

        1. estimated_power:
        - How likely the prompt is to produce useful actions for this sampled game round.
        - Consider whether the strategy is actionable for the shown state.
        - Penalize prompts that are too generic, likely to reference unavailable units, or too vague to guide a concrete response.
        - Score between 0 and 1.

        2. uncertainty:
        - How uncertain you are about that estimate.
        - If the prompt is generic or weakly grounded in the shown state, uncertainty should be higher.
        - Score between 0 and 1.

        3. simplicity:
        - Is the prompt concise and not bloated?
        - Score between 0 and 1.

        4. clarity:
        - Is the prompt precise and easy for an LLM to follow in this game round?
        - Score between 0 and 1.

        Output only a Python-style list:
        [estimated_power, uncertainty, simplicity, clarity]

        {example_str}

        Strategy Prompt:
        {prompt}

        Sampled Dynamic Prompt:
        {dynamic_prompt}

        Output:
        """.strip()

        def clamp01(x: float) -> float:
            """Clamp one parsed surrogate score into the valid [0, 1] range."""
            return max(0.0, min(1.0, float(x)))

        def normalize_scores(values) -> list[float]:
            """Normalize parsed game-round surrogate outputs into four bounded values."""
            if not isinstance(values, (list, tuple)):
                raise ValueError(f"llama.cpp round fitness response must be a list, got {type(values).__name__}.")

            values = list(values)
            if len(values) < 4:
                values = values + [0.0] * (4 - len(values))
            elif len(values) > 4:
                values = values[:4]

            return [clamp01(v) for v in values]

        raw_output = LLM._generate_text(prompt=evaluation_prompt, model=model, temperature=0.2)

        try:
            parsed = ast.literal_eval(raw_output)
            return normalize_scores(parsed)
        except (ValueError, SyntaxError):
            pass

        matches = re.findall(r"-?\d*\.\d+|-?\d+", raw_output)
        if matches:
            parsed = [float(x) for x in matches[:4]]
            return normalize_scores(parsed)
        raise ValueError("llama.cpp round fitness response did not contain parseable numeric scores.")
