'use client'

import { useWallet, Wallet, WalletId } from '@txnlab/use-wallet-react'
import algosdk from 'algosdk'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { algod, appId, assets, encodeU64, getAppAddress } from '../lib/algorand'

type PoolState = {
  reserveA: number
  reserveB: number
  reserveC: number
  feeBps: number
  totalLpSupply: number
}

function readAssetId(asset: any): number {
  return Number(asset?.assetId ?? asset?.['asset-id'] ?? 0)
}

function readAssetAmount(asset: any): number {
  return Number(asset?.amount ?? 0)
}

export default function LpPage() {
  const { wallets, activeWallet, activeAddress, isReady, signTransactions } = useWallet()
  const [pool, setPool] = useState<PoolState>({ reserveA: 0, reserveB: 0, reserveC: 0, feeBps: 30, totalLpSupply: 0 })
  const [selectedWalletId, setSelectedWalletId] = useState<string>('')
  const [mounted, setMounted] = useState(false)
  const [status, setStatus] = useState('')
  const [optedAssetIds, setOptedAssetIds] = useState<number[]>([])
  const [lpBalance, setLpBalance] = useState<number>(0)
  const [addA, setAddA] = useState<number>(10)
  const [addB, setAddB] = useState<number>(10)
  const [addC, setAddC] = useState<number>(10)
  const [removeLp, setRemoveLp] = useState<number>(10)

  const preferredWalletOrder = [WalletId.LUTE, WalletId.PERA, WalletId.DEFLY, WalletId.EXODUS]
  const sortedWallets = useMemo(
    () =>
      [...wallets].sort((left, right) => {
        const li = preferredWalletOrder.indexOf(left.id)
        const ri = preferredWalletOrder.indexOf(right.id)
        return (li === -1 ? 99 : li) - (ri === -1 ? 99 : ri)
      }),
    [wallets],
  )
  const configuredAssets = useMemo(() => assets.filter((asset) => asset.id > 0), [])
  const hasConfigError = !appId || configuredAssets.length !== 3
  const hydratedAddress = mounted ? activeAddress : null
  const hydratedWallets = mounted ? sortedWallets : []
  const invariantNow = pool.reserveA * pool.reserveA + pool.reserveB * pool.reserveB + pool.reserveC * pool.reserveC
  const geometricL = Math.floor(Math.sqrt(invariantNow))
  const addImbalanceBps = useMemo(() => {
    const total = addA + addB + addC
    if (total <= 0) return 0
    return Math.floor((Math.max(addA, addB, addC) * 10000) / total)
  }, [addA, addB, addC])
  const addPenaltyBps = useMemo(() => {
    if (addImbalanceBps <= 3600) return 0
    if (addImbalanceBps <= 4800) return Math.floor((addImbalanceBps - 3600) / 12)
    if (addImbalanceBps >= 7500) return 650
    return 100 + Math.floor(((addImbalanceBps - 4800) * 550) / 2700)
  }, [addImbalanceBps])
  const addLpEstimate = useMemo(() => {
    const depositL = Math.floor(Math.sqrt(addA * addA + addB * addB + addC * addC))
    if (depositL <= 0 || geometricL <= 0) return 0
    const lpRaw = pool.totalLpSupply <= 0 ? depositL : Math.floor((depositL * pool.totalLpSupply) / geometricL)
    return Math.floor((lpRaw * (10000 - addPenaltyBps)) / 10000)
  }, [addA, addB, addC, geometricL, pool.totalLpSupply, addPenaltyBps])
  const removeQuote = useMemo(() => {
    if (pool.totalLpSupply <= 0 || removeLp <= 0) return { a: 0, b: 0, c: 0 }
    return {
      a: Math.floor((pool.reserveA * removeLp) / pool.totalLpSupply),
      b: Math.floor((pool.reserveB * removeLp) / pool.totalLpSupply),
      c: Math.floor((pool.reserveC * removeLp) / pool.totalLpSupply),
    }
  }, [pool, removeLp])

  async function loadPool() {
    if (!appId) return
    const app = await algod.getApplicationByID(appId).do()
    const gs = app.params.globalState ?? []
    const byKey = (key: string) => Number(gs.find((x: any) => Buffer.from(x.key, 'base64').toString('utf8') === key)?.value?.uint ?? 0)
    setPool({
      reserveA: byKey('reserveA'),
      reserveB: byKey('reserveB'),
      reserveC: byKey('reserveC'),
      feeBps: byKey('feeBps') || 30,
      totalLpSupply: byKey('totalLpSupply'),
    })
  }

  async function loadWalletAssetOptIns() {
    if (!activeAddress) return setOptedAssetIds([])
    const accountInfo = await algod.accountInformation(activeAddress).do()
    const accountAssets = accountInfo.assets ?? []
    setOptedAssetIds(accountAssets.map((asset: any) => readAssetId(asset)).filter((id: number) => id > 0))
  }

  async function loadLpBalance() {
    if (!activeAddress || !appId) return setLpBalance(0)
    const accountInfo = await algod.accountApplicationInformation(activeAddress, appId).do().catch(() => null)
    const kv = accountInfo?.appLocalState?.keyValue ?? []
    const byKey = (key: string) => Number(kv.find((x: any) => Buffer.from(x.key, 'base64').toString('utf8') === key)?.value?.uint ?? 0)
    setLpBalance(byKey('lpBalance'))
  }

  async function connect() {
    if (!isReady) throw new Error('Wallet providers are still loading')
    const chosenWallet =
      sortedWallets.find((wallet) => wallet.id === selectedWalletId) ??
      sortedWallets.find((wallet) => wallet.id === WalletId.LUTE) ??
      sortedWallets.find((wallet) => wallet.id === WalletId.PERA) ??
      sortedWallets[0]
    if (!chosenWallet) throw new Error('No compatible wallet providers found')
    await chosenWallet.connect()
    setStatus(`Connected via ${chosenWallet.metadata.name}`)
  }

  async function disconnect() {
    if (!activeWallet) return
    await activeWallet.disconnect()
    setStatus('Disconnected wallet')
  }

  async function optInMissingAssets() {
    if (!activeAddress) throw new Error('Connect wallet first')
    const missing = configuredAssets.filter((asset) => !optedAssetIds.includes(asset.id))
    if (missing.length === 0) return setStatus('All pool assets already opted in')
    const sp = await algod.getTransactionParams().do()
    const txns = missing.map((asset) =>
      algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: activeAddress, receiver: activeAddress, amount: 0, assetIndex: asset.id, suggestedParams: sp }),
    )
    algosdk.assignGroupID(txns)
    const signed = await signTransactions(txns.map((txn) => algosdk.encodeUnsignedTransaction(txn)))
    const signedGroup = signed.filter((stxn): stxn is Uint8Array => stxn !== null)
    const { txid } = await algod.sendRawTransaction(signedGroup).do()
    await algosdk.waitForConfirmation(algod, txid, 4)
    setStatus(`Asset opt-ins confirmed: ${txid}`)
    await loadWalletAssetOptIns()
  }

  async function addLiquidity() {
    if (!activeAddress) throw new Error('Connect wallet first')
    if (addA <= 0 || addB <= 0 || addC <= 0) throw new Error('Enter valid liquidity amounts')
    const appAddress = getAppAddress()
    const sp = await algod.getTransactionParams().do()
    const method = new algosdk.ABIMethod({
      name: 'add_liquidity',
      args: [{ type: 'uint64', name: 'amountA' }, { type: 'uint64', name: 'amountB' }, { type: 'uint64', name: 'amountC' }, { type: 'uint64', name: 'minLpOut' }],
      returns: { type: 'uint64' },
    })
    const txA = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: activeAddress, receiver: appAddress, amount: addA, assetIndex: assets[0].id, suggestedParams: sp })
    const txB = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: activeAddress, receiver: appAddress, amount: addB, assetIndex: assets[1].id, suggestedParams: sp })
    const txC = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: activeAddress, receiver: appAddress, amount: addC, assetIndex: assets[2].id, suggestedParams: sp })
    const appCall = algosdk.makeApplicationNoOpTxnFromObject({
      sender: activeAddress,
      appIndex: BigInt(appId),
      appArgs: [method.getSelector(), encodeU64(addA), encodeU64(addB), encodeU64(addC), encodeU64(Math.max(1, Math.floor(addLpEstimate * 0.98)))],
      suggestedParams: sp,
    })
    algosdk.assignGroupID([txA, txB, txC, appCall])
    const signed = await signTransactions([txA, txB, txC, appCall].map((txn) => algosdk.encodeUnsignedTransaction(txn)))
    const signedGroup = signed.filter((stxn): stxn is Uint8Array => stxn !== null)
    const { txid } = await algod.sendRawTransaction(signedGroup).do()
    await algosdk.waitForConfirmation(algod, txid, 4)
    setStatus(`Add liquidity confirmed: ${txid}`)
    await loadPool()
    await loadLpBalance()
  }

  async function removeLiquidity() {
    if (!activeAddress) throw new Error('Connect wallet first')
    if (removeLp <= 0) throw new Error('Enter LP to burn')
    if (removeLp > lpBalance) throw new Error('LP burn exceeds your balance')
    const sp = await algod.getTransactionParams().do()
    const method = new algosdk.ABIMethod({
      name: 'remove_liquidity',
      args: [{ type: 'uint64', name: 'lpAmount' }, { type: 'uint64', name: 'minAOut' }, { type: 'uint64', name: 'minBOut' }, { type: 'uint64', name: 'minCOut' }],
      returns: { type: '(uint64,uint64,uint64)' },
    })
    const appCall = algosdk.makeApplicationNoOpTxnFromObject({
      sender: activeAddress,
      appIndex: BigInt(appId),
      appArgs: [method.getSelector(), encodeU64(removeLp), encodeU64(Math.max(1, Math.floor(removeQuote.a * 0.98))), encodeU64(Math.max(1, Math.floor(removeQuote.b * 0.98))), encodeU64(Math.max(1, Math.floor(removeQuote.c * 0.98)))],
      foreignAssets: [assets[0].id, assets[1].id, assets[2].id],
      suggestedParams: { ...sp, fee: 4_000n, flatFee: true },
    })
    const signed = await signTransactions([algosdk.encodeUnsignedTransaction(appCall)])
    const signedGroup = signed.filter((stxn): stxn is Uint8Array => stxn !== null)
    const { txid } = await algod.sendRawTransaction(signedGroup).do()
    await algosdk.waitForConfirmation(algod, txid, 4)
    setStatus(`Remove liquidity confirmed: ${txid}`)
    await loadPool()
    await loadLpBalance()
  }

  useEffect(() => {
    setMounted(true)
    loadPool().catch((e) => setStatus(e.message))
  }, [])
  useEffect(() => {
    loadWalletAssetOptIns().catch((e) => setStatus(e.message))
    loadLpBalance().catch((e) => setStatus(e.message))
  }, [activeAddress])

  return (
    <main>
      <h1>LP Management</h1>
      <p>Tri-Asset AMM (TestNet)</p>
      <p><Link href="/">Go to Swap</Link></p>
      {hasConfigError && <div className="warning">Missing frontend env config for app/assets.</div>}

      <div className="card">
        <div className="grid">
          <select value={selectedWalletId} onChange={(e) => setSelectedWalletId(e.target.value)}>
            <option value="">Auto (Lute → Pera → others)</option>
            {hydratedWallets.map((wallet: Wallet) => (
              <option key={wallet.id} value={wallet.id}>{wallet.metadata.name}</option>
            ))}
          </select>
          <button onClick={() => connect().catch((e) => setStatus(e.message))}>
            {hydratedAddress ? `Connected: ${hydratedAddress.slice(0, 8)}...` : 'Connect Wallet'}
          </button>
          <button className="secondary" onClick={() => disconnect().catch((e) => setStatus(e.message))}>Disconnect</button>
          <button className="secondary" onClick={() => optInMissingAssets().catch((e) => setStatus(e.message))}>Opt-in Missing Assets</button>
        </div>
      </div>

      <div className="card">
        <h3>LP State</h3>
        <p>Total LP Supply: {pool.totalLpSupply}</p>
        <p>Your LP Shares: {lpBalance}</p>
        <p>Geometric Liquidity L = sqrt(A²+B²+C²): {geometricL}</p>
        <p>Pool Reserves: A {pool.reserveA} / B {pool.reserveB} / C {pool.reserveC}</p>
      </div>

      <div className="card">
        <h3>Add Liquidity</h3>
        <div className="grid">
          <input type="number" min={1} value={addA} onChange={(e) => setAddA(readAssetAmount({ amount: e.target.value }))} />
          <input type="number" min={1} value={addB} onChange={(e) => setAddB(readAssetAmount({ amount: e.target.value }))} />
          <input type="number" min={1} value={addC} onChange={(e) => setAddC(readAssetAmount({ amount: e.target.value }))} />
          <button onClick={() => addLiquidity().catch((e) => setStatus(e.message))}>Add Liquidity</button>
        </div>
        <p>LP Mint Estimate: <b>{addLpEstimate}</b></p>
        <p>Deposit imbalance: {(addImbalanceBps / 100).toFixed(2)}%, penalty: {addPenaltyBps} bps</p>
      </div>

      <div className="card">
        <h3>Remove Liquidity</h3>
        <div className="grid">
          <input type="number" min={1} value={removeLp} onChange={(e) => setRemoveLp(readAssetAmount({ amount: e.target.value }))} />
          <button className="secondary" onClick={() => removeLiquidity().catch((e) => setStatus(e.message))}>Remove Liquidity</button>
        </div>
        <p>Withdraw estimate: A {removeQuote.a} / B {removeQuote.b} / C {removeQuote.c}</p>
      </div>

      {status && <div className="card"><b>Status:</b> {status}</div>}
    </main>
  )
}

