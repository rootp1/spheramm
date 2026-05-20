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
  ) -> None:
    self.r = {"A": reserve, "B": reserve, "C": reserve}
    self.lp_supply = reserve * 3
    self.center_curvature_bps = center_curvature_bps
    self.edge_curvature_bps = edge_curvature_bps
    self.coupling_divisor = coupling_divisor
    self.imbalance_limit_bps = imbalance_limit_bps

  def _third(self, a: str, b: str) -> str:
    for x in ASSETS:
      if x != a and x != b:
        return x
    raise ValueError("bad pair")

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
      return self.center_curvature_bps
    if dom >= 6200:
      return self.edge_curvature_bps
    span = self.center_curvature_bps - self.edge_curvature_bps
    return self.center_curvature_bps - ((dom - 3400) * span) // 2800

  def _eff(self, x: int, curv: int) -> int:
    return x + (isqrt(x) * curv) // 10_000

  def _eff_inv(self, e: int, curv: int) -> int:
    red = (isqrt(e) * curv) // 10_000
    return max(1, e - red)

  def _inv(self, a: int, b: int, c: int, curv: int) -> int:
    ea, eb, ec = self._eff(a, curv), self._eff(b, curv), self._eff(c, curv)
    return ea * ea + eb * eb + ec * ec

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
    fee = self.dynamic_fee_bps(dom)
    ain_af = (amount_in * (10_000 - fee)) // 10_000
    if ain_af <= 0:
      return Trade(False, reason="zero_after_fee")
    nrin = rin + ain_af
    base = (r3 * ain_af) // max(1, rin * self.coupling_divisor)
    base = max(1, base)
    trade_size_bps = (ain_af * 10_000) // rin
    size_pressure = isqrt(trade_size_bps * 10_000)
    imb_pressure = max(0, dom - 3600)
    d3 = (base * (2500 + size_pressure + imb_pressure)) // 10_000
    d3 = max(1, min(d3, r3 - 1))
    nr3 = r3 - d3
    curv = self.curvature_bps(dom)
    k = self._inv(self.r["A"], self.r["B"], self.r["C"], curv)
    target_sq = k - self._eff(nrin, curv) ** 2 - self._eff(nr3, curv) ** 2
    if target_sq <= 0:
      return Trade(False, reason="inv_exhaust")
    eff_out = isqrt(target_sq)
    nrout = self._eff_inv(eff_out, curv)
    out = rout - nrout
    if out <= 0 or out >= rout:
      return Trade(False, reason="no_out")
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
    d3 = (base * (2500 + size_pressure + imb_pressure)) // 10_000
    d3 = max(1, min(d3, r3 - 1))
    self.r[t] = r3 - d3
    q.execution_quality = (q.amount_out / max(1, amount_in)) / max(1e-9, oracle_px)
    return q

  def reserves_total(self) -> Dict[str, int]:
    return dict(self.r)

  def tvl(self, oracle: Dict[str, float]) -> float:
    return sum(self.r[a] * oracle[a] for a in ASSETS)

