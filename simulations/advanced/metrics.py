from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from .agents import AgentEvent


@dataclass
class Snapshot:
  step: int
  regime: str
  oracle_a: float
  oracle_b: float
  oracle_c: float
  pair_a: int
  pair_b: int
  pair_c: int
  geo_a: int
  geo_b: int
  geo_c: int
  pair_tvl: float
  geo_tvl: float
  pair_dom_bps: int
  geo_dom_bps: int
  pair_imb_bps: int
  geo_imb_bps: int
  geo_fee_proxy: float
  pair_fee_proxy: float
  lp_geo_weight: float
  coupling_intensity_proxy: float
  curvature_region_bps: int


def percentile(values: List[float], q: float) -> float:
  if not values:
    return 0.0
  s = sorted(values)
  i = int((len(s) - 1) * q)
  return float(s[i])


def summarize(events: List[AgentEvent], snaps: List[Snapshot]) -> List[Dict[str, float]]:
  pair = [e for e in events if e.system == "pairwise" and e.ok == 1]
  geo = [e for e in events if e.system == "geometric" and e.ok == 1]
  pair_sl = [e.slippage_pct for e in pair]
  geo_sl = [e.slippage_pct for e in geo]
  pair_whale = [e.slippage_pct for e in pair if e.agent == "whale"]
  geo_whale = [e.slippage_pct for e in geo if e.agent == "whale"]
  pair_arb_pnl = sum(e.pnl_value for e in events if e.system == "pairwise" and e.agent == "arbitrage")
  geo_arb_pnl = sum(e.pnl_value for e in events if e.system == "geometric" and e.agent == "arbitrage")
  pair_exec = [e.execution_quality for e in pair if e.execution_quality > 0]
  geo_exec = [e.execution_quality for e in geo if e.execution_quality > 0]
  avg = lambda xs: float(sum(xs) / max(1, len(xs)))

  final = snaps[-1]
  out: List[Dict[str, float]] = [
    {"metric": "avg_slippage_pair_pct", "value": avg(pair_sl)},
    {"metric": "avg_slippage_geo_pct", "value": avg(geo_sl)},
    {"metric": "tail_slippage_pair_p95_pct", "value": percentile(pair_sl, 0.95)},
    {"metric": "tail_slippage_geo_p95_pct", "value": percentile(geo_sl, 0.95)},
    {"metric": "whale_slippage_pair_pct", "value": avg(pair_whale)},
    {"metric": "whale_slippage_geo_pct", "value": avg(geo_whale)},
    {"metric": "avg_execution_quality_pair", "value": avg(pair_exec)},
    {"metric": "avg_execution_quality_geo", "value": avg(geo_exec)},
    {"metric": "arb_pnl_pair", "value": pair_arb_pnl},
    {"metric": "arb_pnl_geo", "value": geo_arb_pnl},
    {"metric": "final_pair_tvl", "value": final.pair_tvl},
    {"metric": "final_geo_tvl", "value": final.geo_tvl},
    {"metric": "avg_pair_dominance_bps", "value": avg([s.pair_dom_bps for s in snaps])},
    {"metric": "avg_geo_dominance_bps", "value": avg([s.geo_dom_bps for s in snaps])},
    {"metric": "avg_pair_imbalance_bps", "value": avg([s.pair_imb_bps for s in snaps])},
    {"metric": "avg_geo_imbalance_bps", "value": avg([s.geo_imb_bps for s in snaps])},
    {"metric": "avg_geo_coupling_intensity_proxy", "value": avg([s.coupling_intensity_proxy for s in snaps])},
    {"metric": "avg_lp_geo_weight", "value": avg([s.lp_geo_weight for s in snaps])},
    {"metric": "routing_overhead_pair", "value": avg([e.hop_count for e in events if e.system == "pairwise" and e.agent == "basket"])},
    {"metric": "routing_overhead_geo", "value": avg([e.hop_count for e in events if e.system == "geometric" and e.agent == "basket"])},
    {"metric": "reserve_collapse_pair", "value": float(min(final.pair_a, final.pair_b, final.pair_c) < 10_000)},
    {"metric": "reserve_collapse_geo", "value": float(min(final.geo_a, final.geo_b, final.geo_c) < 10_000)},
  ]
  return out

