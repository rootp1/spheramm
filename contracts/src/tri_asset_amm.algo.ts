import type { uint64 } from '@algorandfoundation/algorand-typescript'
import {
  Account,
  assert,
  Contract,
  Global,
  GlobalState,
  LocalState,
  gtxn,
  itxn,
  op,
  Txn,
} from '@algorandfoundation/algorand-typescript'

export class TriAssetAmm extends Contract {
  assetAId = GlobalState<uint64>()
  assetBId = GlobalState<uint64>()
  assetCId = GlobalState<uint64>()

  reserveA = GlobalState<uint64>()
  reserveB = GlobalState<uint64>()
  reserveC = GlobalState<uint64>()

  feeBps = GlobalState<uint64>()
  admin = GlobalState<Account>()
  paused = GlobalState<boolean>()
  totalLiquidity = GlobalState<uint64>()
  totalLpSupply = GlobalState<uint64>()
  lpAssetId = GlobalState<uint64>()
  lpBalance = LocalState<uint64>()

  public createApplication(): void {
    this.assetAId.value = 0
    this.assetBId.value = 0
    this.assetCId.value = 0

    this.reserveA.value = 0
    this.reserveB.value = 0
    this.reserveC.value = 0

    this.feeBps.value = 0
    this.admin.value = Txn.sender
    this.paused.value = false
    this.totalLiquidity.value = 0
    this.totalLpSupply.value = 0
    this.lpAssetId.value = 0
  }

  public create_pool(
    assetA: uint64,
    assetB: uint64,
    assetC: uint64,
    amountA: uint64,
    amountB: uint64,
    amountC: uint64,
    feeBps: uint64,
  ): void {
    assert(this.assetAId.value === 0, 'pool already initialized')
    assert(assetA > 0 && assetB > 0 && assetC > 0, 'invalid asset ids')
    assert(assetA !== assetB && assetA !== assetC && assetB !== assetC, 'duplicate assets')
    assert(amountA > 0 && amountB > 0 && amountC > 0, 'invalid initial amounts')
    assert(amountA <= 100_000_000 && amountB <= 100_000_000 && amountC <= 100_000_000, 'reserve cap exceeded')
    assert(feeBps <= 1000, 'fee too high')

    assert(Global.groupSize === 4, 'invalid group size')

    const tx0 = gtxn.AssetTransferTxn(0)
    const tx1 = gtxn.AssetTransferTxn(1)
    const tx2 = gtxn.AssetTransferTxn(2)

    assert(tx0.sender === Txn.sender && tx1.sender === Txn.sender && tx2.sender === Txn.sender, 'sender mismatch')
    assert(tx0.assetReceiver === Global.currentApplicationAddress, 'a receiver invalid')
    assert(tx1.assetReceiver === Global.currentApplicationAddress, 'b receiver invalid')
    assert(tx2.assetReceiver === Global.currentApplicationAddress, 'c receiver invalid')

    assert(tx0.xferAsset.id === assetA && tx0.assetAmount === amountA, 'asset A funding mismatch')
    assert(tx1.xferAsset.id === assetB && tx1.assetAmount === amountB, 'asset B funding mismatch')
    assert(tx2.xferAsset.id === assetC && tx2.assetAmount === amountC, 'asset C funding mismatch')

    this.assetAId.value = assetA
    this.assetBId.value = assetB
    this.assetCId.value = assetC

    this.reserveA.value = amountA
    this.reserveB.value = amountB
    this.reserveC.value = amountC

    this.feeBps.value = feeBps
    this.admin.value = Txn.sender
    this.paused.value = false

    const liqPartial: uint64 = amountA + amountB
    assert(liqPartial >= amountA && liqPartial >= amountB, 'liquidity overflow')
    const liqTotal: uint64 = liqPartial + amountC
    assert(liqTotal >= liqPartial, 'liquidity overflow')
    this.totalLiquidity.value = liqTotal
    this.totalLpSupply.value = liqTotal
  }

