from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from run_simulation import SimConfig, run


def read_summary(path: Path) -> dict[str, float]:
  out: dict[str, float] = {}
  with path.open() as f:
    r = csv.DictReader(f)
    for row in r:
      try:
        out[row["metric"]] = float(row["value"])
      except Exception:
        pass
  return out


def main() -> None:
  roots = Path("simulations") / "outputs"
  sweep_out = roots / f"sweep_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
  sweep_out.mkdir(parents=True, exist_ok=True)

  configs: list[SimConfig] = []
  for center in (3200, 3800, 4200, 4800):
    for edge in (1000, 1400, 1800):
      for divisor in (35, 40, 50):
        configs.append(
          SimConfig(
            seed=42,
            steps=1200,
            curvature_center_bps=center,
            curvature_edge_bps=edge,
            coupling_base_divisor=divisor,
          )
        )

  rows: list[dict[str, float | int]] = []
  for i, cfg in enumerate(configs):
    out_dir = run(cfg)
    summary = read_summary(out_dir / "summary_metrics.csv")
    rows.append(
      {
        "run_idx": i,
        "center_bps": cfg.curvature_center_bps,
        "edge_bps": cfg.curvature_edge_bps,
        "coupling_divisor": cfg.coupling_base_divisor,
        "avg_slippage_pair": summary.get("avg_trader_slippage_pair_pct", 0.0),
        "avg_slippage_geo": summary.get("avg_trader_slippage_geo_pct", 0.0),
        "final_lp_pair": summary.get("final_pair_lp_growth", 0.0),
        "final_lp_geo": summary.get("final_geo_lp_growth", 0.0),
        "arb_pnl_pair": summary.get("arb_profit_pair", 0.0),
        "arb_pnl_geo": summary.get("arb_profit_geo", 0.0),
        "geo_dominance_avg": summary.get("avg_geo_dominance_bps", 0.0),
        "geo_cap_eff": summary.get("capital_efficiency_geo_max_amt_at_15pct_slippage", 0.0),
      }
    )

  out_csv = sweep_out / "sweep_results.csv"
  with out_csv.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

  ranked = sorted(
    rows,
    key=lambda r: (
      r["avg_slippage_geo"] - r["avg_slippage_pair"],
      -(r["final_lp_geo"] - r["final_lp_pair"]),
      -(r["arb_pnl_geo"] - r["arb_pnl_pair"]),
    ),
  )
  best_csv = sweep_out / "top_candidates.csv"
  with best_csv.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(ranked[0].keys()))
    w.writeheader()
    w.writerows(ranked[:10])

  print(f"Sweep complete: {sweep_out}")


if __name__ == "__main__":
  main()
