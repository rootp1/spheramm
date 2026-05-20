from __future__ import annotations

import random
from typing import Dict, Tuple

from .config import MarketConfig


def update_oracle(oracle: Dict[str, float], prev: Dict[str, float], rng: random.Random, cfg: MarketConfig) -> Dict[str, float]:
  out = dict(oracle)
  if cfg.regime == "random_market":
    for a in out:
      out[a] = max(0.2, out[a] * (1 + rng.uniform(-0.010, 0.010)))
    return out

  if cfg.regime == "correlated_basket":
    common = rng.uniform(-0.007, 0.007)
    for a in out:
      out[a] = max(0.2, out[a] * (1 + common + rng.uniform(-0.0015, 0.0015)))
    return out

  if cfg.regime == "volatile_divergent":
    out["A"] = max(0.2, out["A"] * (1 + rng.uniform(-0.020, 0.024)))
    out["B"] = max(0.2, out["B"] * (1 + rng.uniform(-0.024, 0.020)))
    out["C"] = max(0.2, out["C"] * (1 + rng.uniform(-0.028, 0.028)))
    return out

  if cfg.regime == "liquidity_fragmentation":
    # moderate prices; flow fragmentation comes from routing demands, not extreme price shocks
    for a in out:
      out[a] = max(0.2, out[a] * (1 + rng.uniform(-0.006, 0.006)))
    return out

  if cfg.regime == "crisis_bank_run":
    # progressive collapse of asset A with contagion
    step_down = -0.030 if rng.random() < 0.35 else rng.uniform(-0.012, -0.002)
    out["A"] = max(0.2, out["A"] * (1 + step_down))
    out["B"] = max(0.2, out["B"] * (1 + rng.uniform(-0.012, 0.004)))
    out["C"] = max(0.2, out["C"] * (1 + rng.uniform(-0.010, 0.005)))
    return out

  return out


def preferred_direction(prev: Dict[str, float], now: Dict[str, float]) -> Tuple[str, str]:
  perf = {a: now[a] / max(1e-9, prev[a]) for a in now}
  ain = min(perf, key=perf.get)
  aout = max(perf, key=perf.get)
  return ain, aout

