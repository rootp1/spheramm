import algosdk from 'algosdk'
import { getAccountFromMnemonic, getAlgodClient, getRequiredEnv, getSuggestedParams, waitFor } from './common.ts'

function encU64(v: number | bigint) {
  return algosdk.encodeUint64(BigInt(v))
}

function readUintState(globalState: any[], key: string): number {
  return Number(globalState.find((x: any) => Buffer.from(x.key, 'base64').toString('utf8') === key)?.value?.uint ?? 0)
}

function geometricL(a: number, b: number, c: number) {
  return Math.floor(Math.sqrt(a * a + b * b + c * c))
}

async function main() {
  const algod = getAlgodClient()
  const user = getAccountFromMnemonic('USER_MNEMONIC')
  const appId = Number(getRequiredEnv('AMM_APP_ID'))
  const [assetAId, assetBId, assetCId] = ['ASSET_A_ID', 'ASSET_B_ID', 'ASSET_C_ID'].map((k) => Number(getRequiredEnv(k)))
  const appAddress = algosdk.getApplicationAddress(appId)
  const sp = await getSuggestedParams(algod)

  const appBefore = await algod.getApplicationByID(appId).do()
  const gsBefore = appBefore.params.globalState ?? []
  const reserveABefore = readUintState(gsBefore, 'reserveA')
  const reserveBBefore = readUintState(gsBefore, 'reserveB')
  const reserveCBefore = readUintState(gsBefore, 'reserveC')
  const totalLpBefore = readUintState(gsBefore, 'totalLpSupply')

  console.log('Before LP add', { reserveABefore, reserveBBefore, reserveCBefore, totalLpBefore, geometricL: geometricL(reserveABefore, reserveBBefore, reserveCBefore) })

  const addA = 20
  const addB = 20
  const addC = 20
  const addMethod = new algosdk.ABIMethod({ name: 'add_liquidity', args: [{ type: 'uint64', name: 'amountA' }, { type: 'uint64', name: 'amountB' }, { type: 'uint64', name: 'amountC' }, { type: 'uint64', name: 'minLpOut' }], returns: { type: 'uint64' } })
  const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: user.addr, receiver: appAddress, amount: addA, assetIndex: assetAId, suggestedParams: sp })
  const tx1 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: user.addr, receiver: appAddress, amount: addB, assetIndex: assetBId, suggestedParams: sp })
  const tx2 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: user.addr, receiver: appAddress, amount: addC, assetIndex: assetCId, suggestedParams: sp })
  const tx3 = algosdk.makeApplicationNoOpTxnFromObject({ sender: user.addr, appIndex: BigInt(appId), appArgs: [addMethod.getSelector(), encU64(addA), encU64(addB), encU64(addC), encU64(1)], suggestedParams: sp })
  algosdk.assignGroupID([tx0, tx1, tx2, tx3])
  const addSigned = [tx0, tx1, tx2, tx3].map((t) => t.signTxn(user.sk))
  const { txid: addTxid } = await algod.sendRawTransaction(addSigned).do()
  await waitFor(algod, addTxid)

  const appMid = await algod.getApplicationByID(appId).do()
  const gsMid = appMid.params.globalState ?? []
  const reserveAMid = readUintState(gsMid, 'reserveA')
  const reserveBMid = readUintState(gsMid, 'reserveB')
  const reserveCMid = readUintState(gsMid, 'reserveC')
  const totalLpMid = readUintState(gsMid, 'totalLpSupply')
  console.log('After LP add', { reserveAMid, reserveBMid, reserveCMid, totalLpMid, geometricL: geometricL(reserveAMid, reserveBMid, reserveCMid) })

  const burnLp = Math.max(1, Math.floor((totalLpMid - totalLpBefore) / 2))
  const removeMethod = new algosdk.ABIMethod({ name: 'remove_liquidity', args: [{ type: 'uint64', name: 'lpAmount' }, { type: 'uint64', name: 'minAOut' }, { type: 'uint64', name: 'minBOut' }, { type: 'uint64', name: 'minCOut' }], returns: { type: '(uint64,uint64,uint64)' } })
  const removeTx = algosdk.makeApplicationNoOpTxnFromObject({
    sender: user.addr,
    appIndex: BigInt(appId),
    appArgs: [removeMethod.getSelector(), encU64(burnLp), encU64(1), encU64(1), encU64(1)],
    foreignAssets: [assetAId, assetBId, assetCId],
    suggestedParams: { ...sp, fee: 4_000n, flatFee: true },
  })
  const { txid: removeTxid } = await algod.sendRawTransaction(removeTx.signTxn(user.sk)).do()
  await waitFor(algod, removeTxid)

  const appAfter = await algod.getApplicationByID(appId).do()
  const gsAfter = appAfter.params.globalState ?? []
  const reserveAAfter = readUintState(gsAfter, 'reserveA')
  const reserveBAfter = readUintState(gsAfter, 'reserveB')
  const reserveCAfter = readUintState(gsAfter, 'reserveC')
  const totalLpAfter = readUintState(gsAfter, 'totalLpSupply')
  console.log('After LP remove', { reserveAAfter, reserveBAfter, reserveCAfter, totalLpAfter, geometricL: geometricL(reserveAAfter, reserveBAfter, reserveCAfter) })
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
