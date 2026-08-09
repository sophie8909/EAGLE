# Reflection current state

The active Strategy Reflection path is the sports-team pipeline documented in
[`strategy-reflection.md`](strategy-reflection.md): Match Commentator, Manager,
Coach, then the existing Generator.

The old monolithic strategy reflector/re-writer path is no longer used for
Strategy Mutation. Code Reflection still owns implementation-level mutation and
continues to operate independently.

The evaluator remains authoritative for the fixed match roster, match count,
game-performance scoring, code-quality simplicity scoring, and NSGA-II
objectives. Strategy Reflection only consumes the resulting evidence and
changes `strategy_prompt`.

The temporary full match trace is deleted after terminal Commentator handling.
Compact results and role artifacts remain sufficient to reconstruct the
LLM-analysis chain without retaining raw tick logs.
