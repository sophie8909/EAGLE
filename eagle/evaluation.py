"""Candidate evaluation for generated-agent searches."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from evaluation.code_quality import CodeQualityBreakdown, StrategyRegionScoreResult, analyze_compilation, build_code_quality
from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.game_performance import GamePerformanceConfig
from evaluation.game_metrics import GameMetrics, compute_game_metrics
from evaluation.microrts_runner import MatchResult, run_microrts_match
from evaluation.nsga2_objectives import build_objectives
from generation.agent_template import JavaTemplatePaths
from generation.backend import GenerationBackend
from generation.java_agent_generator import GeneratedJavaAgent, ValidationResult, generate_java_agent_result
from .artifacts import append_result, write_candidate_artifacts
from .candidate import Candidate
from .config import ExperimentConfig

@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate; result: "CandidateResult"; agent: GeneratedJavaAgent|None; compile_result: CompileResult|None
    match_results: list[MatchResult]; game_metrics: GameMetrics|None; strategy_consistency_result: object|None
    code_quality_breakdown: CodeQualityBreakdown; strategy_region_score_result: StrategyRegionScoreResult|None; error: str|None=None

@dataclass(frozen=True)
class CandidateResult:
    candidate_id:str; parent_ids:tuple[str,...]; raw_llm_output:str=""; extracted_code:str=""; assembled_java:str=""
    strategy_region:str=""; validation_result:ValidationResult|None=None
    strategy_region_validation:dict[str,dict]|None=None; compile_result:CompileResult|None=None; strategy_consistency:dict|None=None
    code_quality_breakdown:dict|None=None; match_result:list[MatchResult]|None=None; game_metrics:dict[str,object]|None=None
    final_score:dict[str,float]|None=None; failure_category:str|None=None; failure_reason:str|None=None

def evaluate_population(population:list[Candidate],*,generation:int,config:ExperimentConfig,backend:GenerationBackend,generated_agents_dir:Path,classes_dir:Path,candidates_dir:Path,results_path:Path,mock:bool)->list[Candidate]:
    evaluated=[]
    for index,candidate in enumerate(population):
        evaluation=evaluate_candidate(candidate,config=config,backend=backend,generated_agents_dir=generated_agents_dir,classes_dir=classes_dir,match_artifacts_dir=candidates_dir/candidate.id/"matches",mock=mock,ordinal=index)
        write_candidate_artifacts(candidates_dir,evaluation); append_result(results_path,evaluation); evaluated.append(evaluation.candidate)
        print_progress(generation=generation,index=index,population_size=len(population),evaluation=evaluation)
    return evaluated

def evaluate_candidate(candidate:Candidate,*,config:ExperimentConfig,backend:GenerationBackend,generated_agents_dir:Path,classes_dir:Path,mock:bool,ordinal:int,match_artifacts_dir:Path|None=None)->CandidateEvaluation:
    generation=generate_java_agent_result(candidate,backend,generated_agents_dir,template_paths=JavaTemplatePaths(config.agent_template_path))
    agent=generation.agent; region_score=generation.strategy_region_score_result
    if region_score is None:
        from evaluation.code_quality import evaluate_agent_strategy_region
        region_score=evaluate_agent_strategy_region("",error=generation.failure_reason or "Complete Java validation did not run.")
    compile_result=None; compile_error=None
    if agent is not None:
        try: compile_result=compile_agent_source(agent,config=config,classes_dir=classes_dir,candidate_id=candidate.id,mock=mock)
        except (RuntimeError,OSError,ValueError) as exc: compile_error=str(exc)
    compiler=analyze_compilation(compile_result)
    # Code quality is deterministic and makes no evaluator LLM call.
    quality=build_code_quality(compiler,region_score,{"agent_strategy_region":generation.strategy_region} if generation.strategy_region else {})
    matches=[]; game_metrics=None; match_error=None
    if compiler.compile_success and agent is not None:
        matches,match_error=evaluate_matches(candidate=candidate,agent=agent,config=config,classes_dir=classes_dir,match_artifacts_dir=match_artifacts_dir,mock=mock,ordinal=ordinal)
        if not match_error: game_metrics=compute_game_metrics(matches)
    game_failure=not compiler.compile_success or match_error is not None
    if game_failure: game_metrics=compute_game_metrics([])
    failure_category=None; failure_reason=None
    if generation.failure_category and agent is None: failure_category=generation.failure_category; failure_reason=generation.failure_reason
    elif not compiler.compile_success: failure_category="Java compile failure"; failure_reason=(compile_error or compile_error_message(compile_result)) if compile_result else (compile_error or "Compilation was not run.")
    elif match_error: failure_category=match_failure_category(match_error); failure_reason=match_error
    objectives=build_objectives(game_metrics=game_metrics,code_quality=quality,game_failure=game_failure)
    quality_payload={"code_quality":quality.code_quality,"code_quality_breakdown":quality.to_json_dict(),"strategy_consistency":None,"strategy_region_validation":region_score.to_json_dict()}
    evaluated_candidate=Candidate(id=candidate.id,generation=candidate.generation,parent_ids=candidate.parent_ids,strategy_prompt=candidate.strategy_prompt,previous_code=agent.behavior_source if agent else generation.assembled_java or candidate.previous_code,generation_prompt=candidate.generation_prompt,generated_java_agent_path=str(agent.source_path) if agent else None,compile_status=compile_result.status if compile_result else "not_run",game_eval_result=game_metrics.to_json_dict() if game_metrics else {},code_quality_result=quality_payload,fitness_objectives=objectives,status="failed" if failure_category else "evaluated",metadata={**candidate.metadata,"failure_category":failure_category,"failure_reason":failure_reason})
    result=CandidateResult(candidate.id,candidate.parent_ids,generation.raw_llm_output,generation.extracted_code,generation.assembled_java,generation.strategy_region,generation.validation_result,{k:v.to_json_dict() for k,v in region_score.strategy_region_validation.items()},compile_result,None,quality.to_json_dict(),matches,game_metrics.to_json_dict() if game_metrics else None,objectives,failure_category,failure_reason)
    return CandidateEvaluation(evaluated_candidate,result,agent,compile_result,matches,game_metrics,None,quality,region_score,failure_reason)
def compile_agent_source(
    agent: GeneratedJavaAgent,
    *,
    config: ExperimentConfig,
    classes_dir: Path,
    candidate_id: str,
    mock: bool,
) -> CompileResult:
    return compile_generated_agent(
        agent.source_paths,
        microrts_dir=config.microrts_dir,
        output_dir=classes_dir / candidate_id,
        mock=mock,
    )


def evaluate_matches(
    *,
    candidate: Candidate,
    agent: GeneratedJavaAgent,
    config: ExperimentConfig,
    classes_dir: Path,
    match_artifacts_dir: Path | None,
    mock: bool,
    ordinal: int,
) -> tuple[list[MatchResult], str | None]:
    match_results: list[MatchResult] = []
    try:
        for match_index in range(config.matches_per_candidate):
            match_results.append(
                run_microrts_match(
                    microrts_dir=config.microrts_dir,
                    classes_dir=classes_dir / candidate.id,
                    agent_class=agent.qualified_class_name,
                    opponent=config.opponent,
                    tick_limit=config.tick_limit,
                    match_index=match_index,
                    match_artifacts_dir=match_artifacts_dir,
                    scoring_config=scoring_config_from_experiment(config),
                    mock=mock,
                    mock_score=config.mock_score_base + config.mock_score_step * (ordinal + match_index),
                )
            )
    except (RuntimeError, OSError) as exc:
        return match_results, str(exc)

    failed_matches = [result for result in match_results if not result.ok]
    if failed_matches:
        return match_results, match_error_message(failed_matches[0])
    return match_results, None


def scoring_config_from_experiment(config: ExperimentConfig) -> GamePerformanceConfig:
    return GamePerformanceConfig(
        result_win_score=config.result_win_score,
        result_draw_score=config.result_draw_score,
        result_loss_score=config.result_loss_score,
        army_weight=config.state_army_weight,
        building_weight=config.state_building_weight,
        resource_weight=config.state_resource_weight,
        survival_weight=config.survival_weight,
        final_resource_weight=config.final_resource_weight,
    )


def compile_error_message(result: CompileResult) -> str:
    stderr = (result.stderr or "").strip()
    if stderr:
        return stderr.splitlines()[0]
    return f"javac returned {result.returncode}"


def match_error_message(result: MatchResult) -> str:
    stderr = (result.stderr or "").strip()
    if stderr:
        return stderr.splitlines()[0]
    return f"match returned {result.returncode}"


def match_failure_category(reason: str) -> str:
    lowered = reason.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "Timeout"
    return "Runtime match failure"


def print_progress(
    *,
    generation: int,
    index: int,
    population_size: int,
    evaluation: CandidateEvaluation,
) -> None:
    candidate = evaluation.candidate
    quality = evaluation.code_quality_breakdown
    detail = ""
    if evaluation.error:
        detail = f" error={evaluation.error}"
    elif evaluation.compile_result is not None and not evaluation.compile_result.ok:
        stderr = (evaluation.compile_result.stderr or "").splitlines()
        detail = f" compile_error={stderr[0] if stderr else evaluation.compile_result.returncode}"
    print(
        f"[gen {generation} cand {index + 1}/{population_size}] "
        f"{candidate.id} status={candidate.status} "
        f"objectives={candidate.fitness_objectives} "
        f"code_quality_total={quality.code_quality} "
        f"code_quality_components=("
        f"compilation={quality.compilation_score} + "
        f"strategy_region={quality.strategy_region_score} + "
        f"static={quality.static_quality_score} = "
        f"{quality.code_quality}){detail}",
        flush=True,
    )
