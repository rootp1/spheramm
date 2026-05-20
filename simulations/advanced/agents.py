from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .amm import ASSETS, PAIRS, GeometricAMM, PairwiseAMM, Trade, dominance_bps
from .config import AgentConfig, MarketConfig
from .regimes import preferred_direction


@dataclass
class AgentEvent:
  step: int
  agent: str
  system: str
  ain: str
  aout: str
  amount_in: int
  amount_out: int
  slippage_pct: float
  fee_bps: int
  execution_quality: float
  ok: int
  pnl_value: float = 0.0
  hop_count: int = 1


def _pair_px(oracle: Dict[str, float], ain: str, aout: str) -> float:
  return oracle[aout] / max(1e-9, oracle[ain])


def retail_flow(
  step: int,
  rng: random.Random,
  oracle_prev: Dict[str, float],
  oracle_now: Dict[str, float],
  pair: PairwiseAMM,
  geo: GeometricAMM,
  acfg: AgentConfig,
  mcfg: MarketConfig,
) -> List[AgentEvent]:
  out: List[AgentEvent] = []
  if rng.random() > acfg.retail_intensity:
    return out
  if rng.random() < acfg.retail_directional_persistence:
    ain, aout = preferred_direction(oracle_prev, oracle_now)
  else:
    ain, aout = PAIRS[rng.randrange(3)]
  vol_scale = 1.0 + acfg.retail_vol_sensitivity * abs((oracle_now[ain] / max(1e-9, oracle_prev[ain])) - 1.0)
  amount = int(max(1, (acfg.retail_avg_size + rng.randint(-acfg.retail_size_jitter, acfg.retail_size_jitter)) * vol_scale))
  px = _pair_px(oracle_now, ain, aout)
  p = pair.trade(ain, aout, amount, px)
  g = geo.trade(ain, aout, amount, px)
  out.append(_event(step, "retail", "pairwise", ain, aout, amount, p))
  out.append(_event(step, "retail", "geometric", ain, aout, amount, g))
  return out


def arbitrage_flow(
  step: int,
  rng: random.Random,
  oracle_now: Dict[str, float],
  pair: PairwiseAMM,
  geo: GeometricAMM,
  acfg: AgentConfig,
) -> List[AgentEvent]:
  events: List[AgentEvent] = []
  if rng.random() > acfg.arb_intensity:
    return events
  for ain, aout in PAIRS:
    opx = _pair_px(oracle_now, ain, aout)
    ppx = pair.spot(ain, aout)
    gpx = geo.spot(ain, aout)
    pdev = abs(ppx - opx) / max(1e-9, opx) * 10_000
    gdev = abs(gpx - opx) / max(1e-9, opx) * 10_000
    if pdev > acfg.arb_threshold_bps:
      d_in, d_out = (ain, aout) if ppx > opx else (aout, ain)
      amt = max(1, int(acfg.arb_capital_per_trade * acfg.arb_aggressiveness))
      px = _pair_px(oracle_now, d_in, d_out)
      r = pair.trade(d_in, d_out, amt, px)
      ev = _event(step, "arbitrage", "pairwise", d_in, d_out, amt, r)
      if r.ok:
        ev.pnl_value = r.amount_out * oracle_now[d_out] - amt * oracle_now[d_in]
      events.append(ev)
    if gdev > acfg.arb_threshold_bps:
      d_in, d_out = (ain, aout) if gpx > opx else (aout, ain)
      amt = max(1, int(acfg.arb_capital_per_trade * acfg.arb_aggressiveness))
      px = _pair_px(oracle_now, d_in, d_out)
      r = geo.trade(d_in, d_out, amt, px)
      ev = _event(step, "arbitrage", "geometric", d_in, d_out, amt, r)
      if r.ok:
        ev.pnl_value = r.amount_out * oracle_now[d_out] - amt * oracle_now[d_in]
      events.append(ev)
  return events


