from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List

from .config import AgentConfig, MarketConfig, RegimeName
from .run_advanced import run_experiment


REGIMES: List[RegimeName] = [
  "random_market",
  "correlated_basket",
  "volatile_divergent",
  "liquidity_fragmentation",
  "crisis_bank_run",
]


def read_summary(path: Path) -> Dict[str, float]:
  out: Dict[str, float] = {}
  with path.open() as f:
    r = csv.DictReader(f)
    for row in r:
      out[row["metric"]] = float(row["value"])
  return out


def main() -> None:
  root = Path("simulations") / "outputs"
  out_dir = root / f"advanced_sweep_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
  out_dir.mkdir(parents=True, exist_ok=True)
  rows: List[Dict] = []
  idx = 0
  for regime in REGIMES:
    for center in (3200, 3800, 4200, 5000):
      for edge in (1000, 1400, 1800):
        for div in (35, 40, 50):
          for amp in (1600, 2200, 3000):
            for tail in (2200, 2800, 3600):
              mcfg = MarketConfig(
                regime=regime,
                steps=1200,
                seed=42,
                geometric_center_curvature_bps=center,
                geometric_edge_curvature_bps=edge,
                geometric_coupling_divisor=div,
                equilibrium_amplification_bps=amp,
                tail_guard_bps=tail,
              )
              acfg = AgentConfig()
              run_path = run_experiment(mcfg, acfg)
              sm = read_summary(run_path / "summary.csv")
              rows.append(
                {
                  "run_idx": idx,
                  "regime": regime,
                  "center_bps": center,
                  "edge_bps": edge,
                  "coupling_div": div,
                  "eq_amp_bps": amp,
                  "tail_guard_bps": tail,
                  "avg_slippage_pair": sm.get("avg_slippage_pair_pct", 0),
                  "avg_slippage_geo": sm.get("avg_slippage_geo_pct", 0),
                  "avg_slippage_lgeo": sm.get("avg_slippage_lgeo_pct", 0),
                  "p95_slippage_pair": sm.get("tail_slippage_pair_p95_pct", 0),
                  "p95_slippage_geo": sm.get("tail_slippage_geo_p95_pct", 0),
                  "p95_slippage_lgeo": sm.get("tail_slippage_lgeo_p95_pct", 0),
                  "arb_pnl_pair": sm.get("arb_pnl_pair", 0),
                  "arb_pnl_geo": sm.get("arb_pnl_geo", 0),
                  "arb_pnl_lgeo": sm.get("arb_pnl_lgeo", 0),
                  "geo_dom": sm.get("avg_geo_dominance_bps", 0),
                  "lgeo_dom": sm.get("avg_lgeo_dominance_bps", 0),
                  "pair_dom": sm.get("avg_pair_dominance_bps", 0),
                  "lp_geo_weight": sm.get("avg_lp_geo_weight", 0),
                  "lp_lgeo_weight": sm.get("avg_lp_lgeo_weight", 0),
                  "geo_tension": sm.get("avg_geo_reserve_tension_bps", 0),
                }
              )
              idx += 1

  _write_csv(out_dir / "advanced_sweep_results.csv", rows)
  ranked = sorted(
    rows,
    key=lambda r: (
      (r["p95_slippage_lgeo"] - r["p95_slippage_pair"]),
      (r["p95_slippage_geo"] - r["p95_slippage_pair"]),
      (r["avg_slippage_lgeo"] - r["avg_slippage_pair"]),
      (r["avg_slippage_geo"] - r["avg_slippage_pair"]),
      -(r["arb_pnl_geo"] - r["arb_pnl_pair"]),
      -(r["arb_pnl_lgeo"] - r["arb_pnl_pair"]),
      -r["lp_lgeo_weight"],
      -r["lp_geo_weight"],
      r["geo_tension"],
    ),
  )
  _write_csv(out_dir / "top_regime_specialists.csv", ranked[:50])
  print(f"Advanced sweep output: {out_dir}")


def _write_csv(path: Path, rows: List[Dict]) -> None:
  if not rows:
    return
  with path.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)


if __name__ == "__main__":
  main()
