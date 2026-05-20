from __future__ import annotations

import csv
import json
import math
import random
import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Tuple


ASSETS = ("A", "B", "C")
PAIR_INDEX = [("A", "B"), ("B", "C"), ("A", "C")]


def safe_sqrt(n: int) -> int:
    return int(math.isqrt(max(0, n)))


def geometric_l(a: int, b: int, c: int) -> int:
    return safe_sqrt(a * a + b * b + c * c)


def dominance_bps(a: int, b: int, c: int) -> int:
    k = a * a + b * b + c * c
    if k == 0:
        return 0
    return (max(a * a, b * b, c * c) * 10_000) // k


def imbalance_bps(a: int, b: int, c: int) -> int:
    s = a + b + c
    if s == 0:
        return 0
    return (max(a, b, c) * 10_000) // s


def dynamic_fee_bps(a: int, b: int, c: int) -> int:
    dom = dominance_bps(a, b, c)
    if dom <= 3400:
        return 30
    if dom >= 6400:
        return 100
    return 30 + ((dom - 3400) * 70) // 3000


@dataclass
class TradeResult:
    ok: bool
    amount_out: int = 0
    fee_bps: int = 0
    slippage_pct: float = 0.0
    price_impact_pct: float = 0.0
    execution_quality: float = 0.0
    reason: str = ""


class PairwiseSystem:
    def __init__(self, reserve_each_pool: int = 1000, fee_bps: int = 30):
        self.fee_bps = fee_bps
        self.pools: Dict[Tuple[str, str], Dict[str, int]] = {}
        for a, b in PAIR_INDEX:
            self.pools[(a, b)] = {a: reserve_each_pool, b: reserve_each_pool}

    def _pool_for(self, asset_in: str, asset_out: str):
        key = tuple(sorted((asset_in, asset_out)))
        return key, self.pools[key]

    def spot_price(self, asset_in: str, asset_out: str) -> float:
        _, pool = self._pool_for(asset_in, asset_out)
        return pool[asset_out] / max(1, pool[asset_in])

    def trade(self, asset_in: str, asset_out: str, amount_in: int, oracle_px: float) -> TradeResult:
        if amount_in <= 0 or asset_in == asset_out:
            return TradeResult(ok=False, reason="invalid amount/pair")
        key, pool = self._pool_for(asset_in, asset_out)
        x = pool[asset_in]
        y = pool[asset_out]
        if amount_in >= x * 5:
            return TradeResult(ok=False, reason="too large")
        spot = y / max(1, x)
        amount_in_after_fee = (amount_in * (10_000 - self.fee_bps)) // 10_000
        new_x = x + amount_in_after_fee
        k = x * y
        new_y = k // max(1, new_x)
        out = y - new_y
        if out <= 0 or out >= y:
            return TradeResult(ok=False, reason="zero output")
        pool[asset_in] = new_x
        pool[asset_out] = new_y
        exec_px = out / max(1, amount_in)
        slippage = max(0.0, (spot - exec_px) / max(1e-9, spot) * 100)
        impact = slippage
        quality = exec_px / max(1e-9, oracle_px)
        self.pools[key] = pool
        return TradeResult(ok=True, amount_out=out, fee_bps=self.fee_bps, slippage_pct=slippage, price_impact_pct=impact, execution_quality=quality)

    def reserves(self) -> Dict[str, int]:
        totals = {a: 0 for a in ASSETS}
        for pool in self.pools.values():
            for a, r in pool.items():
                totals[a] += r
        return totals

    def tvl_value(self, oracle: Dict[str, float]) -> float:
        totals = self.reserves()
        return sum(totals[a] * oracle[a] for a in ASSETS)


