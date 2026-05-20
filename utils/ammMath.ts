const SCALE_BPS = 10_000n
const MAX_RESERVE = 100_000_000n

function toBigInt(value: number): bigint {
  return BigInt(Math.floor(value))
}

function safeSquare(x: bigint): bigint {
  if (x < 0n || x > 4_000_000_000n) throw new Error('square bound exceeded')
  return x * x
}

function safeSub(a: bigint, b: bigint): bigint {
  if (a < b) throw new Error('underflow')
  return a - b
}

function invariant3(a: bigint, b: bigint, c: bigint): bigint {
  return safeSquare(a) + safeSquare(b) + safeSquare(c)
}

function sqrtFloor(value: bigint): bigint {
  if (value < 0n) throw new Error('sqrt negative')
  if (value < 2n) return value
  let x0 = value
  let x1 = (x0 + value / x0) / 2n
  while (x1 < x0) {
    x0 = x1
    x1 = (x0 + value / x0) / 2n
  }
  return x0
}

function dominanceBps(a: bigint, b: bigint, c: bigint, k: bigint): bigint {
  const aSq = safeSquare(a)
  const bSq = safeSquare(b)
  const cSq = safeSquare(c)
  const maxSq = aSq > bSq ? (aSq > cSq ? aSq : cSq) : bSq > cSq ? bSq : cSq
  return (maxSq * SCALE_BPS) / k
}

function dynamicFeeBpsFromDom(dom: bigint): bigint {
  if (dom <= 3_300n) return 18n
  if (dom <= 4_900n) return 18n + ((dom - 3_300n) * 32n) / 1_600n
  if (dom <= 6_200n) return 50n + ((dom - 4_900n) * 40n) / 1_300n
  return 90n
}

function couplingAdjustment(reserveIn: bigint, reserveThird: bigint, amountInAfterFee: bigint, domBps: bigint): bigint {
  const denom = reserveIn * 40n
  let base = (reserveThird * amountInAfterFee) / denom
  if (base <= 0n) base = 1n
  const tradeSizeBps = (amountInAfterFee * SCALE_BPS) / reserveIn
  const sizePressure = sqrtFloor(tradeSizeBps * SCALE_BPS)
  const imbalancePressure = domBps > 3_600n ? domBps - 3_600n : 0n
  let weighted = (base * (2_500n + sizePressure + imbalancePressure)) / SCALE_BPS
  if (weighted <= 0n) weighted = 1n
  const maxAdjust = reserveThird - 1n
  return weighted > maxAdjust ? maxAdjust : weighted
}

function curvatureBps(dom: bigint): bigint {
  if (dom <= 3_400n) return 4_200n
  if (dom >= 6_200n) return 1_400n
  return 4_200n - ((dom - 3_400n) * 2_800n) / 2_800n
}

function effectiveReserve(x: bigint, curvBps: bigint): bigint {
  return x + (sqrtFloor(x) * curvBps) / SCALE_BPS
}

function inverseEffectiveReserve(eff: bigint, curvBps: bigint): bigint {
  const reduction = (sqrtFloor(eff) * curvBps) / SCALE_BPS
  if (reduction >= eff) return 1n
  const v = eff - reduction
  return v <= 0n ? 1n : v
}

export type OrbitalQuote = {
  amountOut: number
  feeBps: number
  dominanceBps: number
  imbalanceRatio: number
  couplingAdjustment: number
  newReserveIn: number
  newReserveOut: number
  newReserveThird: number
}

export function geometricLiquidityMetric(aN: number, bN: number, cN: number): number {
  const a = toBigInt(aN)
  const b = toBigInt(bN)
  const c = toBigInt(cN)
  const rawK = invariant3(a, b, c)
  const dom = dominanceBps(a, b, c, rawK)
  const curv = curvatureBps(dom)
  const k = safeSquare(effectiveReserve(a, curv)) + safeSquare(effectiveReserve(b, curv)) + safeSquare(effectiveReserve(c, curv))
  return Number(sqrtFloor(k))
}

export function imbalanceBps(aN: number, bN: number, cN: number): number {
  const a = toBigInt(aN)
  const b = toBigInt(bN)
  const c = toBigInt(cN)
  const sum = a + b + c
  if (sum <= 0n) return 0
  const maxReserve = a > b ? (a > c ? a : c) : b > c ? b : c
  return Number((maxReserve * SCALE_BPS) / sum)
}

export function depositPenaltyBps(depositImbalanceBps: number): number {
  if (depositImbalanceBps <= 3600) return 0
  if (depositImbalanceBps <= 4800) return Math.floor((depositImbalanceBps - 3600) / 12)
  if (depositImbalanceBps >= 7500) return 650
  return 100 + Math.floor(((depositImbalanceBps - 4800) * 550) / 2700)
}

export function quoteAddLiquidity(
  reserveA: number,
  reserveB: number,
  reserveC: number,
  totalLpSupply: number,
  amountA: number,
  amountB: number,
  amountC: number,
): { lpOut: number; lpRaw: number; penaltyBps: number; depositImbalanceBps: number } {
  const poolValue = geometricLiquidityMetric(reserveA, reserveB, reserveC)
  const depositValue = geometricLiquidityMetric(amountA, amountB, amountC)
  if (poolValue <= 0 || depositValue <= 0) return { lpOut: 0, lpRaw: 0, penaltyBps: 0, depositImbalanceBps: 0 }
  const lpRaw = totalLpSupply <= 0 ? depositValue : Math.floor((depositValue * totalLpSupply) / poolValue)
  const depImb = imbalanceBps(amountA, amountB, amountC)
  const penalty = depositPenaltyBps(depImb)
  const lpOut = Math.floor((lpRaw * (10_000 - penalty)) / 10_000)
  return { lpOut, lpRaw, penaltyBps: penalty, depositImbalanceBps: depImb }
}

