from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List


def latest_sweep_dir() -> Path:
  root = Path("simulations") / "outputs"
  cands = sorted([p for p in root.iterdir() if p.is_dir() and p.name.startswith("advanced_sweep_")])
  if not cands:
    raise FileNotFoundError("No advanced sweep directory found.")
  return cands[-1]


def load_rows(path: Path) -> List[Dict[str, float | str]]:
  out: List[Dict[str, float | str]] = []
  with path.open() as f:
    r = csv.DictReader(f)
    for row in r:
      d: Dict[str, float | str] = {}
      for k, v in row.items():
        if k == "regime":
          d[k] = v
        else:
          d[k] = float(v) if v is not None and v != "" else 0.0
      out.append(d)
  return out


def build_dashboard(rows: List[Dict[str, float | str]], out_html: Path) -> None:
  regimes = sorted(set(str(r["regime"]) for r in rows))
  by_regime = {reg: [r for r in rows if r["regime"] == reg] for reg in regimes}
  avg_delta_slip = [sum(float(x["avg_slippage_geo"]) - float(x["avg_slippage_pair"]) for x in by_regime[r]) / max(1, len(by_regime[r])) for r in regimes]
  avg_delta_slip_lgeo = [sum(float(x["avg_slippage_lgeo"]) - float(x["avg_slippage_pair"]) for x in by_regime[r]) / max(1, len(by_regime[r])) for r in regimes]
  avg_delta_arb = [sum(float(x["arb_pnl_geo"]) - float(x["arb_pnl_pair"]) for x in by_regime[r]) / max(1, len(by_regime[r])) for r in regimes]
  avg_delta_arb_lgeo = [sum(float(x["arb_pnl_lgeo"]) - float(x["arb_pnl_pair"]) for x in by_regime[r]) / max(1, len(by_regime[r])) for r in regimes]

  centers = sorted(set(int(r["center_bps"]) for r in rows))
  divs = sorted(set(int(r["coupling_div"]) for r in rows))
  # heatmap: average geometric slippage by (center curvature, coupling divisor)
  z = []
  for c in centers:
    row = []
    for d in divs:
      pts = [r for r in rows if int(r["center_bps"]) == c and int(r["coupling_div"]) == d]
      val = sum(float(r["avg_slippage_geo"]) for r in pts) / max(1, len(pts))
      row.append(val)
    z.append(row)

  html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Advanced Sweep Dashboard</title>
<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>
<style>body{{font-family:Arial,sans-serif;margin:18px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}</style>
</head><body>
<h1>Advanced Regime Sweep Dashboard</h1>
<div class='grid'>
<div id='slip' style='height:360px;border:1px solid #ddd;border-radius:8px'></div>
<div id='arb' style='height:360px;border:1px solid #ddd;border-radius:8px'></div>
<div id='heat' style='height:420px;border:1px solid #ddd;border-radius:8px;grid-column:1/3'></div>
</div>
<script>
Plotly.newPlot('slip', [{{x:{json.dumps(regimes)}, y:{json.dumps(avg_delta_slip)}, type:'bar', name:'global geo - pair'}},{{x:{json.dumps(regimes)}, y:{json.dumps(avg_delta_slip_lgeo)}, type:'bar', name:'localized geo - pair'}}], {{title:'Regime Slippage Delta (lower is better)', barmode:'group'}});
Plotly.newPlot('arb', [{{x:{json.dumps(regimes)}, y:{json.dumps(avg_delta_arb)}, type:'bar', name:'global geo - pair'}},{{x:{json.dumps(regimes)}, y:{json.dumps(avg_delta_arb_lgeo)}, type:'bar', name:'localized geo - pair'}}], {{title:'Regime Arbitrage PnL Delta (higher is better)', barmode:'group'}});
Plotly.newPlot('heat', [{{x:{json.dumps(divs)}, y:{json.dumps(centers)}, z:{json.dumps(z)}, type:'heatmap', colorscale:'Viridis'}}], {{title:'Sensitivity: Avg Geometric Slippage (%)', xaxis:{{title:'Coupling Divisor'}}, yaxis:{{title:'Center Curvature BPS'}}}});
</script></body></html>"""
  out_html.write_text(html)


def main() -> None:
  d = latest_sweep_dir()
  rows = load_rows(d / "advanced_sweep_results.csv")
  build_dashboard(rows, d / "regime_dashboard.html")
  print(f"Generated: {d / 'regime_dashboard.html'}")


if __name__ == "__main__":
  main()
