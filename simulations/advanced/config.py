from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RegimeName = Literal[
  "random_market",
  "correlated_basket",
  "volatile_divergent",
  "liquidity_fragmentation",
  "crisis_bank_run",
]


@dataclass
class MarketConfig:
  seed: int = 42
  steps: int = 2500
  base_reserve: int = 1_000_000
  pair_fee_bps: int = 30
  geometric_center_curvature_bps: int = 4200
  geometric_edge_curvature_bps: int = 1400
  geometric_coupling_divisor: int = 40
  geometric_imbalance_limit_bps: int = 6400
  regime: RegimeName = "random_market"


@dataclass
class AgentConfig:
  retail_intensity: float = 0.80
  retail_avg_size: int = 7000
  retail_size_jitter: int = 5000
  retail_directional_persistence: float = 0.25
  retail_vol_sensitivity: float = 0.5

  arb_intensity: float = 0.40
  arb_threshold_bps: int = 25
  arb_aggressiveness: float = 1.0
  arb_profit_threshold_value: float = 0.0
  arb_capital_per_trade: int = 4000

  whale_intensity: float = 0.10
  whale_avg_size: int = 35000
  whale_directional_bias: float = 0.8

  lp_rebalance_interval: int = 50
  lp_migration_sensitivity: float = 0.4
  lp_total_capital_value: float = 500_000.0

  basket_intensity: float = 0.35
  basket_rotation_size: int = 8000
  basket_triangular_bias: float = 0.7