  public add_liquidity(amountA: uint64, amountB: uint64, amountC: uint64, minLpOut: uint64): uint64 {
    assert(this.assetAId.value > 0, 'pool not initialized')
    assert(!this.paused.value, 'pool paused')
    assert(amountA > 0 && amountB > 0 && amountC > 0, 'invalid deposit amounts')
    assert(Global.groupSize === 4, 'group size must be 4')

    const txA = gtxn.AssetTransferTxn(0)
    const txB = gtxn.AssetTransferTxn(1)
    const txC = gtxn.AssetTransferTxn(2)

    assert(txA.sender === Txn.sender && txB.sender === Txn.sender && txC.sender === Txn.sender, 'sender mismatch')
    assert(txA.assetReceiver === Global.currentApplicationAddress, 'a receiver invalid')
    assert(txB.assetReceiver === Global.currentApplicationAddress, 'b receiver invalid')
    assert(txC.assetReceiver === Global.currentApplicationAddress, 'c receiver invalid')
    assert(txA.xferAsset.id === this.assetAId.value && txA.assetAmount === amountA, 'asset A mismatch')
    assert(txB.xferAsset.id === this.assetBId.value && txB.assetAmount === amountB, 'asset B mismatch')
    assert(txC.xferAsset.id === this.assetCId.value && txC.assetAmount === amountC, 'asset C mismatch')

    const [lpOut] = this.quote_add_liquidity(amountA, amountB, amountC)
    assert(lpOut >= minLpOut, 'lp slippage exceeded')
    assert(lpOut > 0, 'lpOut zero')

    this.reserveA.value = this.reserveA.value + amountA
    this.reserveB.value = this.reserveB.value + amountB
    this.reserveC.value = this.reserveC.value + amountC
    assert(this.reserveA.value <= 100_000_000 && this.reserveB.value <= 100_000_000 && this.reserveC.value <= 100_000_000, 'reserve cap exceeded')

    this.totalLpSupply.value = this.totalLpSupply.value + lpOut
    this.totalLiquidity.value = this.totalLpSupply.value
    this.lpBalance(Txn.sender).value = this.lpBalance(Txn.sender).value + lpOut
    return lpOut
  }

  public remove_liquidity(lpAmount: uint64, minAOut: uint64, minBOut: uint64, minCOut: uint64): [uint64, uint64, uint64] {
    assert(this.assetAId.value > 0, 'pool not initialized')
    assert(!this.paused.value, 'pool paused')
    assert(lpAmount > 0, 'lp amount must be positive')
    assert(this.totalLpSupply.value > 0, 'no LP supply')

    const userLp = this.lpBalance(Txn.sender).value
    assert(userLp >= lpAmount, 'insufficient LP balance')

    const [amountAOut, amountBOut, amountCOut] = this.quote_remove_liquidity(lpAmount)
    assert(amountAOut >= minAOut && amountBOut >= minBOut && amountCOut >= minCOut, 'withdraw slippage exceeded')
    assert(amountAOut > 0 && amountBOut > 0 && amountCOut > 0, 'withdraw amounts zero')

    const newReserveA = this.safeSub(this.reserveA.value, amountAOut)
    const newReserveB = this.safeSub(this.reserveB.value, amountBOut)
    const newReserveC = this.safeSub(this.reserveC.value, amountCOut)
    const rawKAfter = this.rawInvariant(newReserveA, newReserveB, newReserveC)
    this.validatePoolHealth(newReserveA, newReserveB, newReserveC, rawKAfter)

    this.reserveA.value = newReserveA
    this.reserveB.value = newReserveB
    this.reserveC.value = newReserveC

    this.totalLpSupply.value = this.safeSub(this.totalLpSupply.value, lpAmount)
    this.totalLiquidity.value = this.totalLpSupply.value
    this.lpBalance(Txn.sender).value = this.safeSub(this.lpBalance(Txn.sender).value, lpAmount)

    itxn.assetTransfer({ xferAsset: this.assetAId.value, assetReceiver: Txn.sender, assetAmount: amountAOut, fee: 0 }).submit()
    itxn.assetTransfer({ xferAsset: this.assetBId.value, assetReceiver: Txn.sender, assetAmount: amountBOut, fee: 0 }).submit()
    itxn.assetTransfer({ xferAsset: this.assetCId.value, assetReceiver: Txn.sender, assetAmount: amountCOut, fee: 0 }).submit()

    return [amountAOut, amountBOut, amountCOut]
  }

