import type { uint64 } from '@algorandfoundation/algorand-typescript'
import { Account, Contract, Global, GlobalState, LocalState, Txn, assert, gtxn, itxn, op } from '@algorandfoundation/algorand-typescript'

// Research-stage architecture for localized geometric liquidity regions ("orbital ticks").
// This contract is intended for simulation-aligned validation, not production launch.
export class TriAssetAmmOrbitalTicks extends Contract {
  assetAId = GlobalState<uint64>()
  assetBId = GlobalState<uint64>()
  assetCId = GlobalState<uint64>()

  reserveA = GlobalState<uint64>()
  reserveB = GlobalState<uint64>()
  reserveC = GlobalState<uint64>()

  admin = GlobalState<Account>()
  paused = GlobalState<boolean>()

  // LP accounting
  totalLpSupply = GlobalState<uint64>()
  lpCoreSupply = GlobalState<uint64>()
  lpMidSupply = GlobalState<uint64>()
  lpEdgeSupply = GlobalState<uint64>()
  lpCore = LocalState<uint64>()
  lpMid = LocalState<uint64>()
  lpEdge = LocalState<uint64>()

  // Region-local parameters
  coreCurvBps = GlobalState<uint64>()
  midCurvBps = GlobalState<uint64>()
  edgeCurvBps = GlobalState<uint64>()
  coreFeeBps = GlobalState<uint64>()
  midFeeBps = GlobalState<uint64>()
  edgeFeeBps = GlobalState<uint64>()
  coreCouplingDiv = GlobalState<uint64>()
  midCouplingDiv = GlobalState<uint64>()
  edgeCouplingDiv = GlobalState<uint64>()

  public createApplication(): void {
    this.assetAId.value = 0
    this.assetBId.value = 0
    this.assetCId.value = 0
    this.reserveA.value = 0
    this.reserveB.value = 0
    this.reserveC.value = 0
    this.admin.value = Txn.sender
    this.paused.value = false
    this.totalLpSupply.value = 0
    this.lpCoreSupply.value = 0
    this.lpMidSupply.value = 0
    this.lpEdgeSupply.value = 0
    this.coreCurvBps.value = 5200
    this.midCurvBps.value = 3000
    this.edgeCurvBps.value = 1400
    this.coreFeeBps.value = 10
    this.midFeeBps.value = 30
    this.edgeFeeBps.value = 95
    this.coreCouplingDiv.value = 70
    this.midCouplingDiv.value = 40
    this.edgeCouplingDiv.value = 24
  }

  public create_pool(assetA: uint64, assetB: uint64, assetC: uint64, amountA: uint64, amountB: uint64, amountC: uint64): void {
    assert(this.assetAId.value === 0, 'already initialized')
    assert(Global.groupSize === 4, 'group size')
    const tx0 = gtxn.AssetTransferTxn(0)
    const tx1 = gtxn.AssetTransferTxn(1)
    const tx2 = gtxn.AssetTransferTxn(2)
    assert(tx0.sender === Txn.sender && tx1.sender === Txn.sender && tx2.sender === Txn.sender, 'sender')
    assert(tx0.assetReceiver === Global.currentApplicationAddress && tx1.assetReceiver === Global.currentApplicationAddress && tx2.assetReceiver === Global.currentApplicationAddress, 'receiver')
    assert(tx0.xferAsset.id === assetA && tx0.assetAmount === amountA, 'A mismatch')
    assert(tx1.xferAsset.id === assetB && tx1.assetAmount === amountB, 'B mismatch')
    assert(tx2.xferAsset.id === assetC && tx2.assetAmount === amountC, 'C mismatch')
    this.assetAId.value = assetA
    this.assetBId.value = assetB
    this.assetCId.value = assetC
    this.reserveA.value = amountA
    this.reserveB.value = amountB
    this.reserveC.value = amountC
    const lp = amountA + amountB + amountC
    this.totalLpSupply.value = lp
    this.lpCoreSupply.value = (lp * 60) / 100
    this.lpMidSupply.value = (lp * 30) / 100
    this.lpEdgeSupply.value = lp - this.lpCoreSupply.value - this.lpMidSupply.value
  }

  public add_liquidity_region(region: uint64, amountA: uint64, amountB: uint64, amountC: uint64): uint64 {
    assert(!this.paused.value, 'paused')
    assert(region <= 2, 'bad region')
    assert(Global.groupSize === 4, 'group size')
    const tx0 = gtxn.AssetTransferTxn(0)
    const tx1 = gtxn.AssetTransferTxn(1)
    const tx2 = gtxn.AssetTransferTxn(2)
    assert(tx0.sender === Txn.sender && tx1.sender === Txn.sender && tx2.sender === Txn.sender, 'sender')
    assert(tx0.xferAsset.id === this.assetAId.value && tx1.xferAsset.id === this.assetBId.value && tx2.xferAsset.id === this.assetCId.value, 'asset')
    assert(tx0.assetAmount === amountA && tx1.assetAmount === amountB && tx2.assetAmount === amountC, 'amount')

    const addLp = amountA + amountB + amountC
    this.reserveA.value = this.reserveA.value + amountA
    this.reserveB.value = this.reserveB.value + amountB
    this.reserveC.value = this.reserveC.value + amountC
    this.totalLpSupply.value = this.totalLpSupply.value + addLp
    if (region === 0) {
      this.lpCoreSupply.value = this.lpCoreSupply.value + addLp
      this.lpCore(Txn.sender).value = this.lpCore(Txn.sender).value + addLp
    } else if (region === 1) {
      this.lpMidSupply.value = this.lpMidSupply.value + addLp
      this.lpMid(Txn.sender).value = this.lpMid(Txn.sender).value + addLp
    } else {
      this.lpEdgeSupply.value = this.lpEdgeSupply.value + addLp
      this.lpEdge(Txn.sender).value = this.lpEdge(Txn.sender).value + addLp
    }
    return addLp
  }

