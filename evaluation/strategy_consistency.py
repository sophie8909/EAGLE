"""LLM judge for consistency between strategy text and generated behaviors."""
from __future__ import annotations
import json, re, urllib.error, urllib.request
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from eagle.llm_logging import LLMCallLogger

@dataclass(frozen=True)
class StrategyConsistencyResult:
    score: float | None
    reason: str
    raw_response: str = ""
    error: str | None = None
    def to_json_dict(self) -> dict[str, Any]: return asdict(self)

def parse_strategy_consistency(payload: dict[str, Any], raw: str = "") -> StrategyConsistencyResult:
    if "score" not in payload: raise ValueError("Strategy consistency response is missing score.")
    score = float(payload["score"])
    if not 0.0 <= score <= 10.0: raise ValueError("Strategy consistency score must be between 0 and 10.")
    reason = str(payload.get("reason", "")).strip()
    if not reason: raise ValueError("Strategy consistency response is missing reason.")
    return StrategyConsistencyResult(score, reason, raw)

def evaluate_strategy_consistency(*, strategy_prompt: str, generated_behavior_code: str, backend: str = "mock", base_url: str = "http://localhost:8080", model: str = "local-model", logger: LLMCallLogger | None = None, candidate_id: str | None = None, generation: int | None = None) -> StrategyConsistencyResult:
    if backend == "mock":
        prompt_terms=set(re.findall(r"[a-zA-Z]{4,}",strategy_prompt.lower())); code_terms=set(re.findall(r"[a-zA-Z]{4,}",generated_behavior_code.lower()))
        score=min(10.0,2.0+10.0*len(prompt_terms & code_terms)/max(8,len(prompt_terms) or 1))
        return StrategyConsistencyResult(round(score,2),"Mock judge measures strategy-term coverage across the complete behavior set.")
    if backend not in {"openai","llama_cpp"}: raise ValueError(f"Unknown strategy consistency backend: {backend}")
    url=base_url.rstrip("/"); url=f"{url}/chat/completions" if url.endswith("/v1") else f"{url}/v1/chat/completions"
    prompt=("Judge only strategy consistency. Return strict JSON with numeric score from 0 to 10 and reason. Evaluate whether all behavior functions implement one stated plan across production, resources, unit control, and attacks; identify contradictions or missing major parts. Do not judge Java formatting, compilation, warnings, style, or game performance.\n\nStrategy description:\n"+strategy_prompt+"\n\nGenerated behavior functions:\n"+generated_behavior_code)
    request=urllib.request.Request(url,data=json.dumps({"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0.0}).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=120) as response: response_text=response.read().decode()
        content=str(json.loads(response_text)["choices"][0]["message"]["content"]); parsed=_extract_json(content); result=parse_strategy_consistency(parsed,content)
    except Exception as exc:
        error=f"Strategy consistency judge failed: {exc}"; _log(logger,prompt,locals().get("content",locals().get("response_text","")),"error",model,candidate_id,generation,error,url); return StrategyConsistencyResult(None,"",locals().get("content",""),error)
    _log(logger,prompt,content,"success",model,candidate_id,generation,None,url); return result

def _extract_json(text: str) -> dict[str, Any]:
    try: return json.loads(text)
    except json.JSONDecodeError:
        match=re.search(r"\{.*\}",text,re.DOTALL)
        if not match: raise ValueError("response did not contain JSON")
        return json.loads(match.group(0))

def _log(logger,input_text,response_text,status,model,candidate_id,generation,error,url):
    if logger: logger.write(stage="strategy_consistency",input_text=input_text,response_text=response_text,status=status,backend="openai_compatible",model=model,candidate_id=candidate_id,generation=generation,attempt=1,error=error,metadata={"url":url})