  public get_lp_state(): [uint64, uint64, uint64, uint64] {
    return [this.totalLpSupply.value, this.lpBalance(Txn.sender).value, this.geometricLiquidity(this.reserveA.value, this.reserveB.value, this.reserveC.value), this.imbalanceBps(this.reserveA.value, this.reserveB.value, this.reserveC.value)]
  }

  public get_pool_value(): uint64 {
    return this.geometricLiquidity(this.reserveA.value, this.reserveB.value, this.reserveC.value)
  }

  public quote_add_liquidity(amountA: uint64, amountB: uint64, amountC: uint64): [uint64, uint64, uint64, uint64] {
    assert(amountA > 0 && amountB > 0 && amountC > 0, 'invalid deposit amounts')
    const poolValue = this.geometricLiquidity(this.reserveA.value, this.reserveB.value, this.reserveC.value)
    const depositValue = this.geometricLiquidity(amountA, amountB, amountC)
    assert(poolValue > 0 && depositValue > 0, 'invalid liquidity values')

    let lpRaw: uint64 = 0
    if (this.totalLpSupply.value === 0) {
      lpRaw = depositValue
    } else {
      lpRaw = (depositValue * this.totalLpSupply.value) / poolValue
    }
    assert(lpRaw > 0, 'lpRaw zero')

    const depositImbalance = this.imbalanceBps(amountA, amountB, amountC)
    const penaltyBps = this.computeDepositPenaltyBps(depositImbalance)
    const lpOut: uint64 = (lpRaw * (10_000 - penaltyBps)) / 10_000
    assert(lpOut > 0, 'lpOut zero')
    return [lpOut, lpRaw, penaltyBps, depositImbalance]
  }

  public quote_remove_liquidity(lpAmount: uint64): [uint64, uint64, uint64] {
    assert(this.totalLpSupply.value > 0, 'no LP supply')
    assert(lpAmount > 0 && lpAmount <= this.totalLpSupply.value, 'invalid lpAmount')
    const amountAOut: uint64 = (this.reserveA.value * lpAmount) / this.totalLpSupply.value
    const amountBOut: uint64 = (this.reserveB.value * lpAmount) / this.totalLpSupply.value
    const amountCOut: uint64 = (this.reserveC.value * lpAmount) / this.totalLpSupply.value
    return [amountAOut, amountBOut, amountCOut]
  }

  public quote_swap_exact_in(assetInId: uint64, amountIn: uint64): uint64 {
    assert(this.assetAId.value > 0, 'pool not initialized')
    assert(this.reserveA.value > 0 && this.reserveB.value > 0 && this.reserveC.value > 0, 'pool assets not active')
    assert(amountIn > 0, 'amountIn must be positive')
    assert(Txn.numAssets >= 1, 'missing output asset')

    const assetOutId = Txn.assets(0).id
    assert(this.isPoolAsset(assetInId), 'assetIn unsupported')
    assert(this.isPoolAsset(assetOutId), 'assetOut unsupported')
    assert(assetOutId !== assetInId, 'same asset pair invalid')

    const reserveIn = this.getReserveByAssetId(assetInId)
    const reserveOut = this.getReserveByAssetId(assetOutId)
    const reserveThird = this.getThirdReserveByAssetIds(assetInId, assetOutId)
    const [amountOut] = this.quoteOutput(reserveIn, reserveOut, reserveThird, amountIn)
    return amountOut
  }