class GeometricSystem:
    def __init__(
        self,
        reserve_a: int = 1000,
        reserve_b: int = 1000,
        reserve_c: int = 1000,
        curvature_center_bps: int = 4200,
        curvature_edge_bps: int = 1400,
        coupling_base_divisor: int = 40,
    ):
        self.reserve = {"A": reserve_a, "B": reserve_b, "C": reserve_c}
        self.total_lp_supply = reserve_a + reserve_b + reserve_c
        self.curvature_center_bps = curvature_center_bps
        self.curvature_edge_bps = curvature_edge_bps
        self.coupling_base_divisor = coupling_base_divisor

    def _third(self, a: str, b: str) -> str:
        for x in ASSETS:
            if x != a and x != b:
                return x
        raise ValueError("no third asset")

    def spot_price(self, asset_in: str, asset_out: str) -> float:
        # local finite-difference quote for 1 unit
        q = self.quote(asset_in, asset_out, 1)
        return float(q.amount_out)

    def quote(self, asset_in: str, asset_out: str, amount_in: int) -> TradeResult:
        if amount_in <= 0 or asset_in == asset_out:
            return TradeResult(ok=False, reason="invalid amount/pair")
        rin = self.reserve[asset_in]
        rout = self.reserve[asset_out]
        t = self._third(asset_in, asset_out)
        r3 = self.reserve[t]
        if rin <= 0 or rout <= 0 or r3 <= 1:
            return TradeResult(ok=False, reason="empty reserve")
        if rin < 20 or amount_in > rin // 20:
            return TradeResult(ok=False, reason="trade-size guard")
        dom = dominance_bps(self.reserve["A"], self.reserve["B"], self.reserve["C"])
        if dom > 6400:
            return TradeResult(ok=False, reason="dominance threshold exceeded")
        fee = self.dynamic_fee_bps(dom)
        ain = (amount_in * (10_000 - fee)) // 10_000
        if ain <= 0:
            return TradeResult(ok=False, reason="amount after fee is zero")
        new_rin = rin + ain
        base = (r3 * ain) // max(1, rin * self.coupling_base_divisor)
        if base <= 0:
            base = 1
        trade_size_bps = (ain * 10_000) // rin
        size_pressure = safe_sqrt(trade_size_bps * 10_000)
        imbalance_pressure = max(0, dom - 3600)
        delta3 = (base * (2_500 + size_pressure + imbalance_pressure)) // 10_000
        if delta3 <= 0:
            delta3 = 1
        if delta3 >= r3:
            delta3 = r3 - 1
        new_r3 = r3 - delta3
        curv = self.curvature_bps(dom)
        k = self.invariant_soft(self.reserve["A"], self.reserve["B"], self.reserve["C"], curv)
        target_sq = k - self.effective(new_rin, curv) ** 2 - self.effective(new_r3, curv) ** 2
        if target_sq <= 0:
            return TradeResult(ok=False, reason="invariant exhausted")
        target_eff_out = safe_sqrt(target_sq)
        reduction = (safe_sqrt(target_eff_out) * curv) // 10_000
        new_rout = max(1, target_eff_out - reduction)
        out = rout - new_rout
        if out <= 0 or out >= rout:
            return TradeResult(ok=False, reason="invalid output")
        spot = rout / max(1, rin)
        exec_px = out / max(1, amount_in)
        slippage = max(0.0, (spot - exec_px) / max(1e-9, spot) * 100)
        impact = slippage
        return TradeResult(ok=True, amount_out=out, fee_bps=fee, slippage_pct=slippage, price_impact_pct=impact)

    def dynamic_fee_bps(self, dom: int) -> int:
        if dom <= 3300:
            return 18
        if dom <= 4900:
            return 18 + ((dom - 3300) * 32) // 1600
        if dom <= 6200:
            return 50 + ((dom - 4900) * 40) // 1300
        return 90

    def curvature_bps(self, dom: int) -> int:
        if dom <= 3400:
            return self.curvature_center_bps
        if dom >= 6200:
            return self.curvature_edge_bps
        span = self.curvature_center_bps - self.curvature_edge_bps
        return self.curvature_center_bps - ((dom - 3400) * span) // 2800

    def effective(self, x: int, curv: int) -> int:
        return x + (safe_sqrt(x) * curv) // 10_000

    def invariant_soft(self, a: int, b: int, c: int, curv: int) -> int:
        ea = self.effective(a, curv)
        eb = self.effective(b, curv)
        ec = self.effective(c, curv)
        return ea * ea + eb * eb + ec * ec

    def trade(self, asset_in: str, asset_out: str, amount_in: int, oracle_px: float) -> TradeResult:
        q = self.quote(asset_in, asset_out, amount_in)
        if not q.ok:
            return q
        rin = self.reserve[asset_in]
        rout = self.reserve[asset_out]
        t = self._third(asset_in, asset_out)
        r3 = self.reserve[t]
        dom = dominance_bps(self.reserve["A"], self.reserve["B"], self.reserve["C"])
        fee = q.fee_bps
        ain = (amount_in * (10_000 - fee)) // 10_000
        new_rin = rin + ain
        base = (r3 * ain) // max(1, rin * 20)
        if base <= 0:
            base = 1
        delta3 = (base * (10_000 + dom)) // 10_000
        if delta3 <= 0:
            delta3 = 1
        if delta3 >= r3:
            delta3 = r3 - 1
        new_r3 = r3 - delta3
        self.reserve[asset_in] = new_rin
        self.reserve[asset_out] = rout - q.amount_out
        self.reserve[t] = new_r3
        q.execution_quality = (q.amount_out / max(1, amount_in)) / max(1e-9, oracle_px)
        return q

    def reserves(self) -> Dict[str, int]:
        return dict(self.reserve)

    def tvl_value(self, oracle: Dict[str, float]) -> float:
        return sum(self.reserve[a] * oracle[a] for a in ASSETS)


