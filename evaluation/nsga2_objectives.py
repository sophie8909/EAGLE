"""Convert pipeline results into NSGA-II objective values."""
from __future__ import annotations
from .code_quality import CodeQualityBreakdown
from .game_metrics import GameMetrics
FAILED_GAME_PERFORMANCE=-1000.0
OBJECTIVE_DIRECTIONS={"game_performance":"maximize","code_quality":"maximize"}

def build_objectives(*,game_metrics:GameMetrics|None,code_quality:CodeQualityBreakdown,game_failure:bool=False)->dict[str,float]:
    return {"game_performance":FAILED_GAME_PERFORMANCE if game_failure or game_metrics is None else float(game_metrics.objective),"code_quality":float(code_quality.code_quality)}