  public swap_exact_in(assetInId: uint64, amountIn: uint64, minAmountOut: uint64): uint64 {
    assert(this.assetAId.value > 0, 'pool not initialized')
    assert(!this.paused.value, 'pool paused')
    assert(this.reserveA.value > 0 && this.reserveB.value > 0 && this.reserveC.value > 0, 'pool assets not active')

    assert(Global.groupSize === 2, 'group size must be 2')
    const transfer = gtxn.AssetTransferTxn(0)

    assert(transfer.sender === Txn.sender, 'sender mismatch')
    assert(transfer.assetReceiver === Global.currentApplicationAddress, 'receiver must be app')
    assert(transfer.xferAsset.id === assetInId, 'assetIn mismatch')
    assert(transfer.assetAmount === amountIn, 'amount mismatch')
    assert(amountIn > 0, 'amountIn must be positive')
    assert(Txn.numAssets >= 1, 'missing output asset in foreign assets')

    const assetOutId = Txn.assets(0).id
    assert(this.isPoolAsset(assetInId), 'assetIn unsupported')
    assert(this.isPoolAsset(assetOutId), 'assetOut unsupported')
    assert(assetOutId !== assetInId, 'output asset must differ')

    const reserveIn = this.getReserveByAssetId(assetInId)
    const reserveOut = this.getReserveByAssetId(assetOutId)
    const reserveThird = this.getThirdReserveByAssetIds(assetInId, assetOutId)
    const thirdAssetId = this.getThirdAssetIdByPair(assetInId, assetOutId)

    const [amountOut, newReserveIn, newReserveOut, newReserveThird] = this.quoteOutput(
      reserveIn,
      reserveOut,
      reserveThird,
      amountIn,
    )

    assert(amountOut >= minAmountOut, 'slippage exceeded')
    assert(amountOut > 0, 'amountOut zero')
    assert(amountOut < reserveOut, 'output would drain reserve')
    assert(reserveOut >= amountOut, 'reserve underflow')

    this.setReserveByAssetId(assetInId, newReserveIn)
    this.setReserveByAssetId(assetOutId, newReserveOut)
    this.setReserveByAssetId(thirdAssetId, newReserveThird)

    itxn
      .assetTransfer({
        xferAsset: assetOutId,
        assetReceiver: Txn.sender,
        assetAmount: amountOut,
        fee: 0,
      })
      .submit()

    return amountOut
  }

  public get_pool_state(): [uint64, uint64, uint64, uint64, uint64, uint64, uint64] {
    return [
      this.assetAId.value,
      this.assetBId.value,
      this.assetCId.value,
      this.reserveA.value,
      this.reserveB.value,
      this.reserveC.value,
      this.feeBps.value,
    ]
  }

  public opt_in_asset(assetId: uint64): void {
    assert(Txn.sender === this.admin.value, 'admin only')
    assert(assetId > 0, 'invalid asset id')

    itxn
      .assetTransfer({
        xferAsset: assetId,
        assetReceiver: Global.currentApplicationAddress,
        assetAmount: 0,
        fee: 0,
      })
      .submit()
  }

  public pause(): void {
    assert(Txn.sender === this.admin.value, 'admin only')
    this.paused.value = true
  }

  public unpause(): void {
    assert(Txn.sender === this.admin.value, 'admin only')
    this.paused.value = false
  }

  private applyFee(amountIn: uint64, feeBps: uint64): uint64 {
    const feeFactor: uint64 = 10_000 - feeBps
    return (amountIn * feeFactor) / 10_000
  }