export function quoteRemoveLiquidity(
  reserveA: number,
  reserveB: number,
  reserveC: number,
  totalLpSupply: number,
  lpAmount: number,
): { amountAOut: number; amountBOut: number; amountCOut: number } {
  if (totalLpSupply <= 0 || lpAmount <= 0) return { amountAOut: 0, amountBOut: 0, amountCOut: 0 }
  return {
    amountAOut: Math.floor((reserveA * lpAmount) / totalLpSupply),
    amountBOut: Math.floor((reserveB * lpAmount) / totalLpSupply),
    amountCOut: Math.floor((reserveC * lpAmount) / totalLpSupply),
  }
}

export function quoteOrbitalExactIn(reserveInN: number, reserveOutN: number, reserveThirdN: number, amountInN: number): OrbitalQuote {
  const reserveIn = toBigInt(reserveInN)
  const reserveOut = toBigInt(reserveOutN)
  const reserveThird = toBigInt(reserveThirdN)
  const amountIn = toBigInt(amountInN)

  if (reserveIn <= 0n || reserveOut <= 0n || reserveThird <= 1n || amountIn <= 0n) {
    return { amountOut: 0, feeBps: 0, dominanceBps: 0, imbalanceRatio: 0, couplingAdjustment: 0, newReserveIn: Number(reserveIn), newReserveOut: Number(reserveOut), newReserveThird: Number(reserveThird) }
  }
  if (reserveIn > MAX_RESERVE || reserveOut > MAX_RESERVE || reserveThird > MAX_RESERVE) {
    return { amountOut: 0, feeBps: 0, dominanceBps: 0, imbalanceRatio: 0, couplingAdjustment: 0, newReserveIn: Number(reserveIn), newReserveOut: Number(reserveOut), newReserveThird: Number(reserveThird) }
  }
  if (reserveIn < 20n || amountIn > reserveIn / 20n) {
    return { amountOut: 0, feeBps: 0, dominanceBps: 0, imbalanceRatio: 0, couplingAdjustment: 0, newReserveIn: Number(reserveIn), newReserveOut: Number(reserveOut), newReserveThird: Number(reserveThird) }
  }

  const rawK = invariant3(reserveIn, reserveOut, reserveThird)
  const dom = dominanceBps(reserveIn, reserveOut, reserveThird, rawK)
  if (dom > 6_400n) {
    return { amountOut: 0, feeBps: Number(dynamicFeeBpsFromDom(dom)), dominanceBps: Number(dom), imbalanceRatio: Number(dom) / 10_000, couplingAdjustment: 0, newReserveIn: Number(reserveIn), newReserveOut: Number(reserveOut), newReserveThird: Number(reserveThird) }
  }

  const feeBps = dynamicFeeBpsFromDom(dom)
  const amountInAfterFee = (amountIn * (SCALE_BPS - feeBps)) / SCALE_BPS
  if (amountInAfterFee <= 0n) {
    return { amountOut: 0, feeBps: Number(feeBps), dominanceBps: Number(dom), imbalanceRatio: Number(dom) / 10_000, couplingAdjustment: 0, newReserveIn: Number(reserveIn), newReserveOut: Number(reserveOut), newReserveThird: Number(reserveThird) }
  }

  const newReserveIn = reserveIn + amountInAfterFee
  const deltaThird = couplingAdjustment(reserveIn, reserveThird, amountInAfterFee, dom)
  const newReserveThird = safeSub(reserveThird, deltaThird)
  const curv = curvatureBps(dom)
  const k = safeSquare(effectiveReserve(reserveIn, curv)) + safeSquare(effectiveReserve(reserveOut, curv)) + safeSquare(effectiveReserve(reserveThird, curv))
  const targetOutSq = safeSub(safeSub(k, safeSquare(effectiveReserve(newReserveIn, curv))), safeSquare(effectiveReserve(newReserveThird, curv)))
  const targetOutEff = sqrtFloor(targetOutSq)
  const newReserveOut = inverseEffectiveReserve(targetOutEff, curv)
  if (newReserveOut > reserveOut) {
    return { amountOut: 0, feeBps: Number(feeBps), dominanceBps: Number(dom), imbalanceRatio: Number(dom) / 10_000, couplingAdjustment: Number(deltaThird), newReserveIn: Number(newReserveIn), newReserveOut: Number(newReserveOut), newReserveThird: Number(newReserveThird) }
  }
  const amountOut = safeSub(reserveOut, newReserveOut)

  return {
    amountOut: Number(amountOut),
    feeBps: Number(feeBps),
    dominanceBps: Number(dom),
    imbalanceRatio: Number(dom) / 10_000,
    couplingAdjustment: Number(deltaThird),
    newReserveIn: Number(newReserveIn),
    newReserveOut: Number(newReserveOut),
    newReserveThird: Number(newReserveThird),
  }
}
