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

    Precedence: the automatic ceiling wins. Below it the result is never under
    the legacy ``floor + length bonus`` (so it is only ever more generous than
    before); the ceiling ``max(CPU_AUTO_CAP_S, floor)`` is applied to the FINAL
    value, so even a 500k-character single-shot job is bounded and a wedged
    engine is caught in finite time. Only automatic budgets are capped — an
    explicit user setting never reaches this function.
    """
    n = max(0, int(chars))
    legacy = floor + length_bonus_s(n)
    scaled = CPU_SECONDS_PER_CHAR * n
    return min(max(legacy, scaled), max(CPU_AUTO_CAP_S, floor))


#: Clients (the MCP tools, the desktop UI backstop) size their wait from the
#: text as the USER typed it, but the backend budgets the text after number
#: normalization, pronunciation rules and inline overrides — which can be
#: several times longer ("2024" becomes "two thousand twenty four"). A client
#: that budgets from the raw length can give up before the backend does.
TEXT_EXPANSION_FACTOR = 4


def client_execution_budget_s(floor: float, chars: int) -> float:
    """Upper bound of the execution budget the backend may grant ``chars`` raw
    characters, for any caller that cannot see the backend's final text.

    THE shared function for client-side waits (``mcp_server``; the TypeScript
    ``generateAbortMs`` mirrors it and is held equal by tests). ``floor`` is the
    largest execution base the backend could apply (accelerated, CPU, or a
    sidecar receive timeout). Covers both the legacy and the CPU-speed rule, so
    it is >= whatever ``model_manager.generate_timeout_s`` returns for any text
    that normalizes to at most ``TEXT_EXPANSION_FACTOR`` times ``chars``.
    """
    n = max(0, int(chars)) * TEXT_EXPANSION_FACTOR
    return max(floor + length_bonus_s(n), cpu_auto_budget_s(floor, n))