  private quoteOutput(
    reserveIn: uint64,
    reserveOut: uint64,
    reserveThird: uint64,
    amountIn: uint64,
  ): [uint64, uint64, uint64, uint64] {
    assert(reserveIn > 0 && reserveOut > 0 && reserveThird > 0, 'empty reserves')
    assert(amountIn > 0, 'amountIn must be positive')
    assert(reserveIn <= 100_000_000 && reserveOut <= 100_000_000 && reserveThird <= 100_000_000, 'reserve cap exceeded')
    assert(reserveIn >= 20, 'reserve too small for max swap')
    assert(amountIn <= reserveIn / 20, 'swap exceeds max trade size')

    const rawKBefore = this.rawInvariant(reserveIn, reserveOut, reserveThird)
    this.validatePoolHealth(reserveIn, reserveOut, reserveThird, rawKBefore)
    const dominanceBps = this.computeDominanceBps(reserveIn, reserveOut, reserveThird, rawKBefore)
    const curvatureBps = this.computeCurvatureBps(dominanceBps)
    const kBefore = this.invariant(reserveIn, reserveOut, reserveThird, curvatureBps)
    const feeBps = this.computeDynamicFee(dominanceBps)
    const amountInAfterFee = this.applyFee(amountIn, feeBps)
    assert(amountInAfterFee > 0, 'amountIn too small after fee')
    const newReserveIn: uint64 = reserveIn + amountInAfterFee
    assert(newReserveIn >= reserveIn, 'reserve overflow')
    assert(newReserveIn <= 100_000_000, 'reserve cap exceeded')

    const couplingAdjustment = this.computeCouplingAdjustment(reserveIn, reserveThird, amountInAfterFee, dominanceBps)
    const newReserveThird = this.safeSub(reserveThird, couplingAdjustment)
    assert(newReserveThird > 0, 'third reserve depleted')
    assert(newReserveThird <= 100_000_000, 'reserve cap exceeded')

    const newEffIn = this.effectiveReserve(newReserveIn, curvatureBps)
    const newEffThird = this.effectiveReserve(newReserveThird, curvatureBps)
    const newEffInSq = this.safeSquare(newEffIn)
    const newEffThirdSq = this.safeSquare(newEffThird)

    assert(kBefore >= newEffInSq, 'invariant exhausted by input')
    const remainingAfterInput: uint64 = this.safeSub(kBefore, newEffInSq)
    assert(remainingAfterInput >= newEffThirdSq, 'invariant exhausted by third reserve')

    const targetOutSq: uint64 = this.safeSub(remainingAfterInput, newEffThirdSq)
    const targetOutEff: uint64 = this.safeSqrt(targetOutSq)
    const newReserveOut: uint64 = this.inverseEffectiveReserve(targetOutEff, curvatureBps)

    assert(reserveOut >= newReserveOut, 'invalid output reserve')
    const amountOut: uint64 = this.safeSub(reserveOut, newReserveOut)
    assert(amountOut > 0, 'amountOut zero')
    assert(amountOut < reserveOut, 'output would drain reserve')
    assert(newReserveOut <= 100_000_000, 'reserve cap exceeded')

    const rawKAfter = this.rawInvariant(newReserveIn, newReserveOut, newReserveThird)
    this.validatePoolHealth(newReserveIn, newReserveOut, newReserveThird, rawKAfter)
    return [amountOut, newReserveIn, newReserveOut, newReserveThird]
  }

  private rawInvariant(reserveA: uint64, reserveB: uint64, reserveC: uint64): uint64 {
    const reserveASq = this.safeSquare(reserveA)
    const reserveBSq = this.safeSquare(reserveB)
    const reserveCSq = this.safeSquare(reserveC)

    const sumAB: uint64 = reserveASq + reserveBSq
    assert(sumAB >= reserveASq, 'raw invariant overflow')
    const sumABC: uint64 = sumAB + reserveCSq
    assert(sumABC >= sumAB, 'raw invariant overflow')
    return sumABC
  }

