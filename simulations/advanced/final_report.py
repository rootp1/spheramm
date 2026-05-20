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


def _read_summary(path: Path) -> Dict[str, float]:
  out: Dict[str, float] = {}
  with path.open() as f:
    r = csv.DictReader(f)
    for row in r:
      out[row["metric"]] = float(row["value"])
  return out


def main() -> None:
  root = Path("simulations") / "outputs"
  out_dir = root / f"final_report_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
  out_dir.mkdir(parents=True, exist_ok=True)

  rows: List[Dict[str, float | str]] = []
  for regime in REGIMES:
    run_path = run_experiment(MarketConfig(regime=regime, steps=1200, seed=42), AgentConfig())
    sm = _read_summary(run_path / "summary.csv")
    rows.append(
      {
        "regime": regime,
        "slippage_pair": sm.get("avg_slippage_pair_pct", 0),
        "slippage_global_geo": sm.get("avg_slippage_geo_pct", 0),
        "slippage_localized_geo": sm.get("avg_slippage_lgeo_pct", 0),
        "p95_pair": sm.get("tail_slippage_pair_p95_pct", 0),
        "p95_global_geo": sm.get("tail_slippage_geo_p95_pct", 0),
        "p95_localized_geo": sm.get("tail_slippage_lgeo_p95_pct", 0),
        "arb_pair": sm.get("arb_pnl_pair", 0),
        "arb_global_geo": sm.get("arb_pnl_geo", 0),
        "arb_localized_geo": sm.get("arb_pnl_lgeo", 0),
        "tvl_pair": sm.get("final_pair_tvl", 0),
        "tvl_global_geo": sm.get("final_geo_tvl", 0),
        "tvl_localized_geo": sm.get("final_lgeo_tvl", 0),
      }
    )

  with (out_dir / "regime_comparison.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

  md = ["# Final Comparative Report", ""]
  md.append("This report compares three systems:")
  md.append("- Pairwise baseline (Tinyman-style)")
  md.append("- Global geometric AMM")
  md.append("- Localized geometric AMM (orbital regions)")
  md.append("")
  for r in rows:
    md.append(f"## {r['regime']}")
    md.append(f"- Avg slippage: pair {r['slippage_pair']:.4f} | global geo {r['slippage_global_geo']:.4f} | localized geo {r['slippage_localized_geo']:.4f}")
    md.append(f"- P95 slippage: pair {r['p95_pair']:.4f} | global geo {r['p95_global_geo']:.4f} | localized geo {r['p95_localized_geo']:.4f}")
    md.append(f"- Arbitrage PnL: pair {r['arb_pair']:.2f} | global geo {r['arb_global_geo']:.2f} | localized geo {r['arb_localized_geo']:.2f}")
    md.append(f"- Final TVL: pair {r['tvl_pair']:.2f} | global geo {r['tvl_global_geo']:.2f} | localized geo {r['tvl_localized_geo']:.2f}")
    md.append("")
  (out_dir / "final_report.md").write_text("\n".join(md))
  print(f"Final report output: {out_dir}")


if __name__ == "__main__":
  main()

