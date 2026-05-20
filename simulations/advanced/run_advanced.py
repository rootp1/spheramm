from __future__ import annotations

import argparse
import csv
import random
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List

from .agents import (
  AgentEvent,
  arbitrage_flow,
  basket_trader_flow,
  lp_allocation_flow,
  retail_flow,
  whale_stress_flow,
)
from .amm import GeometricAMM, PairwiseAMM, dominance_bps, imbalance_bps
from .config import AgentConfig, MarketConfig, RegimeName
from .metrics import Snapshot, summarize
from .regimes import update_oracle
from .visualize import build_dashboard_html


def run_experiment(mcfg: MarketConfig, acfg: AgentConfig) -> Path:
  rng = random.Random(mcfg.seed)
  pair = PairwiseAMM(mcfg.base_reserve, mcfg.pair_fee_bps)
  geo = GeometricAMM(
    reserve=mcfg.base_reserve,
    center_curvature_bps=mcfg.geometric_center_curvature_bps,
    edge_curvature_bps=mcfg.geometric_edge_curvature_bps,
    coupling_divisor=mcfg.geometric_coupling_divisor,
    imbalance_limit_bps=mcfg.geometric_imbalance_limit_bps,
  )
  oracle = {"A": 1.0, "B": 1.0, "C": 1.0}
  oracle_prev = dict(oracle)

  out_dir = Path("simulations") / "outputs" / f"advanced_{mcfg.regime}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
  out_dir.mkdir(parents=True, exist_ok=True)

  state = {"pair_fee_proxy": 0.0, "geo_fee_proxy": 0.0, "lp_geo_weight": 0.5}
  events: List[AgentEvent] = []
  snaps: List[Snapshot] = []

  for step in range(mcfg.steps):
    oracle_prev = oracle
    oracle = update_oracle(oracle, oracle_prev, rng, mcfg)
    step_events: List[AgentEvent] = []
    step_events += retail_flow(step, rng, oracle_prev, oracle, pair, geo, acfg, mcfg)
    step_events += basket_trader_flow(step, rng, oracle, pair, geo, acfg, mcfg)
    step_events += whale_stress_flow(step, rng, oracle_prev, oracle, pair, geo, acfg, mcfg)
    step_events += arbitrage_flow(step, rng, oracle, pair, geo, acfg)
    state["pair_fee_proxy"] += sum((e.amount_in * e.fee_bps / 10_000) for e in step_events if e.system == "pairwise" and e.ok == 1)
    state["geo_fee_proxy"] += sum((e.amount_in * e.fee_bps / 10_000) for e in step_events if e.system == "geometric" and e.ok == 1)
    step_events += lp_allocation_flow(step, rng, oracle, pair, geo, acfg, state)
    events.extend(step_events)

    pr = pair.reserves_total()
    gr = geo.reserves_total()
    gdom = dominance_bps(gr["A"], gr["B"], gr["C"])
    pdom = dominance_bps(pr["A"], pr["B"], pr["C"])
    snaps.append(
      Snapshot(
        step=step,
        regime=mcfg.regime,
        oracle_a=oracle["A"],
        oracle_b=oracle["B"],
        oracle_c=oracle["C"],
        pair_a=pr["A"],
        pair_b=pr["B"],
        pair_c=pr["C"],
        geo_a=gr["A"],
        geo_b=gr["B"],
        geo_c=gr["C"],
        pair_tvl=pair.tvl(oracle),
        geo_tvl=geo.tvl(oracle),
        pair_dom_bps=pdom,
        geo_dom_bps=gdom,
        pair_imb_bps=imbalance_bps(pr["A"], pr["B"], pr["C"]),
        geo_imb_bps=imbalance_bps(gr["A"], gr["B"], gr["C"]),
        geo_fee_proxy=state["geo_fee_proxy"],
        pair_fee_proxy=state["pair_fee_proxy"],
        lp_geo_weight=state["lp_geo_weight"],
        coupling_intensity_proxy=float(max(0, gdom - 3600)),
        curvature_region_bps=geo.curvature_bps(gdom),
      )
    )

  summary = summarize(events, snaps)
  _write_csv(out_dir / "events.csv", [asdict(e) for e in events])
  _write_csv(out_dir / "snapshots.csv", [asdict(s) for s in snaps])
  _write_csv(out_dir / "summary.csv", summary)
  build_dashboard_html(out_dir, snaps, events)
  _write_report(out_dir, mcfg, acfg, summary)
  print(f"Advanced simulation output: {out_dir}")
  return out_dir


def _write_csv(path: Path, rows: List[Dict]) -> None:
  if not rows:
    return
  with path.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)


def _write_report(out_dir: Path, mcfg: MarketConfig, acfg: AgentConfig, summary: List[Dict[str, float]]) -> None:
  sm = {r["metric"]: r["value"] for r in summary}
  text = f"""# Advanced Regime Report

Regime: `{mcfg.regime}`
Steps: `{mcfg.steps}`
Seed: `{mcfg.seed}`

## Core Findings

- Avg slippage pair: {sm.get('avg_slippage_pair_pct', 0):.4f}%
- Avg slippage geometric: {sm.get('avg_slippage_geo_pct', 0):.4f}%
- P95 slippage pair: {sm.get('tail_slippage_pair_p95_pct', 0):.4f}%
- P95 slippage geometric: {sm.get('tail_slippage_geo_p95_pct', 0):.4f}%
- Arbitrage PnL pair: {sm.get('arb_pnl_pair', 0):.2f}
- Arbitrage PnL geometric: {sm.get('arb_pnl_geo', 0):.2f}
- Avg dominance pair: {sm.get('avg_pair_dominance_bps', 0):.2f} bps
- Avg dominance geometric: {sm.get('avg_geo_dominance_bps', 0):.2f} bps
- Avg LP geo weight: {sm.get('avg_lp_geo_weight', 0):.4f}

## Interpretation

This run should be interpreted as a **regime-specific** result, not a universal ranking.
Use cross-regime sweeps to identify specialization domains.

Artifacts:
- `events.csv`
- `snapshots.csv`
- `summary.csv`
- `dashboard.html`
"""
  (out_dir / "report.md").write_text(text)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--regime", type=str, default="random_market")
  parser.add_argument("--steps", type=int, default=2500)
  parser.add_argument("--seed", type=int, default=42)
  args = parser.parse_args()
  regime: RegimeName = args.regime  # type: ignore[assignment]
  mcfg = MarketConfig(regime=regime, steps=args.steps, seed=args.seed)
  acfg = AgentConfig()
  run_experiment(mcfg, acfg)


if __name__ == "__main__":
  main()