@dataclass
class SimConfig:
    seed: int = 42
    steps: int = 1500
    trader_freq: float = 0.85
    arb_freq: float = 0.35
    avg_trade_size: int = 8000
    trade_size_jitter: int = 6000
    momentum_bias: float = 0.35
    arbitrage_threshold_bps: int = 35
    base_reserve_per_asset: int = 1_000_000
    curvature_center_bps: int = 4200
    curvature_edge_bps: int = 1400
    coupling_base_divisor: int = 40


def oracle_step(oracle: Dict[str, float], rng: random.Random) -> Dict[str, float]:
    nxt = dict(oracle)
    for a in ASSETS:
        shock = rng.uniform(-0.008, 0.008)
        nxt[a] = max(0.3, oracle[a] * (1 + shock))
    return nxt


def pick_trade_pair(rng: random.Random, oracle_prev: Dict[str, float], oracle_now: Dict[str, float], momentum_bias: float) -> Tuple[str, str]:
    pairs = [("A", "B"), ("B", "C"), ("A", "C")]
    if rng.random() > momentum_bias:
        return pairs[rng.randrange(len(pairs))]
    # momentum directional flow toward recent winner
    perf = {a: oracle_now[a] / max(1e-9, oracle_prev[a]) for a in ASSETS}
    asset_in = min(perf, key=perf.get)
    asset_out = max(perf, key=perf.get)
    if asset_in == asset_out:
        return pairs[rng.randrange(len(pairs))]
    return asset_in, asset_out


def oracle_pair_px(oracle: Dict[str, float], a: str, b: str) -> float:
    return oracle[a] / max(1e-9, oracle[b])


