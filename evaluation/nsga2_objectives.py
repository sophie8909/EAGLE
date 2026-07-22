"""Convert pipeline results into NSGA-II objective values."""
from __future__ import annotations
from .code_quality import CodeQualityBreakdown
from .game_metrics import GameMetrics
FAILED_GAME_PERFORMANCE=-1000.0
WORST_GAME_OBJECTIVE=-1.0
OBJECTIVE_DIRECTIONS={"game_performance":"maximize","code_quality":"maximize"}

def build_objectives(*,game_metrics:GameMetrics|None,code_quality:CodeQualityBreakdown,game_failure:bool=False)->dict[str,float]:
    return {"game_performance":FAILED_GAME_PERFORMANCE if game_failure else float(game_metrics.objective if game_metrics else WORST_GAME_OBJECTIVE),"code_quality":float(code_quality.code_quality)}