  private invariant(reserveA: uint64, reserveB: uint64, reserveC: uint64, curvatureBps: uint64): uint64 {
    const effA = this.effectiveReserve(reserveA, curvatureBps)
    const effB = this.effectiveReserve(reserveB, curvatureBps)
    const effC = this.effectiveReserve(reserveC, curvatureBps)

    const effASq = this.safeSquare(effA)
    const effBSq = this.safeSquare(effB)
    const effCSq = this.safeSquare(effC)

    const sumAB: uint64 = effASq + effBSq
    assert(sumAB >= effASq, 'invariant overflow')
    const sumABC: uint64 = sumAB + effCSq
    assert(sumABC >= sumAB, 'invariant overflow')

    return sumABC
  }

  private geometricLiquidity(reserveA: uint64, reserveB: uint64, reserveC: uint64): uint64 {
    const rawK = this.rawInvariant(reserveA, reserveB, reserveC)
    const dom = this.computeDominanceBps(reserveA, reserveB, reserveC, rawK)
    const curv = this.computeCurvatureBps(dom)
    const k = this.invariant(reserveA, reserveB, reserveC, curv)
    return this.safeSqrt(k)
  }

  private safeSquare(value: uint64): uint64 {
    assert(value <= 4_000_000_000, 'square bound exceeded')
    const squared: uint64 = value * value
    assert(value === 0 || squared / value === value, 'square overflow')
    return squared
  }

  private safeSub(a: uint64, b: uint64): uint64 {
    assert(a >= b, 'underflow')
    return a - b
  }

  private safeSqrt(value: uint64): uint64 {
    return op.sqrt(value)
  }

  private computeDominanceBps(reserveA: uint64, reserveB: uint64, reserveC: uint64, kValue: uint64): uint64 {
    assert(kValue > 0, 'invalid invariant')
    const aSq = this.safeSquare(reserveA)
    const bSq = this.safeSquare(reserveB)
    const cSq = this.safeSquare(reserveC)
    let maxSq = aSq
    if (bSq > maxSq) maxSq = bSq
    if (cSq > maxSq) maxSq = cSq
    return (maxSq * 10_000) / kValue
  }

  private validatePoolHealth(reserveA: uint64, reserveB: uint64, reserveC: uint64, kValue: uint64): void {
    const dominanceBps = this.computeDominanceBps(reserveA, reserveB, reserveC, kValue)
    assert(dominanceBps <= 6_400, 'dominance threshold exceeded')
  }

  private imbalanceBps(reserveA: uint64, reserveB: uint64, reserveC: uint64): uint64 {
    const sum: uint64 = reserveA + reserveB + reserveC
    assert(sum > 0, 'sum zero')
    let maxReserve = reserveA
    if (reserveB > maxReserve) maxReserve = reserveB
    if (reserveC > maxReserve) maxReserve = reserveC
    return (maxReserve * 10_000) / sum
  }

  private computeDepositPenaltyBps(depositImbalanceBps: uint64): uint64 {
    if (depositImbalanceBps <= 3_600) return 0
    if (depositImbalanceBps <= 4_800) return (depositImbalanceBps - 3_600) / 12
    if (depositImbalanceBps >= 7_500) return 650
    return 100 + ((depositImbalanceBps - 4_800) * 550) / 2_700
  }

  private computeDynamicFee(dominanceBps: uint64): uint64 {
    // Equilibrium attraction: lower fees near balance, higher fees only under stress.
    if (dominanceBps <= 3_300) return 18
    if (dominanceBps <= 4_900) return 18 + ((dominanceBps - 3_300) * 32) / 1_600
    if (dominanceBps <= 6_200) return 50 + ((dominanceBps - 4_900) * 40) / 1_300
    return 90
  }

  private computeCurvatureBps(dominanceBps: uint64): uint64 {
    // Region-aware softened geometry proxy:
    // high bps => softer center behavior, low bps => stronger edge protection.
    if (dominanceBps <= 3_400) return 4_200
    if (dominanceBps >= 6_200) return 1_400
    return 4_200 - ((dominanceBps - 3_400) * 2_800) / 2_800
  }

