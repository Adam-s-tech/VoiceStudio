"""Pure length-scaling arithmetic for the per-job generate compute budget.

Stdlib only, so ``services.model_manager`` (the real budget), the torch-free
``worker.deadlines`` fallback and the standalone ``mcp_server`` client timeout
all share ONE definition instead of each re-deriving it. They drifted apart
before (#1190/#1202), and a drifted copy means a tool or remote worker giving
up before the backend does.

Two scaling classes:

* **Accelerated / explicit** — the long-standing rule: the configured floor plus
  1 s per 40 characters past a 1200-character free allowance.
* **CPU, default budget** (#2609) — a CPU render is routinely 10-50x slower than
  realtime-on-GPU, so a flat 600 s floor plus a negligible length term
  abandoned healthy renders of an ordinary paragraph (a 6-core Ryzen on
  OmniVoice hit the 600 s wall with the worker still computing). The default
  CPU budget now grows with the input at ``CPU_SECONDS_PER_CHAR``, bounded by
  ``CPU_AUTO_CAP_S`` so a genuinely wedged engine is still caught in finite
  time. An EXPLICIT user setting never takes this path — it stays authoritative.
"""
from __future__ import annotations

#: Free character allowance before the legacy length bonus starts.
FREE_CHARS = 1200
#: Legacy length bonus: one extra second per this many characters.
CHARS_PER_SECOND = 40.0

#: Default CPU budget growth, seconds of compute allowed per input character.
CPU_SECONDS_PER_CHAR = 4.0
#: Hard ceiling for the AUTOMATIC CPU budget (2 h). Bounds a wedged job; a user
#: who needs longer sets the CPU budget explicitly in Settings.
CPU_AUTO_CAP_S = 7200.0


def length_bonus_s(chars: int) -> float:
    """Legacy bonus seconds for ``chars`` characters of input."""
    return max(0, int(chars) - FREE_CHARS) / CHARS_PER_SECOND


def cpu_auto_budget_s(floor: float, chars: int) -> float:
    """Default CPU execution budget for ``chars`` characters of input.

    Never below the legacy ``floor + length bonus`` (so it can only be more
    generous than before), never above ``max(CPU_AUTO_CAP_S, floor)``.
    """
    n = max(0, int(chars))
    legacy = floor + length_bonus_s(n)
    scaled = min(CPU_SECONDS_PER_CHAR * n, max(CPU_AUTO_CAP_S, floor))
    return max(legacy, scaled)