  public swap_exact_in_localized(assetInId: uint64, amountIn: uint64, minAmountOut: uint64): uint64 {
    assert(!this.paused.value, 'paused')
    assert(Global.groupSize === 2, 'group size')
    const transfer = gtxn.AssetTransferTxn(0)
    assert(transfer.sender === Txn.sender, 'sender')
    assert(transfer.assetReceiver === Global.currentApplicationAddress, 'receiver')
    assert(transfer.xferAsset.id === assetInId && transfer.assetAmount === amountIn, 'input mismatch')
    const assetOutId = Txn.assets(0).id
    assert(assetInId !== assetOutId, 'same asset')

    const region = this.currentRegion()
    const curv = this.regionCurvature(region)
    const fee = this.regionFee(region)
    const couplingDiv = this.regionCouplingDiv(region)
    const reserveIn = this.getReserve(assetInId)
    const reserveOut = this.getReserve(assetOutId)
    const thirdId = this.getThirdAsset(assetInId, assetOutId)
    const reserveThird = this.getReserve(thirdId)

    const amountInAfterFee = (amountIn * (10_000 - fee)) / 10_000
    const newReserveIn = reserveIn + amountInAfterFee
    let coupling = (reserveThird * amountInAfterFee) / (reserveIn * couplingDiv)
    if (coupling === 0) coupling = 1
    const newReserveThird = reserveThird > coupling ? reserveThird - coupling : 1

    const k = this.softInvariant(this.reserveA.value, this.reserveB.value, this.reserveC.value, curv)
    const effIn = this.effective(newReserveIn, curv)
    const effThird = this.effective(newReserveThird, curv)
    const rem = k - effIn * effIn - effThird * effThird
    const effOut = op.sqrt(rem)
    const newReserveOut = this.inverseEffective(effOut, curv)
    const amountOut = reserveOut - newReserveOut
    assert(amountOut >= minAmountOut, 'slippage')

    this.setReserve(assetInId, newReserveIn)
    this.setReserve(assetOutId, newReserveOut)
    this.setReserve(thirdId, newReserveThird)
    itxn.assetTransfer({ xferAsset: assetOutId, assetReceiver: Txn.sender, assetAmount: amountOut, fee: 0 }).submit()
    return amountOut
  }

  public get_region_state(): [uint64, uint64, uint64, uint64, uint64, uint64, uint64, uint64, uint64] {
    return [
      this.lpCoreSupply.value,
      this.lpMidSupply.value,
      this.lpEdgeSupply.value,
      this.coreCurvBps.value,
      this.midCurvBps.value,
      this.edgeCurvBps.value,
      this.coreFeeBps.value,
      this.midFeeBps.value,
      this.edgeFeeBps.value,
    ]
  }

  private currentRegion(): uint64 {
    const a = this.reserveA.value
    const b = this.reserveB.value
    const c = this.reserveC.value
    const sum = a + b + c
    const imb = (this.max3(a, b, c) * 10_000) / sum
    if (imb < 3_600) return 0
    if (imb < 5_000) return 1
    return 2
  }

  private regionCurvature(region: uint64): uint64 {
    if (region === 0) return this.coreCurvBps.value
    if (region === 1) return this.midCurvBps.value
    return this.edgeCurvBps.value
  }

  private regionFee(region: uint64): uint64 {
    if (region === 0) return this.coreFeeBps.value
    if (region === 1) return this.midFeeBps.value
    return this.edgeFeeBps.value
  }

  private regionCouplingDiv(region: uint64): uint64 {
    if (region === 0) return this.coreCouplingDiv.value
    if (region === 1) return this.midCouplingDiv.value
    return this.edgeCouplingDiv.value
  }

  private effective(x: uint64, curvBps: uint64): uint64 {
    return x + (op.sqrt(x) * curvBps) / 10_000
  }

  private inverseEffective(eff: uint64, curvBps: uint64): uint64 {
    const red = (op.sqrt(eff) * curvBps) / 10_000
    return eff > red ? eff - red : 1
  }

  private softInvariant(a: uint64, b: uint64, c: uint64, curvBps: uint64): uint64 {
    const ea = this.effective(a, curvBps)
    const eb = this.effective(b, curvBps)
    const ec = this.effective(c, curvBps)
    return ea * ea + eb * eb + ec * ec
  }

  private max3(a: uint64, b: uint64, c: uint64): uint64 {
    let m = a
    if (b > m) m = b
    if (c > m) m = c
    return m
  }

  private isPoolAsset(id: uint64): boolean {
    return id === this.assetAId.value || id === this.assetBId.value || id === this.assetCId.value
  }

  private getReserve(id: uint64): uint64 {
    assert(this.isPoolAsset(id), 'asset')
    if (id === this.assetAId.value) return this.reserveA.value
    if (id === this.assetBId.value) return this.reserveB.value
    return this.reserveC.value
  }

  private setReserve(id: uint64, v: uint64): void {
    assert(this.isPoolAsset(id), 'asset')
    if (id === this.assetAId.value) this.reserveA.value = v
    else if (id === this.assetBId.value) this.reserveB.value = v
    else this.reserveC.value = v
  }

  private getThirdAsset(a: uint64, b: uint64): uint64 {
    if (a !== this.assetAId.value && b !== this.assetAId.value) return this.assetAId.value
    if (a !== this.assetBId.value && b !== this.assetBId.value) return this.assetBId.value
    return this.assetCId.value
  }
}
