from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Tuple


ASSETS = ("A", "B", "C")
PAIRS = (("A", "B"), ("B", "C"), ("A", "C"))


def isqrt(n: int) -> int:
  return int(math.isqrt(max(0, n)))


def dominance_bps(a: int, b: int, c: int) -> int:
  k = a * a + b * b + c * c
  if k <= 0:
    return 0
  return (max(a * a, b * b, c * c) * 10_000) // k


def imbalance_bps(a: int, b: int, c: int) -> int:
  s = a + b + c
  if s <= 0:
    return 0
  return (max(a, b, c) * 10_000) // s


@dataclass
class Trade:
  ok: bool
  amount_out: int = 0
  fee_bps: int = 0
  slippage_pct: float = 0.0
  execution_quality: float = 0.0
  reason: str = ""
  hop_count: int = 1


class PairwiseAMM:
  def __init__(self, reserve_each_pool: int, fee_bps: int = 30) -> None:
    self.fee_bps = fee_bps
    self.pools: Dict[Tuple[str, str], Dict[str, int]] = {}
    for a, b in PAIRS:
      self.pools[(a, b)] = {a: reserve_each_pool, b: reserve_each_pool}

  def _pool_key(self, ain: str, aout: str) -> Tuple[str, str]:
    return tuple(sorted((ain, aout)))

  def _pool(self, ain: str, aout: str) -> Dict[str, int]:
    return self.pools[self._pool_key(ain, aout)]

  def spot(self, ain: str, aout: str) -> float:
    p = self._pool(ain, aout)
    return p[aout] / max(1, p[ain])

  def quote(self, ain: str, aout: str, amount_in: int) -> Trade:
    if amount_in <= 0 or ain == aout:
      return Trade(False, reason="invalid")
    p = self._pool(ain, aout)
    x, y = p[ain], p[aout]
    if x <= 0 or y <= 0:
      return Trade(False, reason="empty")
    amount_in_af = (amount_in * (10_000 - self.fee_bps)) // 10_000
    nx = x + amount_in_af
    ny = (x * y) // max(1, nx)
    out = y - ny
    if out <= 0 or out >= y:
      return Trade(False, reason="no_out")
    spot = y / max(1, x)
    exec_px = out / max(1, amount_in)
    sl = max(0.0, (spot - exec_px) / max(1e-9, spot) * 100)
    return Trade(True, amount_out=out, fee_bps=self.fee_bps, slippage_pct=sl)

  def trade(self, ain: str, aout: str, amount_in: int, oracle_px: float) -> Trade:
    q = self.quote(ain, aout, amount_in)
    if not q.ok:
      return q
    p = self._pool(ain, aout)
    amount_in_af = (amount_in * (10_000 - self.fee_bps)) // 10_000
    p[ain] += amount_in_af
    p[aout] -= q.amount_out
    q.execution_quality = (q.amount_out / max(1, amount_in)) / max(1e-9, oracle_px)
    return q

  def reserves_total(self) -> Dict[str, int]:
    t = {a: 0 for a in ASSETS}
    for p in self.pools.values():
      for a, r in p.items():
        t[a] += r
    return t

  def tvl(self, oracle: Dict[str, float]) -> float:
    t = self.reserves_total()
    return sum(t[a] * oracle[a] for a in ASSETS)