def whale_stress_flow(
  step: int,
  rng: random.Random,
  oracle_prev: Dict[str, float],
  oracle_now: Dict[str, float],
  pair: PairwiseAMM,
  geo: GeometricAMM,
  acfg: AgentConfig,
  mcfg: MarketConfig,
) -> List[AgentEvent]:
  events: List[AgentEvent] = []
  if rng.random() > acfg.whale_intensity:
    return events
  ain, aout = preferred_direction(oracle_prev, oracle_now) if rng.random() < acfg.whale_directional_bias else PAIRS[rng.randrange(3)]
  if mcfg.regime == "crisis_bank_run":
    ain, aout = "A", "B"
  amt = max(1, acfg.whale_avg_size + rng.randint(-acfg.whale_avg_size // 5, acfg.whale_avg_size // 3))
  px = _pair_px(oracle_now, ain, aout)
  p = pair.trade(ain, aout, amt, px)
  g = geo.trade(ain, aout, amt, px)
  events.append(_event(step, "whale", "pairwise", ain, aout, amt, p))
  events.append(_event(step, "whale", "geometric", ain, aout, amt, g))
  return events


def basket_trader_flow(
  step: int,
  rng: random.Random,
  oracle_now: Dict[str, float],
  pair: PairwiseAMM,
  geo: GeometricAMM,
  acfg: AgentConfig,
  mcfg: MarketConfig,
) -> List[AgentEvent]:
  events: List[AgentEvent] = []
  intensity = acfg.basket_intensity + (0.18 if mcfg.regime == "correlated_basket" else 0.0)
  if rng.random() > intensity:
    return events
  size = max(1, acfg.basket_rotation_size + rng.randint(-acfg.basket_rotation_size // 3, acfg.basket_rotation_size // 3))
  # Triangular rotation A->B->C->A captures multi-asset basket flow.
  route: List[Tuple[str, str]] = [("A", "B"), ("B", "C"), ("C", "A")] if rng.random() < acfg.basket_triangular_bias else [PAIRS[rng.randrange(3)]]
  current_amt_pair = size
  current_amt_geo = size
  for hop, (ain, aout) in enumerate(route, start=1):
    px = _pair_px(oracle_now, ain, aout)
    p = pair.trade(ain, aout, current_amt_pair, px)
    g = geo.trade(ain, aout, current_amt_geo, px)
    events.append(_event(step, "basket", "pairwise", ain, aout, current_amt_pair, p, hop_count=hop))
    events.append(_event(step, "basket", "geometric", ain, aout, current_amt_geo, g, hop_count=hop))
    if not p.ok or not g.ok:
      break
    current_amt_pair = max(1, p.amount_out)
    current_amt_geo = max(1, g.amount_out)
  return events


def lp_allocation_flow(
  step: int,
  rng: random.Random,
  oracle_now: Dict[str, float],
  pair: PairwiseAMM,
  geo: GeometricAMM,
  acfg: AgentConfig,
  state: Dict[str, float],
) -> List[AgentEvent]:
  events: List[AgentEvent] = []
  if step % max(1, acfg.lp_rebalance_interval) != 0:
    return events
  pair_tvl = pair.tvl(oracle_now)
  geo_tvl = geo.tvl(oracle_now)
  pair_dom = dominance_bps(**_abc(pair.reserves_total()))
  geo_dom = dominance_bps(**_abc(geo.reserves_total()))
  # Simple migration policy: favor higher adjusted yield = fee proxy - dominance stress.
  pair_score = state.get("pair_fee_proxy", 0.0) - acfg.lp_migration_sensitivity * (pair_dom / 10_000)
  geo_score = state.get("geo_fee_proxy", 0.0) - acfg.lp_migration_sensitivity * (geo_dom / 10_000)
  target_geo_weight = 0.5 + max(-0.35, min(0.35, (geo_score - pair_score)))
  state["lp_geo_weight"] = max(0.05, min(0.95, target_geo_weight))
  # Log as synthetic event.
  events.append(
    AgentEvent(
      step=step,
      agent="lp_allocator",
      system="meta",
      ain="A",
      aout="B",
      amount_in=0,
      amount_out=0,
      slippage_pct=0.0,
      fee_bps=0,
      execution_quality=0.0,
      ok=1,
      pnl_value=state["lp_geo_weight"],
      hop_count=0,
    )
  )
  return events


def _event(step: int, agent: str, system: str, ain: str, aout: str, amt: int, r: Trade, hop_count: int = 1) -> AgentEvent:
  return AgentEvent(
    step=step,
    agent=agent,
    system=system,
    ain=ain,
    aout=aout,
    amount_in=amt,
    amount_out=r.amount_out,
    slippage_pct=r.slippage_pct,
    fee_bps=r.fee_bps,
    execution_quality=r.execution_quality,
    ok=int(r.ok),
    hop_count=hop_count,
  )


def _abc(reserves: Dict[str, int]) -> Dict[str, int]:
  return {"a": reserves["A"], "b": reserves["B"], "c": reserves["C"]}