def run(cfg: SimConfig | None = None) -> Path:
    cfg = cfg or SimConfig()
    rng = random.Random(cfg.seed)
    pairwise = PairwiseSystem(cfg.base_reserve_per_asset, 30)
    geometric = GeometricSystem(
        cfg.base_reserve_per_asset,
        cfg.base_reserve_per_asset,
        cfg.base_reserve_per_asset,
        cfg.curvature_center_bps,
        cfg.curvature_edge_bps,
        cfg.coupling_base_divisor,
    )
    oracle = {"A": 1.0, "B": 1.0, "C": 1.0}
    oracle_prev = dict(oracle)

    out_dir = Path("simulations") / "outputs" / datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    out_dir.mkdir(parents=True, exist_ok=True)

    ts_rows: List[Dict[str, object]] = []
    trade_rows: List[Dict[str, object]] = []
    trajectory_rows: List[Dict[str, object]] = []

    lp0_pair = pairwise.tvl_value(oracle) / float(cfg.base_reserve_per_asset * 3)
    lp0_geo = geometric.tvl_value(oracle) / geometric.total_lp_supply
    arb_profit_pair = 0.0
    arb_profit_geo = 0.0
    arb_count_pair = 0
    arb_count_geo = 0
    fee_escalations_geo = 0

    for step in range(cfg.steps):
        oracle_prev = oracle
        oracle = oracle_step(oracle, rng)

        if rng.random() < cfg.trader_freq:
            ain, aout = pick_trade_pair(rng, oracle_prev, oracle, cfg.momentum_bias)
            amount = max(1, cfg.avg_trade_size + rng.randint(-cfg.trade_size_jitter, cfg.trade_size_jitter))
            px_oracle = oracle_pair_px(oracle, ain, aout)
            r1 = pairwise.trade(ain, aout, amount, px_oracle)
            r2 = geometric.trade(ain, aout, amount, px_oracle)
            trade_rows.append(
                {
                    "step": step,
                    "agent": "trader",
                    "in": ain,
                    "out": aout,
                    "amount_in": amount,
                    "pair_ok": int(r1.ok),
                    "geo_ok": int(r2.ok),
                    "pair_out": r1.amount_out,
                    "geo_out": r2.amount_out,
                    "pair_slippage_pct": r1.slippage_pct,
                    "geo_slippage_pct": r2.slippage_pct,
                    "pair_exec_quality": r1.execution_quality,
                    "geo_exec_quality": r2.execution_quality,
                    "geo_fee_bps": r2.fee_bps,
                }
            )
            if r2.ok and r2.fee_bps > 30:
                fee_escalations_geo += 1

        if rng.random() < cfg.arb_freq:
            for ain, aout in PAIR_INDEX:
                opx = oracle_pair_px(oracle, ain, aout)
                ppx = pairwise.spot_price(ain, aout)
                gpx = geometric.spot_price(ain, aout)
                dev_pair_bps = abs(ppx - opx) / max(1e-9, opx) * 10_000
                dev_geo_bps = abs(gpx - opx) / max(1e-9, opx) * 10_000
                if dev_pair_bps > cfg.arbitrage_threshold_bps:
                    direction = (ain, aout) if ppx > opx else (aout, ain)
                    amt = max(1, cfg.avg_trade_size // 2)
                    rr = pairwise.trade(direction[0], direction[1], amt, oracle_pair_px(oracle, direction[0], direction[1]))
                    if rr.ok:
                        arb_profit_pair += rr.amount_out * oracle[direction[1]] - amt * oracle[direction[0]]
                        arb_count_pair += 1
                if dev_geo_bps > cfg.arbitrage_threshold_bps:
                    direction = (ain, aout) if gpx > opx else (aout, ain)
                    amt = max(1, cfg.avg_trade_size // 2)
                    rr = geometric.trade(direction[0], direction[1], amt, oracle_pair_px(oracle, direction[0], direction[1]))
                    if rr.ok:
                        arb_profit_geo += rr.amount_out * oracle[direction[1]] - amt * oracle[direction[0]]
                        arb_count_geo += 1

        pr = pairwise.reserves()
        gr = geometric.reserves()
        trajectory_rows.append({"step": step, "system": "pairwise", "A": pr["A"], "B": pr["B"], "C": pr["C"]})
        trajectory_rows.append({"step": step, "system": "geometric", "A": gr["A"], "B": gr["B"], "C": gr["C"]})

        pair_lp = pairwise.tvl_value(oracle) / float(cfg.base_reserve_per_asset * 3)
        geo_lp = geometric.tvl_value(oracle) / geometric.total_lp_supply
        ts_rows.append(
            {
                "step": step,
                "oracle_A": oracle["A"],
                "oracle_B": oracle["B"],
                "oracle_C": oracle["C"],
                "pair_tvl": pairwise.tvl_value(oracle),
                "geo_tvl": geometric.tvl_value(oracle),
                "pair_lp_value": pair_lp,
                "geo_lp_value": geo_lp,
                "pair_lp_growth": pair_lp / lp0_pair,
                "geo_lp_growth": geo_lp / lp0_geo,
                "pair_dominance_bps": dominance_bps(pr["A"], pr["B"], pr["C"]),
                "geo_dominance_bps": dominance_bps(gr["A"], gr["B"], gr["C"]),
                "pair_imbalance_bps": imbalance_bps(pr["A"], pr["B"], pr["C"]),
                "geo_imbalance_bps": imbalance_bps(gr["A"], gr["B"], gr["C"]),
                "geo_liquidity_L": geometric_l(gr["A"], gr["B"], gr["C"]),
                "geo_curvature_bps": geometric.curvature_bps(dominance_bps(gr["A"], gr["B"], gr["C"])),
            }
        )

    # Capital efficiency: max amount with <=15% slippage for A->B
    def max_supported(system_name: str, max_try: int = 250_000, threshold_pct: float = 15.0):
        if system_name == "pair":
            sys = PairwiseSystem(cfg.base_reserve_per_asset, 30)
            quote = lambda amt: sys.trade("A", "B", amt, 1.0)
        else:
            sys = GeometricSystem(cfg.base_reserve_per_asset, cfg.base_reserve_per_asset, cfg.base_reserve_per_asset)
            quote = lambda amt: sys.trade("A", "B", amt, 1.0)
        best = 0
        for amt in range(100, max_try + 1, 100):
            r = quote(amt)
            if r.ok and r.slippage_pct <= threshold_pct:
                best = amt
            else:
                break
        return best

    pair_max = max_supported("pair")
    geo_max = max_supported("geo")

    avg = lambda col: sum(float(r[col]) for r in ts_rows) / max(1, len(ts_rows))
    trader_only = [r for r in trade_rows if r["agent"] == "trader"]
    avg_pair_slip = sum(r["pair_slippage_pct"] for r in trader_only) / max(1, len(trader_only))
    avg_geo_slip = sum(r["geo_slippage_pct"] for r in trader_only) / max(1, len(trader_only))

    path_delta = path_dependence_test(cfg.seed)
    summary = [
        ("steps", cfg.steps),
        ("avg_trader_slippage_pair_pct", round(avg_pair_slip, 6)),
        ("avg_trader_slippage_geo_pct", round(avg_geo_slip, 6)),
        ("final_pair_lp_growth", round(ts_rows[-1]["pair_lp_growth"], 6)),
        ("final_geo_lp_growth", round(ts_rows[-1]["geo_lp_growth"], 6)),
        ("avg_pair_dominance_bps", round(avg("pair_dominance_bps"), 4)),
        ("avg_geo_dominance_bps", round(avg("geo_dominance_bps"), 4)),
        ("arb_profit_pair", round(arb_profit_pair, 6)),
        ("arb_profit_geo", round(arb_profit_geo, 6)),
        ("arb_trades_pair", arb_count_pair),
        ("arb_trades_geo", arb_count_geo),
        ("geo_fee_escalation_events", fee_escalations_geo),
        ("capital_efficiency_pair_max_amt_at_15pct_slippage", pair_max),
        ("capital_efficiency_geo_max_amt_at_15pct_slippage", geo_max),
        ("path_dependence_pair_l1_reserve_delta", path_delta["pair_l1"]),
        ("path_dependence_geo_l1_reserve_delta", path_delta["geo_l1"]),
    ]

    write_csv(out_dir / "metrics_timeseries.csv", ts_rows)
    write_csv(out_dir / "trades.csv", trade_rows)
    write_csv(out_dir / "reserves_trajectory.csv", trajectory_rows)
    write_csv(out_dir / "summary_metrics.csv", [{"metric": k, "value": v} for k, v in summary])
    write_html_charts(out_dir, ts_rows, trade_rows, trajectory_rows)

    print(f"Simulation complete. Outputs: {out_dir}")
    return out_dir


def path_dependence_test(seed: int) -> Dict[str, int]:
    rng = random.Random(seed + 999)
    trades = []
    for _ in range(200):
        a, b = PAIR_INDEX[rng.randrange(3)]
        amt = rng.randint(1000, 8000)
        trades.append((a, b, amt))
    rev = list(reversed(trades))
    p1, p2 = PairwiseSystem(1_000_000), PairwiseSystem(1_000_000)
    g1, g2 = GeometricSystem(1_000_000, 1_000_000, 1_000_000), GeometricSystem(1_000_000, 1_000_000, 1_000_000)
    for a, b, amt in trades:
        p1.trade(a, b, amt, 1.0)
        g1.trade(a, b, amt, 1.0)
    for a, b, amt in rev:
        p2.trade(a, b, amt, 1.0)
        g2.trade(a, b, amt, 1.0)
    pr1, pr2 = p1.reserves(), p2.reserves()
    gr1, gr2 = g1.reserves(), g2.reserves()
    pair_l1 = sum(abs(pr1[a] - pr2[a]) for a in ASSETS)
    geo_l1 = sum(abs(gr1[a] - gr2[a]) for a in ASSETS)
    return {"pair_l1": pair_l1, "geo_l1": geo_l1}


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_html_charts(out_dir: Path, ts_rows: List[Dict[str, object]], trade_rows: List[Dict[str, object]], traj_rows: List[Dict[str, object]]) -> None:
    steps = [r["step"] for r in ts_rows]
    pair_lp = [r["pair_lp_growth"] for r in ts_rows]
    geo_lp = [r["geo_lp_growth"] for r in ts_rows]
    pair_imb = [r["pair_imbalance_bps"] for r in ts_rows]
    geo_imb = [r["geo_imbalance_bps"] for r in ts_rows]
    geo_fee = [r.get("geo_fee_bps", 30) for r in trade_rows if r["agent"] == "trader"]
    pair_sl = [r["pair_slippage_pct"] for r in trade_rows if r["agent"] == "trader"]
    geo_sl = [r["geo_slippage_pct"] for r in trade_rows if r["agent"] == "trader"]
    pair_dom = [r["pair_dominance_bps"] for r in ts_rows]
    geo_dom = [r["geo_dominance_bps"] for r in ts_rows]
    geo_curv = [r["geo_curvature_bps"] for r in ts_rows]

    p3 = [r for r in traj_rows if r["system"] == "pairwise"]
    g3 = [r for r in traj_rows if r["system"] == "geometric"]
    html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>AMM Simulation Charts</title>
<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>
<style>body{{font-family:Arial,sans-serif;margin:20px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} .card{{border:1px solid #ddd;padding:10px;border-radius:8px}}</style>
</head><body>
<h1>Orbital vs Pairwise AMM Simulation</h1>
<div class='grid'>
  <div id='slippage' class='card' style='height:360px'></div>
  <div id='lp' class='card' style='height:360px'></div>
  <div id='imbalance' class='card' style='height:360px'></div>
  <div id='fee' class='card' style='height:360px'></div>
  <div id='dominance' class='card' style='height:360px'></div>
  <div id='curvature' class='card' style='height:360px'></div>
  <div id='trajectory' class='card' style='height:500px;grid-column:1/3'></div>
</div>
<script>
Plotly.newPlot('slippage', [
  {{y:{json.dumps(pair_sl)}, type:'histogram', name:'Pairwise Slippage %', opacity:0.7}},
  {{y:{json.dumps(geo_sl)}, type:'histogram', name:'Geometric Slippage %', opacity:0.7}}
], {{title:'Slippage Distribution', barmode:'overlay'}});

Plotly.newPlot('lp', [
  {{x:{json.dumps(steps)}, y:{json.dumps(pair_lp)}, mode:'lines', name:'Pairwise LP Growth'}},
  {{x:{json.dumps(steps)}, y:{json.dumps(geo_lp)}, mode:'lines', name:'Geometric LP Growth'}}
], {{title:'LP Value Growth', xaxis:{{title:'Step'}}, yaxis:{{title:'Growth Multiple'}}}});

Plotly.newPlot('imbalance', [
  {{x:{json.dumps(steps)}, y:{json.dumps(pair_imb)}, mode:'lines', name:'Pairwise Imbalance (bps)'}},
  {{x:{json.dumps(steps)}, y:{json.dumps(geo_imb)}, mode:'lines', name:'Geometric Imbalance (bps)'}}
], {{title:'Reserve Imbalance Over Time', xaxis:{{title:'Step'}}, yaxis:{{title:'bps'}}}});

Plotly.newPlot('fee', [
  {{y:{json.dumps(geo_fee)}, type:'histogram', name:'Geometric Dynamic Fee (bps)'}}
], {{title:'Dynamic Fee Behavior'}});

Plotly.newPlot('dominance', [
  {{x:{json.dumps(steps)}, y:{json.dumps(pair_dom)}, mode:'lines', name:'Pairwise Dominance (bps)'}},
  {{x:{json.dumps(steps)}, y:{json.dumps(geo_dom)}, mode:'lines', name:'Geometric Dominance (bps)'}}
], {{title:'Dominance Evolution', xaxis:{{title:'Step'}}, yaxis:{{title:'bps'}}}});

Plotly.newPlot('curvature', [
  {{x:{json.dumps(steps)}, y:{json.dumps(geo_curv)}, mode:'lines', name:'Geometric Curvature Region (bps)'}}
], {{title:'Adaptive Curvature Regions', xaxis:{{title:'Step'}}, yaxis:{{title:'curvature bps'}}}});

Plotly.newPlot('trajectory', [
  {{x:{json.dumps([r["A"] for r in p3])}, y:{json.dumps([r["B"] for r in p3])}, z:{json.dumps([r["C"] for r in p3])}, mode:'lines', type:'scatter3d', name:'Pairwise Total Reserves'}},
  {{x:{json.dumps([r["A"] for r in g3])}, y:{json.dumps([r["B"] for r in g3])}, z:{json.dumps([r["C"] for r in g3])}, mode:'lines', type:'scatter3d', name:'Geometric Reserves'}}
], {{title:'3D Reserve Geometry Evolution', scene:{{xaxis:{{title:'A'}}, yaxis:{{title:'B'}}, zaxis:{{title:'C'}}}}}});
</script>
</body></html>"""
    (out_dir / "charts.html").write_text(html)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    cfg = SimConfig(seed=args.seed, steps=args.steps)
    run(cfg)