class GeometricAMM:
  def __init__(
    self,
    reserve: int,
    center_curvature_bps: int = 4200,
    edge_curvature_bps: int = 1400,
    coupling_divisor: int = 40,
    imbalance_limit_bps: int = 6400,
    equilibrium_amplification_bps: int = 2200,
    tail_guard_bps: int = 2800,
    stress_memory_decay_bps: int = 9300,
    coupling_field_gain_bps: int = 2600,
    tension_soft_threshold_bps: int = 2800,
    tension_hard_threshold_bps: int = 5200,
    center_fee_floor_bps: int = 8,
    stress_fee_ceiling_bps: int = 130,
  ) -> None:
    self.r = {"A": reserve, "B": reserve, "C": reserve}
    self.lp_supply = reserve * 3
    self.center_curvature_bps = center_curvature_bps
    self.edge_curvature_bps = edge_curvature_bps
    self.coupling_divisor = coupling_divisor
    self.imbalance_limit_bps = imbalance_limit_bps
    self.equilibrium_amplification_bps = equilibrium_amplification_bps
    self.tail_guard_bps = tail_guard_bps
    self.stress_memory_decay_bps = stress_memory_decay_bps
    self.coupling_field_gain_bps = coupling_field_gain_bps
    self.tension_soft_threshold_bps = tension_soft_threshold_bps
    self.tension_hard_threshold_bps = tension_hard_threshold_bps
    self.center_fee_floor_bps = center_fee_floor_bps
    self.stress_fee_ceiling_bps = stress_fee_ceiling_bps
    self.stress_memory_bps = 0
    self.prev_r = dict(self.r)

  def _third(self, a: str, b: str) -> str:
    for x in ASSETS:
      if x != a and x != b:
        return x
    raise ValueError("bad pair")

  def dynamic_fee_bps(self, tension_bps: int) -> int:
    # Equilibrium efficiency: lower fee near center; stress premium away from center.
    if tension_bps <= self.tension_soft_threshold_bps:
      return self.center_fee_floor_bps + (tension_bps * 12) // max(1, self.tension_soft_threshold_bps)
    if tension_bps <= self.tension_hard_threshold_bps:
      return 20 + ((tension_bps - self.tension_soft_threshold_bps) * 55) // max(1, self.tension_hard_threshold_bps - self.tension_soft_threshold_bps)
    return self.stress_fee_ceiling_bps

  def curvature_bps(self, dom: int) -> int:
    if dom <= 3400:
      return self.center_curvature_bps
    if dom >= 6200:
      return self.edge_curvature_bps
    span = self.center_curvature_bps - self.edge_curvature_bps
    return self.center_curvature_bps - ((dom - 3400) * span) // 2800

  def _eff(self, x: int, curv: int, amp: int) -> int:
    # Hybrid center concentration:
    # amplification flattens local pricing around equilibrium by boosting effective local liquidity.
    return x + (isqrt(x) * (curv + amp)) // 10_000

  def _eff_inv(self, e: int, curv: int, amp: int) -> int:
    red = (isqrt(e) * (curv + amp)) // 10_000
    return max(1, e - red)

  def _inv(self, a: int, b: int, c: int, curv: int, amp: int) -> int:
    ea, eb, ec = self._eff(a, curv, amp), self._eff(b, curv, amp), self._eff(c, curv, amp)
    return ea * ea + eb * eb + ec * ec

  def reserve_tension_bps(self) -> int:
    a, b, c = self.r["A"], self.r["B"], self.r["C"]
    dom = dominance_bps(a, b, c)
    imb = imbalance_bps(a, b, c)
    sa = abs(a - self.prev_r["A"])
    sb = abs(b - self.prev_r["B"])
    sc = abs(c - self.prev_r["C"])
    vel = ((sa + sb + sc) * 10_000) // max(1, a + b + c)
    curvature_pressure = max(0, dom - 3600)
    base = (dom + imb + (vel * 8) + curvature_pressure) // 4
    memory_mix = ((self.stress_memory_bps * 5500) + (base * 4500)) // 10_000
    return min(10_000, memory_mix)

  def center_amplification_bps(self, tension_bps: int) -> int:
    # Strongest around equilibrium, decays under stress.
    if tension_bps >= self.tension_hard_threshold_bps:
      return 0
    return (self.equilibrium_amplification_bps * (self.tension_hard_threshold_bps - tension_bps)) // max(1, self.tension_hard_threshold_bps)

  def coupling_field_bps(self, tension_bps: int) -> int:
    # Field-like coupling: depends on global stress memory, not only local trade.
    field = (self.coupling_field_gain_bps * tension_bps) // 10_000
    return min(8000, field + (self.stress_memory_bps // 3))

  def spot(self, ain: str, aout: str) -> float:
    q = self.quote(ain, aout, 100)
    return q.amount_out / 100.0 if q.ok else 0.0

  def quote(self, ain: str, aout: str, amount_in: int) -> Trade:
    if amount_in <= 0 or ain == aout:
      return Trade(False, reason="invalid")
    rin = self.r[ain]
    rout = self.r[aout]
    t = self._third(ain, aout)
    r3 = self.r[t]
    if rin < 20 or amount_in > rin // 20:
      return Trade(False, reason="size_guard")
    dom = dominance_bps(self.r["A"], self.r["B"], self.r["C"])
    if dom > self.imbalance_limit_bps:
      return Trade(False, reason="dominance_guard")
    tension = self.reserve_tension_bps()
    fee = self.dynamic_fee_bps(tension)
    ain_af = (amount_in * (10_000 - fee)) // 10_000
    if ain_af <= 0:
      return Trade(False, reason="zero_after_fee")
    nrin = rin + ain_af
    base = (r3 * ain_af) // max(1, rin * self.coupling_divisor)
    base = max(1, base)
    trade_size_bps = (ain_af * 10_000) // rin
    size_pressure = isqrt(trade_size_bps * 10_000)
    field = self.coupling_field_bps(tension)
    imb_pressure = max(0, dom - 3600)
    d3 = (base * (1800 + size_pressure + imb_pressure + field)) // 10_000
    d3 = max(1, min(d3, r3 - 1))
    nr3 = r3 - d3
    curv = self.curvature_bps(dom)
    amp = self.center_amplification_bps(tension)
    k = self._inv(self.r["A"], self.r["B"], self.r["C"], curv, amp)
    target_sq = k - self._eff(nrin, curv, amp) ** 2 - self._eff(nr3, curv, amp) ** 2
    if target_sq <= 0:
      return Trade(False, reason="inv_exhaust")
    eff_out = isqrt(target_sq)
    nrout = self._eff_inv(eff_out, curv, amp)
    out = rout - nrout
    if out <= 0 or out >= rout:
      return Trade(False, reason="no_out")
    # Tail suppression: asymptotic damping for edge-of-surface behavior.
    trade_frac_bps = (amount_in * 10_000) // max(1, rin)
    tail_pressure = max(0, trade_frac_bps - self.tail_guard_bps)
    if tail_pressure > 0:
      damp = min(7000, (tail_pressure * 7000) // max(1, 10_000 - self.tail_guard_bps))
      out = max(1, (out * (10_000 - damp)) // 10_000)
    spot = rout / max(1, rin)
    exec_px = out / max(1, amount_in)
    sl = max(0.0, (spot - exec_px) / max(1e-9, spot) * 100)
    return Trade(True, amount_out=out, fee_bps=fee, slippage_pct=sl)

  def trade(self, ain: str, aout: str, amount_in: int, oracle_px: float) -> Trade:
    q = self.quote(ain, aout, amount_in)
    if not q.ok:
      return q
    rin = self.r[ain]
    t = self._third(ain, aout)
    dom = dominance_bps(self.r["A"], self.r["B"], self.r["C"])
    tension = self.reserve_tension_bps()
    fee = q.fee_bps
    ain_af = (amount_in * (10_000 - fee)) // 10_000
    self.r[ain] = rin + ain_af
    self.r[aout] -= q.amount_out
    r3 = self.r[t]
    base = (r3 * ain_af) // max(1, rin * self.coupling_divisor)
    base = max(1, base)
    trade_size_bps = (ain_af * 10_000) // rin
    size_pressure = isqrt(trade_size_bps * 10_000)
    imb_pressure = max(0, dom - 3600)
    field = self.coupling_field_bps(tension)
    d3 = (base * (1800 + size_pressure + imb_pressure + field)) // 10_000
    d3 = max(1, min(d3, r3 - 1))
    self.r[t] = r3 - d3
    # update stress memory and reserve velocity anchors
    next_tension = self.reserve_tension_bps()
    self.stress_memory_bps = ((self.stress_memory_bps * self.stress_memory_decay_bps) + (next_tension * (10_000 - self.stress_memory_decay_bps))) // 10_000
    self.prev_r = dict(self.r)
    q.execution_quality = (q.amount_out / max(1, amount_in)) / max(1e-9, oracle_px)
    return q

  def reserves_total(self) -> Dict[str, int]:
    return dict(self.r)

  def tvl(self, oracle: Dict[str, float]) -> float:
    return sum(self.r[a] * oracle[a] for a in ASSETS)


class LocalizedGeometricAMM:
  """
  Orbital-style localized geometric liquidity:
  - Region 0: balanced core (deep, soft, low fee)
  - Region 1: mid imbalance
  - Region 2: edge protection (thin, hard, high fee)
  """

  def __init__(self, reserve: int) -> None:
    self.r = {"A": reserve, "B": reserve, "C": reserve}
    self.lp_supply = reserve * 3
    self.region_lp = {0: self.lp_supply * 60 // 100, 1: self.lp_supply * 30 // 100, 2: self.lp_supply * 10 // 100}
    self.region_utilization = {0: 0.0, 1: 0.0, 2: 0.0}
    self.region_params = {
      0: {"curv": 5200, "fee": 10, "coupling_div": 70, "liq_mult_bps": 15500},
      1: {"curv": 3000, "fee": 30, "coupling_div": 40, "liq_mult_bps": 10000},
      2: {"curv": 1400, "fee": 95, "coupling_div": 24, "liq_mult_bps": 6800},
    }

  def _third(self, a: str, b: str) -> str:
    for x in ASSETS:
      if x != a and x != b:
        return x
    raise ValueError("bad pair")

  def current_region(self) -> int:
    imb = imbalance_bps(self.r["A"], self.r["B"], self.r["C"])
    if imb < 3600:
      return 0
    if imb < 5000:
      return 1
    return 2

  def _eff(self, x: int, curv: int) -> int:
    return x + (isqrt(x) * curv) // 10_000

  def _eff_inv(self, e: int, curv: int) -> int:
    red = (isqrt(e) * curv) // 10_000
    return max(1, e - red)

  def _inv(self, a: int, b: int, c: int, curv: int) -> int:
    ea, eb, ec = self._eff(a, curv), self._eff(b, curv), self._eff(c, curv)
    return ea * ea + eb * eb + ec * ec

  def _apply_region_quote(self, ain: str, aout: str, amount_in: int, region: int) -> Trade:
    if amount_in <= 0:
      return Trade(False, reason="invalid")
    p = self.region_params[region]
    rin = self.r[ain]
    rout = self.r[aout]
    t = self._third(ain, aout)
    r3 = self.r[t]
    # localized liquidity scaling: amplify/de-amplify effective tradable depth
    liq_mult = p["liq_mult_bps"]
    rin_eff_base = (rin * liq_mult) // 10_000
    rout_eff_base = (rout * liq_mult) // 10_000
    r3_eff_base = (r3 * liq_mult) // 10_000
    if rin_eff_base < 20:
      return Trade(False, reason="size_guard")
    if amount_in > rin_eff_base // 14:
      return Trade(False, reason="region_size_guard")

    fee = p["fee"]
    ain_af = (amount_in * (10_000 - fee)) // 10_000
    if ain_af <= 0:
      return Trade(False, reason="zero_after_fee")

    nrin_eff = rin_eff_base + ain_af
    base = (r3_eff_base * ain_af) // max(1, rin_eff_base * p["coupling_div"])
    base = max(1, base)
    d3 = max(1, min(base, r3_eff_base - 1))
    nr3_eff = r3_eff_base - d3

    curv = p["curv"]
    k = self._inv(rin_eff_base, rout_eff_base, r3_eff_base, curv)
    target_sq = k - self._eff(nrin_eff, curv) ** 2 - self._eff(nr3_eff, curv) ** 2
    if target_sq <= 0:
      return Trade(False, reason="inv_exhaust")
    eff_out = isqrt(target_sq)
    nrout_eff = self._eff_inv(eff_out, curv)
    out_eff = rout_eff_base - nrout_eff
    if out_eff <= 0 or out_eff >= rout_eff_base:
      return Trade(False, reason="no_out")

    # map localized effective outputs back to real reserve domain
    out = max(1, (out_eff * 10_000) // liq_mult)
    out = min(out, max(1, rout - 1))
    spot = rout / max(1, rin)
    exec_px = out / max(1, amount_in)
    sl = max(0.0, (spot - exec_px) / max(1e-9, spot) * 100)
    return Trade(True, amount_out=out, fee_bps=fee, slippage_pct=sl)

  def quote(self, ain: str, aout: str, amount_in: int) -> Trade:
    if amount_in <= 0 or ain == aout:
      return Trade(False, reason="invalid")
    region = self.current_region()
    # smooth transition by blending chunks across neighboring regions
    chunks: list[tuple[int, int]] = []
    if region == 0:
      chunks = [(0, 60), (1, 30), (2, 10)]
    elif region == 1:
      chunks = [(0, 20), (1, 60), (2, 20)]
    else:
      chunks = [(0, 10), (1, 25), (2, 65)]

    total_out = 0
    total_sl = 0.0
    total_fee_weight = 0
    remaining = amount_in
    for idx, w in chunks:
      if remaining <= 0:
        break
      chunk_in = max(1, (amount_in * w) // 100)
      chunk_in = min(chunk_in, remaining)
      q = self._apply_region_quote(ain, aout, chunk_in, idx)
      if not q.ok:
        # gentle failover to next region, avoid hard cliff
        continue
      total_out += q.amount_out
      total_sl += q.slippage_pct * chunk_in
      total_fee_weight += q.fee_bps * chunk_in
      remaining -= chunk_in
    if total_out <= 0:
      return Trade(False, reason="all_regions_exhausted")
    avg_sl = total_sl / max(1, amount_in - remaining)
    avg_fee = total_fee_weight // max(1, amount_in - remaining)
    return Trade(True, amount_out=total_out, fee_bps=avg_fee, slippage_pct=avg_sl)

  def trade(self, ain: str, aout: str, amount_in: int, oracle_px: float) -> Trade:
    q = self.quote(ain, aout, amount_in)
    if not q.ok:
      return q
    # reserve updates use realized avg fee and damped 3rd coupling
    rin = self.r[ain]
    rout = self.r[aout]
    t = self._third(ain, aout)
    r3 = self.r[t]
    ain_af = (amount_in * (10_000 - q.fee_bps)) // 10_000
    self.r[ain] = rin + ain_af
    self.r[aout] = max(1, rout - q.amount_out)
    # coupling linked to active region
    reg = self.current_region()
    div = self.region_params[reg]["coupling_div"]
    d3 = max(1, (r3 * ain_af) // max(1, rin * div))
    self.r[t] = max(1, r3 - d3)
    self.region_utilization[reg] += float(amount_in)
    q.execution_quality = (q.amount_out / max(1, amount_in)) / max(1e-9, oracle_px)
    return q

  def spot(self, ain: str, aout: str) -> float:
    q = self.quote(ain, aout, 100)
    return q.amount_out / 100.0 if q.ok else 0.0

  def reserves_total(self) -> Dict[str, int]:
    return dict(self.r)

  def tvl(self, oracle: Dict[str, float]) -> float:
    return sum(self.r[a] * oracle[a] for a in ASSETS)