  private effectiveReserve(reserve: uint64, curvatureBps: uint64): uint64 {
    const sqrtR = this.safeSqrt(reserve)
    const boost: uint64 = (sqrtR * curvatureBps) / 10_000
    const eff: uint64 = reserve + boost
    assert(eff >= reserve, 'effective reserve overflow')
    return eff
  }

  private inverseEffectiveReserve(effective: uint64, curvatureBps: uint64): uint64 {
    const sqrtEff = this.safeSqrt(effective)
    const reduction: uint64 = (sqrtEff * curvatureBps) / 10_000
    if (reduction >= effective) return 1
    const raw: uint64 = effective - reduction
    if (raw === 0) return 1
    return raw
  }

  private computeCouplingAdjustment(
    reserveIn: uint64,
    reserveThird: uint64,
    amountInAfterFee: uint64,
    dominanceBps: uint64,
  ): uint64 {
    assert(reserveIn > 0, 'reserveIn zero')
    assert(reserveThird > 1, 'third reserve too small')
    const denom: uint64 = reserveIn * 40
    assert(denom > reserveIn, 'denominator overflow')
    let base: uint64 = (reserveThird * amountInAfterFee) / denom
    if (base === 0) base = 1

    const tradeSizeBps: uint64 = (amountInAfterFee * 10_000) / reserveIn
    const sizePressure: uint64 = this.safeSqrt(tradeSizeBps * 10_000)
    let imbalancePressure: uint64 = 0
    if (dominanceBps > 3_600) imbalancePressure = dominanceBps - 3_600

    let weighted: uint64 = (base * (2_500 + sizePressure + imbalancePressure)) / 10_000
    if (weighted === 0) weighted = 1

    const maxAdjust: uint64 = reserveThird - 1
    if (weighted > maxAdjust) return maxAdjust
    return weighted
  }

  private getThirdReserveByAssetIds(assetInId: uint64, assetOutId: uint64): uint64 {
    assert(this.isPoolAsset(assetInId), 'assetIn unsupported')
    assert(this.isPoolAsset(assetOutId), 'assetOut unsupported')
    assert(assetInId !== assetOutId, 'asset ids must differ')

    if (assetInId !== this.assetAId.value && assetOutId !== this.assetAId.value) return this.reserveA.value
    if (assetInId !== this.assetBId.value && assetOutId !== this.assetBId.value) return this.reserveB.value
    return this.reserveC.value
  }

  private getThirdAssetIdByPair(assetInId: uint64, assetOutId: uint64): uint64 {
    assert(this.isPoolAsset(assetInId), 'assetIn unsupported')
    assert(this.isPoolAsset(assetOutId), 'assetOut unsupported')
    assert(assetInId !== assetOutId, 'asset ids must differ')

    if (assetInId !== this.assetAId.value && assetOutId !== this.assetAId.value) return this.assetAId.value
    if (assetInId !== this.assetBId.value && assetOutId !== this.assetBId.value) return this.assetBId.value
    return this.assetCId.value
  }

  private getReserveByAssetId(assetId: uint64): uint64 {
    assert(this.isPoolAsset(assetId), 'unsupported asset')
    if (assetId === this.assetAId.value) return this.reserveA.value
    if (assetId === this.assetBId.value) return this.reserveB.value
    return this.reserveC.value
  }

  private setReserveByAssetId(assetId: uint64, value: uint64): void {
    assert(this.isPoolAsset(assetId), 'unsupported asset')
    assert(value <= 100_000_000, 'reserve cap exceeded')
    if (assetId === this.assetAId.value) {
      this.reserveA.value = value
      return
    }
    if (assetId === this.assetBId.value) {
      this.reserveB.value = value
      return
    }
    this.reserveC.value = value
  }

  private isPoolAsset(assetId: uint64): boolean {
    return assetId === this.assetAId.value || assetId === this.assetBId.value || assetId === this.assetCId.value
  }
}
