import { getAccountFromMnemonic, getAlgodClient, getRequiredEnv } from './common.ts'
import algosdk from 'algosdk'

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
  const assetAId = Number(getRequiredEnv('ASSET_A_ID'))
  const assetBId = Number(getRequiredEnv('ASSET_B_ID'))
  const appAddress = algosdk.getApplicationAddress(appId)

  const swapMethod = new algosdk.ABIMethod({ name: 'swap_exact_in', args: [{ type: 'uint64', name: 'assetInId' }, { type: 'uint64', name: 'amountIn' }, { type: 'uint64', name: 'minAmountOut' }], returns: { type: 'uint64' } })
  const sp = await algod.getTransactionParams().do()
  sp.flatFee = true
  sp.fee = 1_000n

  const before = await algod.getApplicationByID(appId).do()
  const gsBefore = before.params.globalState ?? []
  const ra0 = readUintState(gsBefore, 'reserveA')
  const rb0 = readUintState(gsBefore, 'reserveB')
  const rc0 = readUintState(gsBefore, 'reserveC')
  const lp0 = readUintState(gsBefore, 'totalLpSupply')
  const l0 = geometricL(ra0, rb0, rc0)

  for (let i = 0; i < 3; i++) {
    const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: user.addr, receiver: appAddress, amount: 5, assetIndex: assetAId, suggestedParams: sp })
    const tx1 = algosdk.makeApplicationNoOpTxnFromObject({
      sender: user.addr,
      appIndex: BigInt(appId),
      appArgs: [swapMethod.getSelector(), algosdk.encodeUint64(BigInt(assetAId)), algosdk.encodeUint64(5n), algosdk.encodeUint64(1n)],
      foreignAssets: [assetBId],
      suggestedParams: { ...sp, fee: 5_000n, flatFee: true },
    })
    algosdk.assignGroupID([tx0, tx1])
    const { txid } = await algod.sendRawTransaction([tx0.signTxn(user.sk), tx1.signTxn(user.sk)]).do()
    await algosdk.waitForConfirmation(algod, txid, 4)
  }

  const after = await algod.getApplicationByID(appId).do()
  const gsAfter = after.params.globalState ?? []
  const ra1 = readUintState(gsAfter, 'reserveA')
  const rb1 = readUintState(gsAfter, 'reserveB')
  const rc1 = readUintState(gsAfter, 'reserveC')
  const lp1 = readUintState(gsAfter, 'totalLpSupply')
  const l1 = geometricL(ra1, rb1, rc1)

  const perLpBefore = lp0 > 0 ? l0 / lp0 : 0
  const perLpAfter = lp1 > 0 ? l1 / lp1 : 0
  console.log('Fee growth snapshot')
  console.log({ reservesBefore: [ra0, rb0, rc0], reservesAfter: [ra1, rb1, rc1], geometricBefore: l0, geometricAfter: l1, totalLpBefore: lp0, totalLpAfter: lp1, valuePerLpBefore: perLpBefore, valuePerLpAfter: perLpAfter })
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
