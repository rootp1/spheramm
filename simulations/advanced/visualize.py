from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .agents import AgentEvent
from .metrics import Snapshot


def build_dashboard_html(out_dir: Path, snaps: List[Snapshot], events: List[AgentEvent]) -> None:
  steps = [s.step for s in snaps]
  pair_dom = [s.pair_dom_bps for s in snaps]
  geo_dom = [s.geo_dom_bps for s in snaps]
  lgeo_dom = [s.lgeo_dom_bps for s in snaps]
  pair_imb = [s.pair_imb_bps for s in snaps]
  geo_imb = [s.geo_imb_bps for s in snaps]
  lgeo_imb = [s.lgeo_imb_bps for s in snaps]
  pair_tvl = [s.pair_tvl for s in snaps]
  geo_tvl = [s.geo_tvl for s in snaps]
  lgeo_tvl = [s.lgeo_tvl for s in snaps]
  geo_curv = [s.curvature_region_bps for s in snaps]
  geo_coupling = [s.coupling_intensity_proxy for s in snaps]
  geo_tension = [s.reserve_tension_bps for s in snaps]
  geo_amp = [s.center_amplification_bps for s in snaps]
  geo_mem = [s.stress_memory_bps for s in snaps]

  p3a, p3b, p3c = [s.pair_a for s in snaps], [s.pair_b for s in snaps], [s.pair_c for s in snaps]
  g3a, g3b, g3c = [s.geo_a for s in snaps], [s.geo_b for s in snaps], [s.geo_c for s in snaps]
  lg3a, lg3b, lg3c = [s.lgeo_a for s in snaps], [s.lgeo_b for s in snaps], [s.lgeo_c for s in snaps]
  psl = [e.slippage_pct for e in events if e.system == "pairwise" and e.ok == 1]
  gsl = [e.slippage_pct for e in events if e.system == "geometric" and e.ok == 1]
  lgsl = [e.slippage_pct for e in events if e.system == "localized_geometric" and e.ok == 1]

  html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Advanced AMM Regime Dashboard</title>
<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>
<style>body{{font-family:Arial,sans-serif;margin:18px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .card{{border:1px solid #ddd;border-radius:8px;padding:8px}}</style>
</head><body>
<h1>Regime Dashboard</h1>
<div class='grid'>
  <div id='sl' class='card' style='height:350px'></div>
  <div id='tvl' class='card' style='height:350px'></div>
  <div id='dom' class='card' style='height:350px'></div>
  <div id='imb' class='card' style='height:350px'></div>
  <div id='curv' class='card' style='height:350px'></div>
  <div id='coupling' class='card' style='height:350px'></div>
  <div id='tension' class='card' style='height:350px'></div>
  <div id='amp' class='card' style='height:350px'></div>
  <div id='memory' class='card' style='height:350px'></div>
  <div id='traj' class='card' style='height:520px;grid-column:1/3'></div>
</div>
<script>
Plotly.newPlot('sl', [{{y:{json.dumps(psl)},type:'histogram',name:'Pairwise'}},{{y:{json.dumps(gsl)},type:'histogram',name:'Global Geometric'}},{{y:{json.dumps(lgsl)},type:'histogram',name:'Localized Geometric'}}], {{title:'Slippage Distribution',barmode:'overlay'}});
Plotly.newPlot('tvl', [{{x:{json.dumps(steps)},y:{json.dumps(pair_tvl)},mode:'lines',name:'Pairwise TVL'}},{{x:{json.dumps(steps)},y:{json.dumps(geo_tvl)},mode:'lines',name:'Global Geometric TVL'}},{{x:{json.dumps(steps)},y:{json.dumps(lgeo_tvl)},mode:'lines',name:'Localized Geometric TVL'}}], {{title:'TVL Evolution'}});
Plotly.newPlot('dom', [{{x:{json.dumps(steps)},y:{json.dumps(pair_dom)},mode:'lines',name:'Pairwise'}},{{x:{json.dumps(steps)},y:{json.dumps(geo_dom)},mode:'lines',name:'Global Geometric'}},{{x:{json.dumps(steps)},y:{json.dumps(lgeo_dom)},mode:'lines',name:'Localized Geometric'}}], {{title:'Dominance bps'}});
Plotly.newPlot('imb', [{{x:{json.dumps(steps)},y:{json.dumps(pair_imb)},mode:'lines',name:'Pairwise'}},{{x:{json.dumps(steps)},y:{json.dumps(geo_imb)},mode:'lines',name:'Global Geometric'}},{{x:{json.dumps(steps)},y:{json.dumps(lgeo_imb)},mode:'lines',name:'Localized Geometric'}}], {{title:'Imbalance bps'}});
Plotly.newPlot('curv', [{{x:{json.dumps(steps)},y:{json.dumps(geo_curv)},mode:'lines',name:'Curvature Region'}}], {{title:'Adaptive Curvature Region'}});
Plotly.newPlot('coupling', [{{x:{json.dumps(steps)},y:{json.dumps(geo_coupling)},mode:'lines',name:'Coupling Intensity Proxy'}}], {{title:'Coupling Activation'}});
Plotly.newPlot('tension', [{{x:{json.dumps(steps)},y:{json.dumps(geo_tension)},mode:'lines',name:'Reserve Tension'}}], {{title:'Reserve Tension'}});
Plotly.newPlot('amp', [{{x:{json.dumps(steps)},y:{json.dumps(geo_amp)},mode:'lines',name:'Center Amplification'}}], {{title:'Equilibrium Concentration Intensity'}});
Plotly.newPlot('memory', [{{x:{json.dumps(steps)},y:{json.dumps(geo_mem)},mode:'lines',name:'Stress Memory'}}], {{title:'Stress Memory Propagation'}});
Plotly.newPlot('traj', [{{x:{json.dumps(p3a)},y:{json.dumps(p3b)},z:{json.dumps(p3c)},type:'scatter3d',mode:'lines',name:'Pairwise Total Reserves'}},{{x:{json.dumps(g3a)},y:{json.dumps(g3b)},z:{json.dumps(g3c)},type:'scatter3d',mode:'lines',name:'Global Geometric Reserves'}},{{x:{json.dumps(lg3a)},y:{json.dumps(lg3b)},z:{json.dumps(lg3c)},type:'scatter3d',mode:'lines',name:'Localized Geometric Reserves'}}], {{title:'3D Reserve-Space Trajectories',scene:{{xaxis:{{title:'A'}},yaxis:{{title:'B'}},zaxis:{{title:'C'}}}}}});
</script></body></html>"""
  (out_dir / "dashboard.html").write_text(html)
