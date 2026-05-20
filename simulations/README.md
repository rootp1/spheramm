# AMM Agent-Based Simulation

Run:

```bash
python3 simulations/run_simulation.py
python3 simulations/run_simulation.py --steps 3000 --seed 7
```

Outputs are written to:

- `simulations/outputs/<timestamp>/metrics_timeseries.csv`
- `simulations/outputs/<timestamp>/summary_metrics.csv`
- `simulations/outputs/<timestamp>/trades.csv`
- `simulations/outputs/<timestamp>/reserves_trajectory.csv`
- `simulations/outputs/<timestamp>/charts.html`

The simulation compares:

1. Pairwise constant-product AMMs (A/B, B/C, A/C), fixed fee 0.3%
2. Orbital-inspired geometric 3-asset AMM with dynamic fee + coupling
   - softened generalized-geometry proxy (`effectiveReserve = x + curvature*sqrt(x)`)
   - adaptive curvature regions (balance vs stress)
   - damped nonlinear third-reserve coupling
   - equilibrium-attraction fee profile

Agents:

- Trader agent (random + directional flow)
- Arbitrage agent (oracle convergence with threshold)

All randomness is seeded for reproducibility.

## Parameter Sweep

Run:

```bash
python3 simulations/sweep.py
```

This generates:

- `simulations/outputs/sweep_<timestamp>/sweep_results.csv`
- `simulations/outputs/sweep_<timestamp>/top_candidates.csv`

Sweep dimensions:

- center curvature bps
- edge curvature bps
- coupling base divisor

Use this to search for parameter regions where geometric AMM competitiveness improves.
