# Advanced Agentic Regime Simulator

Run one regime:

```bash
python3 -m simulations.advanced.run_advanced --regime correlated_basket --steps 2000 --seed 42
```

Run full regime sweep:

```bash
python3 -m simulations.advanced.sweep_advanced
python3 -m simulations.advanced.analyze_sweep
```

## Regimes

- `random_market`
- `correlated_basket`
- `volatile_divergent`
- `liquidity_fragmentation`
- `crisis_bank_run`

## Agents

- Retail flow agent
- Arbitrage agent
- Whale stress agent
- LP allocation agent
- Correlated basket trader

## Outputs per run

- `events.csv`
- `snapshots.csv`
- `summary.csv`
- `dashboard.html`
- `report.md`

## Sweep outputs

- `advanced_sweep_results.csv`
- `top_regime_specialists.csv`
- `regime_dashboard.html` (after `analyze_sweep`)

## Research use

Use `advanced_sweep_results.csv` + `top_regime_specialists.csv` to identify:

- favorable regimes
- failure regimes
- specialization domains for geometric liquidity
