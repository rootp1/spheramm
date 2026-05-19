import algosdk from 'algosdk'
import fs from 'node:fs'
import path from 'node:path'
import { getAccountFromMnemonic, getAlgodClient, getRequiredEnv, getSuggestedParams, waitFor } from './common.ts'

function encU64(v: number | bigint) {
  return algosdk.encodeUint64(BigInt(v))
}

type ScenarioResult = {
  name: string
  ok: boolean
  detail: string
}

function readUintState(globalState: any[], key: string): number {
  return Number(globalState.find((x: any) => Buffer.from(x.key, 'base64').toString('utf8') === key)?.value?.uint ?? 0)
}

async function deployFreshApp(algod: algosdk.Algodv2, deployer: algosdk.Account) {
  const approvalTealPath = path.resolve(process.cwd(), '../contracts/src/artifacts/TriAssetAmm.approval.teal')
  const clearTealPath = path.resolve(process.cwd(), '../contracts/src/artifacts/TriAssetAmm.clear.teal')

  if (!fs.existsSync(approvalTealPath) || !fs.existsSync(clearTealPath)) {
    throw new Error('Contract artifacts missing. Run: npm run build:contracts from repository root')
  }

  const approvalTeal = fs.readFileSync(approvalTealPath, 'utf-8')
  const clearTeal = fs.readFileSync(clearTealPath, 'utf-8')
  const approvalCompiled = await algod.compile(approvalTeal).do()
  const clearCompiled = await algod.compile(clearTeal).do()

  const sp = await algod.getTransactionParams().do()
  const createMethod = new algosdk.ABIMethod({ name: 'createApplication', args: [], returns: { type: 'void' } })

  const appCreateTxn = algosdk.makeApplicationCreateTxnFromObject({
    sender: deployer.addr,
    approvalProgram: new Uint8Array(Buffer.from(approvalCompiled.result, 'base64')),
    clearProgram: new Uint8Array(Buffer.from(clearCompiled.result, 'base64')),
    appArgs: [createMethod.getSelector()],
    numGlobalInts: 11,
    numGlobalByteSlices: 1,
    numLocalInts: 1,
    numLocalByteSlices: 0,
    suggestedParams: sp,
    onComplete: algosdk.OnApplicationComplete.NoOpOC,
  })

  const signedCreate = appCreateTxn.signTxn(deployer.sk)
  const { txid } = await algod.sendRawTransaction(signedCreate).do()
  const result = await waitFor(algod, txid)
  if (!result.applicationIndex) throw new Error('Failed to deploy fresh validation app')

  const appId = Number(result.applicationIndex)
  const appAddress = algosdk.getApplicationAddress(appId)

  const fundSp = await algod.getTransactionParams().do()
  const fundTxn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
    sender: deployer.addr,
    receiver: appAddress,
    amount: 700_000,
    suggestedParams: fundSp,
  })
  const signedFund = fundTxn.signTxn(deployer.sk)
  const { txid: fundTxId } = await algod.sendRawTransaction(signedFund).do()
  await waitFor(algod, fundTxId)

  return { appId, appAddress }
}

async function expectFailure(name: string, run: () => Promise<unknown>): Promise<ScenarioResult> {
  try {
    await run()
    return { name, ok: false, detail: 'unexpected success' }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error)
    return { name, ok: true, detail: msg.slice(0, 160) }
  }
}

async function expectSuccess(name: string, run: () => Promise<unknown>): Promise<ScenarioResult> {
  try {
    await run()
    return { name, ok: true, detail: 'ok' }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error)
    return { name, ok: false, detail: msg.slice(0, 160) }
  }
}

function appNoOp(
  sender: string,
  appId: number,
  appArgs: Uint8Array[],
  sp: algosdk.SuggestedParams,
  foreignAssets?: number[],
  fee?: bigint,
) {
  return algosdk.makeApplicationNoOpTxnFromObject({
    sender,
    appIndex: BigInt(appId),
    appArgs,
    foreignAssets,
    suggestedParams: fee ? { ...sp, fee } : sp,
  })
}

