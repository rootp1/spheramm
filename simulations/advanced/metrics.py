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
  lgeo_a: int
  lgeo_b: int
  lgeo_c: int
  pair_tvl: float
  geo_tvl: float
  lgeo_tvl: float
  pair_dom_bps: int
  geo_dom_bps: int
  lgeo_dom_bps: int
  pair_imb_bps: int
  geo_imb_bps: int
  lgeo_imb_bps: int
  geo_fee_proxy: float
  lgeo_fee_proxy: float
  pair_fee_proxy: float
  lp_geo_weight: float
  lp_lgeo_weight: float
  coupling_intensity_proxy: float
  curvature_region_bps: int
  reserve_tension_bps: int
  center_amplification_bps: int
  stress_memory_bps: int


def percentile(values: List[float], q: float) -> float:
  if not values:
    return 0.0
  s = sorted(values)
  i = int((len(s) - 1) * q)
  return float(s[i])


def summarize(events: List[AgentEvent], snaps: List[Snapshot]) -> List[Dict[str, float]]:
  pair = [e for e in events if e.system == "pairwise" and e.ok == 1]
  geo = [e for e in events if e.system == "geometric" and e.ok == 1]
  lgeo = [e for e in events if e.system == "localized_geometric" and e.ok == 1]
  pair_sl = [e.slippage_pct for e in pair]
  geo_sl = [e.slippage_pct for e in geo]
  lgeo_sl = [e.slippage_pct for e in lgeo]
  pair_whale = [e.slippage_pct for e in pair if e.agent == "whale"]
  geo_whale = [e.slippage_pct for e in geo if e.agent == "whale"]
  lgeo_whale = [e.slippage_pct for e in lgeo if e.agent == "whale"]
  pair_arb_pnl = sum(e.pnl_value for e in events if e.system == "pairwise" and e.agent == "arbitrage")
  geo_arb_pnl = sum(e.pnl_value for e in events if e.system == "geometric" and e.agent == "arbitrage")
  lgeo_arb_pnl = sum(e.pnl_value for e in events if e.system == "localized_geometric" and e.agent == "arbitrage")
  pair_exec = [e.execution_quality for e in pair if e.execution_quality > 0]
  geo_exec = [e.execution_quality for e in geo if e.execution_quality > 0]
  lgeo_exec = [e.execution_quality for e in lgeo if e.execution_quality > 0]
  avg = lambda xs: float(sum(xs) / max(1, len(xs)))

  final = snaps[-1]
  out: List[Dict[str, float]] = [
    {"metric": "avg_slippage_pair_pct", "value": avg(pair_sl)},
    {"metric": "avg_slippage_geo_pct", "value": avg(geo_sl)},
    {"metric": "avg_slippage_lgeo_pct", "value": avg(lgeo_sl)},
    {"metric": "tail_slippage_pair_p95_pct", "value": percentile(pair_sl, 0.95)},
    {"metric": "tail_slippage_geo_p95_pct", "value": percentile(geo_sl, 0.95)},
    {"metric": "tail_slippage_lgeo_p95_pct", "value": percentile(lgeo_sl, 0.95)},
    {"metric": "whale_slippage_pair_pct", "value": avg(pair_whale)},
    {"metric": "whale_slippage_geo_pct", "value": avg(geo_whale)},
    {"metric": "whale_slippage_lgeo_pct", "value": avg(lgeo_whale)},
    {"metric": "avg_execution_quality_pair", "value": avg(pair_exec)},
    {"metric": "avg_execution_quality_geo", "value": avg(geo_exec)},
    {"metric": "avg_execution_quality_lgeo", "value": avg(lgeo_exec)},
    {"metric": "arb_pnl_pair", "value": pair_arb_pnl},
    {"metric": "arb_pnl_geo", "value": geo_arb_pnl},
    {"metric": "arb_pnl_lgeo", "value": lgeo_arb_pnl},
    {"metric": "final_pair_tvl", "value": final.pair_tvl},
    {"metric": "final_geo_tvl", "value": final.geo_tvl},
    {"metric": "final_lgeo_tvl", "value": final.lgeo_tvl},
    {"metric": "avg_pair_dominance_bps", "value": avg([s.pair_dom_bps for s in snaps])},
    {"metric": "avg_geo_dominance_bps", "value": avg([s.geo_dom_bps for s in snaps])},
    {"metric": "avg_lgeo_dominance_bps", "value": avg([s.lgeo_dom_bps for s in snaps])},
    {"metric": "avg_pair_imbalance_bps", "value": avg([s.pair_imb_bps for s in snaps])},
    {"metric": "avg_geo_imbalance_bps", "value": avg([s.geo_imb_bps for s in snaps])},
    {"metric": "avg_lgeo_imbalance_bps", "value": avg([s.lgeo_imb_bps for s in snaps])},
    {"metric": "avg_geo_coupling_intensity_proxy", "value": avg([s.coupling_intensity_proxy for s in snaps])},
    {"metric": "avg_geo_reserve_tension_bps", "value": avg([s.reserve_tension_bps for s in snaps])},
    {"metric": "avg_geo_center_amplification_bps", "value": avg([s.center_amplification_bps for s in snaps])},
    {"metric": "avg_geo_stress_memory_bps", "value": avg([s.stress_memory_bps for s in snaps])},
    {"metric": "avg_lp_geo_weight", "value": avg([s.lp_geo_weight for s in snaps])},
    {"metric": "avg_lp_lgeo_weight", "value": avg([s.lp_lgeo_weight for s in snaps])},
    {"metric": "routing_overhead_pair", "value": avg([e.hop_count for e in events if e.system == "pairwise" and e.agent == "basket"])},
    {"metric": "routing_overhead_geo", "value": avg([e.hop_count for e in events if e.system == "geometric" and e.agent == "basket"])},
    {"metric": "routing_overhead_lgeo", "value": avg([e.hop_count for e in events if e.system == "localized_geometric" and e.agent == "basket"])},
    {"metric": "reserve_collapse_pair", "value": float(min(final.pair_a, final.pair_b, final.pair_c) < 10_000)},
    {"metric": "reserve_collapse_geo", "value": float(min(final.geo_a, final.geo_b, final.geo_c) < 10_000)},
    {"metric": "reserve_collapse_lgeo", "value": float(min(final.lgeo_a, final.lgeo_b, final.lgeo_c) < 10_000)},
  ]
  return out
