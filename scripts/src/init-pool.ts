import algosdk from 'algosdk'
import { getAccountFromMnemonic, getAlgodClient, getRequiredEnv, getSuggestedParams, waitFor } from './common.ts'

function encU64(v: number | bigint) {
  return algosdk.encodeUint64(BigInt(v))
}

async function main() {
  const algod = getAlgodClient()
  const deployer = getAccountFromMnemonic('DEPLOYER_MNEMONIC')

  const appId = Number(getRequiredEnv('AMM_APP_ID'))
  const assetAId = Number(getRequiredEnv('ASSET_A_ID'))
  const assetBId = Number(getRequiredEnv('ASSET_B_ID'))
  const assetCId = Number(getRequiredEnv('ASSET_C_ID'))
  const feeBps = Number(process.env.FEE_BPS ?? '30')

  const amountA = 1_000
  const amountB = 1_000
  const amountC = 1_000

  const appAddress = algosdk.getApplicationAddress(appId)
  const sp = await getSuggestedParams(algod)

  const optInMethod = new algosdk.ABIMethod({
    name: 'opt_in_asset',
    args: [{ type: 'uint64', name: 'assetId' }],
    returns: { type: 'void' },
  })
  const createPoolMethod = new algosdk.ABIMethod({
    name: 'create_pool',
    args: [
      { type: 'uint64', name: 'assetA' },
      { type: 'uint64', name: 'assetB' },
      { type: 'uint64', name: 'assetC' },
      { type: 'uint64', name: 'amountA' },
      { type: 'uint64', name: 'amountB' },
      { type: 'uint64', name: 'amountC' },
      { type: 'uint64', name: 'feeBps' },
    ],
    returns: { type: 'void' },
  })

  for (const assetId of [assetAId, assetBId, assetCId]) {
    const optInAppCall = algosdk.makeApplicationNoOpTxnFromObject({
      sender: deployer.addr,
      appIndex: BigInt(appId),
      appArgs: [optInMethod.getSelector(), encU64(assetId)],
      foreignAssets: [assetId],
      suggestedParams: { ...sp, fee: 2_000n },
    })

    const signedOptIn = optInAppCall.signTxn(deployer.sk)
    const { txid: optInTxId } = await algod.sendRawTransaction(signedOptIn).do()
    await waitFor(algod, optInTxId)
  }

  const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender: deployer.addr,
    receiver: appAddress,
    amount: amountA,
    assetIndex: assetAId,
    suggestedParams: sp,
  })
  const tx1 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender: deployer.addr,
    receiver: appAddress,
    amount: amountB,
    assetIndex: assetBId,
    suggestedParams: sp,
  })
  const tx2 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender: deployer.addr,
    receiver: appAddress,
    amount: amountC,
    assetIndex: assetCId,
    suggestedParams: sp,
  })

  const appArgs = [
    createPoolMethod.getSelector(),
    encU64(assetAId),
    encU64(assetBId),
    encU64(assetCId),
    encU64(amountA),
    encU64(amountB),
    encU64(amountC),
    encU64(feeBps),
  ]

  const tx3 = algosdk.makeApplicationNoOpTxnFromObject({
    sender: deployer.addr,
    appIndex: BigInt(appId),
    appArgs,
    foreignAssets: [assetAId, assetBId, assetCId],
    suggestedParams: sp,
  })

  algosdk.assignGroupID([tx0, tx1, tx2, tx3])

  const signed = [tx0, tx1, tx2, tx3].map((txn) => txn.signTxn(deployer.sk))
  const { txid } = await algod.sendRawTransaction(signed).do()

  await waitFor(algod, txid)
  console.log('Pool initialized with 1000 / 1000 / 1000')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