async function main() {
  const algod = getAlgodClient()
  const deployer = getAccountFromMnemonic('DEPLOYER_MNEMONIC')

  const assetAId = Number(getRequiredEnv('ASSET_A_ID'))
  const assetBId = Number(getRequiredEnv('ASSET_B_ID'))
  const assetCId = Number(getRequiredEnv('ASSET_C_ID'))

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
  const optInMethod = new algosdk.ABIMethod({
    name: 'opt_in_asset',
    args: [{ type: 'uint64', name: 'assetId' }],
    returns: { type: 'void' },
  })
  const quoteMethod = new algosdk.ABIMethod({
    name: 'quote_swap_exact_in',
    args: [
      { type: 'uint64', name: 'assetInId' },
      { type: 'uint64', name: 'amountIn' },
    ],
    returns: { type: 'uint64' },
  })
  const swapMethod = new algosdk.ABIMethod({
    name: 'swap_exact_in',
    args: [
      { type: 'uint64', name: 'assetInId' },
      { type: 'uint64', name: 'amountIn' },
      { type: 'uint64', name: 'minAmountOut' },
    ],
    returns: { type: 'uint64' },
  })
  const pauseMethod = new algosdk.ABIMethod({ name: 'pause', args: [], returns: { type: 'void' } })
  const unpauseMethod = new algosdk.ABIMethod({ name: 'unpause', args: [], returns: { type: 'void' } })
  const poolStateMethod = new algosdk.ABIMethod({ name: 'get_pool_state', args: [], returns: { type: '(uint64,uint64,uint64,uint64,uint64,uint64,uint64)' } })

  const { appId, appAddress } = await deployFreshApp(algod, deployer)
  console.log(`Validation app deployed: APP_ID=${appId}`)

  const results: ScenarioResult[] = []

  const runSigned = async (txns: algosdk.Transaction[], signer: algosdk.Account) => {
    if (txns.length > 1) algosdk.assignGroupID(txns)
    const signed = txns.map((txn) => txn.signTxn(signer.sk))
    const { txid } = await algod.sendRawTransaction(signed).do()
    await waitFor(algod, txid)
  }

  const sp = await getSuggestedParams(algod)

  results.push(
    await expectFailure('pre-init quote fails', async () => {
      const tx = appNoOp(deployer.addr, appId, [quoteMethod.getSelector(), encU64(assetAId), encU64(10)], sp, [assetBId])
      await runSigned([tx], deployer)
    }),
  )

  for (const assetId of [assetAId, assetBId, assetCId]) {
    const tx = appNoOp(deployer.addr, appId, [optInMethod.getSelector(), encU64(assetId)], { ...sp, fee: 2_000n }, [assetId], 2_000n)
    await runSigned([tx], deployer)
  }

  results.push(
    await expectFailure('create_pool wrong group size fails', async () => {
      const tx = appNoOp(
        deployer.addr,
        appId,
        [
          createPoolMethod.getSelector(),
          encU64(assetAId),
          encU64(assetBId),
          encU64(assetCId),
          encU64(1000),
          encU64(1000),
          encU64(1000),
          encU64(30),
        ],
        sp,
        [assetAId, assetBId, assetCId],
      )
      await runSigned([tx], deployer)
    }),
  )

  results.push(
    await expectFailure('create_pool duplicate asset ids fail', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1000, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1000, assetIndex: assetAId, suggestedParams: sp })
      const tx2 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1000, assetIndex: assetCId, suggestedParams: sp })
      const tx3 = appNoOp(
        deployer.addr,
        appId,
        [
          createPoolMethod.getSelector(),
          encU64(assetAId),
          encU64(assetAId),
          encU64(assetCId),
          encU64(1000),
          encU64(1000),
          encU64(1000),
          encU64(30),
        ],
        sp,
        [assetAId, assetCId],
      )
      await runSigned([tx0, tx1, tx2, tx3], deployer)
    }),
  )

  results.push(
    await expectSuccess('create_pool valid succeeds', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1000, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1000, assetIndex: assetBId, suggestedParams: sp })
      const tx2 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1000, assetIndex: assetCId, suggestedParams: sp })
      const tx3 = appNoOp(
        deployer.addr,
        appId,
        [
          createPoolMethod.getSelector(),
          encU64(assetAId),
          encU64(assetBId),
          encU64(assetCId),
          encU64(1000),
          encU64(1000),
          encU64(1000),
          encU64(30),
        ],
        sp,
        [assetAId, assetBId, assetCId],
      )
      await runSigned([tx0, tx1, tx2, tx3], deployer)
    }),
  )

  results.push(
    await expectFailure('second create_pool fails', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1, assetIndex: assetBId, suggestedParams: sp })
      const tx2 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 1, assetIndex: assetCId, suggestedParams: sp })
      const tx3 = appNoOp(
        deployer.addr,
        appId,
        [
          createPoolMethod.getSelector(),
          encU64(assetAId),
          encU64(assetBId),
          encU64(assetCId),
          encU64(1),
          encU64(1),
          encU64(1),
          encU64(30),
        ],
        sp,
        [assetAId, assetBId, assetCId],
      )
      await runSigned([tx0, tx1, tx2, tx3], deployer)
    }),
  )

  results.push(
    await expectSuccess('pause succeeds', async () => {
      const tx = appNoOp(deployer.addr, appId, [pauseMethod.getSelector()], sp)
      await runSigned([tx], deployer)
    }),
  )

  results.push(
    await expectFailure('swap while paused fails', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 10, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(10), encU64(1)],
        { ...sp, fee: 5_000n },
        [assetBId],
        5_000n,
      )
      await runSigned([tx0, tx1], deployer)
    }),
  )

  results.push(
    await expectSuccess('unpause succeeds', async () => {
      const tx = appNoOp(deployer.addr, appId, [unpauseMethod.getSelector()], sp)
      await runSigned([tx], deployer)
    }),
  )

  results.push(
    await expectFailure('swap group size != 2 fails', async () => {
      const tx = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(10), encU64(1)],
        { ...sp, fee: 5_000n },
        [assetBId],
        5_000n,
      )
      await runSigned([tx], deployer)
    }),
  )

  results.push(
    await expectFailure('swap same in/out fails', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 10, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(10), encU64(1)],
        { ...sp, fee: 5_000n },
        [assetAId],
        5_000n,
      )
      await runSigned([tx0, tx1], deployer)
    }),
  )

  results.push(
    await expectFailure('swap unsupported out asset fails', async () => {
      const fakeAssetOut = assetCId + 9_999_999
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 10, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(10), encU64(1)],
        { ...sp, fee: 5_000n },
        [fakeAssetOut],
        5_000n,
      )
      await runSigned([tx0, tx1], deployer)
    }),
  )

  results.push(
    await expectFailure('swap amount mismatch fails', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 9, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(10), encU64(1)],
        { ...sp, fee: 5_000n },
        [assetBId],
        5_000n,
      )
      await runSigned([tx0, tx1], deployer)
    }),
  )

  results.push(
    await expectFailure('swap slippage guard fails', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 10, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(10), encU64(10_000)],
        { ...sp, fee: 5_000n },
        [assetBId],
        5_000n,
      )
      await runSigned([tx0, tx1], deployer)
    }),
  )

  results.push(
    await expectFailure('swap >5% reserveIn fails', async () => {
      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 60, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(60), encU64(1)],
        { ...sp, fee: 5_000n },
        [assetBId],
        5_000n,
      )
      await runSigned([tx0, tx1], deployer)
    }),
  )

  results.push(
    await expectFailure('quote same in/out fails', async () => {
      const tx = appNoOp(deployer.addr, appId, [quoteMethod.getSelector(), encU64(assetAId), encU64(10)], sp, [assetAId])
      await runSigned([tx], deployer)
    }),
  )

  results.push(
    await expectSuccess('quote valid succeeds', async () => {
      const tx = appNoOp(deployer.addr, appId, [quoteMethod.getSelector(), encU64(assetAId), encU64(10)], sp, [assetBId])
      await runSigned([tx], deployer)
    }),
  )

  results.push(
    await expectSuccess('swap valid succeeds', async () => {
      const appBefore = await algod.getApplicationByID(appId).do()
      const gsBefore = appBefore.params.globalState ?? []
      const reserveCBefore = readUintState(gsBefore, 'reserveC')

      const tx0 = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({ sender: deployer.addr, receiver: appAddress, amount: 10, assetIndex: assetAId, suggestedParams: sp })
      const tx1 = appNoOp(
        deployer.addr,
        appId,
        [swapMethod.getSelector(), encU64(assetAId), encU64(10), encU64(1)],
        { ...sp, fee: 5_000n },
        [assetBId],
        5_000n,
      )
      await runSigned([tx0, tx1], deployer)

      const appAfter = await algod.getApplicationByID(appId).do()
      const gsAfter = appAfter.params.globalState ?? []
      const reserveCAfter = readUintState(gsAfter, 'reserveC')
      if (reserveCAfter >= reserveCBefore) {
        throw new Error('third reserve did not decrease during swap')
      }
    }),
  )

  results.push(
    await expectSuccess('get_pool_state succeeds', async () => {
      const tx = appNoOp(deployer.addr, appId, [poolStateMethod.getSelector()], sp)
      await runSigned([tx], deployer)
    }),
  )

  const burner = algosdk.generateAccount()
  const fundSp = await getSuggestedParams(algod)
  const fundBurnerTx = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
    sender: deployer.addr,
    receiver: burner.addr,
    amount: 300_000,
    suggestedParams: fundSp,
  })
  await runSigned([fundBurnerTx], deployer)

  results.push(
    await expectFailure('non-admin pause fails', async () => {
      const burnerSp = await getSuggestedParams(algod)
      const tx = appNoOp(burner.addr, appId, [pauseMethod.getSelector()], burnerSp)
      await runSigned([tx], burner)
    }),
  )

  const passed = results.filter((r) => r.ok).length
  const total = results.length

  console.log('\n--- Edge Case Validation Results ---')
  for (const result of results) {
    console.log(`${result.ok ? 'PASS' : 'FAIL'} | ${result.name} | ${result.detail}`)
  }

  console.log('\n--- Summary ---')
  console.log(`APP_ID=${appId}`)
  console.log(`Passed ${passed}/${total} scenarios`)

  if (passed !== total) {
    process.exitCode = 1
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
