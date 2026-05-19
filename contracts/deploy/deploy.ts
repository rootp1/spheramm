import algosdk from 'algosdk'
import fs from 'node:fs'
import path from 'node:path'

const approvalTealPath = path.resolve(process.cwd(), 'src/artifacts/TriAssetAmm.approval.teal')
const clearTealPath = path.resolve(process.cwd(), 'src/artifacts/TriAssetAmm.clear.teal')

async function main() {
  if (!fs.existsSync(approvalTealPath) || !fs.existsSync(clearTealPath)) {
    throw new Error('Build artifacts missing. Run: npm run build -w contracts')
  }

  const mnemonic = process.env.DEPLOYER_MNEMONIC
  if (!mnemonic) throw new Error('DEPLOYER_MNEMONIC is required in .env')

  const algodServer = process.env.ALGOD_SERVER ?? 'https://testnet-api.algonode.cloud'
  const algodPort = process.env.ALGOD_PORT ?? '443'
  const algodToken = process.env.ALGOD_TOKEN ?? ''

  const algod = new algosdk.Algodv2(algodToken, algodServer, algodPort)

  const deployer = algosdk.mnemonicToSecretKey(mnemonic)
  const approvalTeal = fs.readFileSync(approvalTealPath, 'utf-8')
  const clearTeal = fs.readFileSync(clearTealPath, 'utf-8')
  const approvalCompiled = await algod.compile(approvalTeal).do()
  const clearCompiled = await algod.compile(clearTeal).do()

  const suggestedParams = await algod.getTransactionParams().do()
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
    extraPages: 1,
    suggestedParams,
    onComplete: algosdk.OnApplicationComplete.NoOpOC,
  })

  const signed = appCreateTxn.signTxn(deployer.sk)
  const { txid } = await algod.sendRawTransaction(signed).do()
  const result = await algosdk.waitForConfirmation(algod, txid, 4)

  if (!result.applicationIndex) throw new Error('Application deployment failed')

  const appId = Number(result.applicationIndex)
  const appAddress = algosdk.getApplicationAddress(appId)
  const paymentSp = await algod.getTransactionParams().do()
  const fundTxn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
    sender: deployer.addr,
    receiver: appAddress,
    amount: 500_000,
    suggestedParams: paymentSp,
  })
  const signedFundTxn = fundTxn.signTxn(deployer.sk)
  const { txid: fundTxId } = await algod.sendRawTransaction(signedFundTxn).do()
  await algosdk.waitForConfirmation(algod, fundTxId, 4)

  console.log('AMM App deployed')
  console.log(`APP_ID=${appId}`)
  console.log(`APP_ADDRESS=${appAddress}`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
