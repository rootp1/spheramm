# Tri-Asset AMM MVP (Algorand TestNet)

End-to-end MVP of a **3-asset unified AMM pool** on Algorand using:

- AlgoKit CLI
- Smart contracts in Algorand TypeScript (PuyaTS)
- Next.js App Router frontend (TypeScript)
- Pera Wallet integration
- TestNet deployment/scripts

## Project Structure

- `/contracts` — Algorand TypeScript smart contract + deploy script
- `/frontend` — Next.js swap UI + Pera integration
- `/scripts` — ASA creation, pool init, swap test scripts
- `/utils` — shared deterministic AMM math helper

## Smart Contract Summary

Contract file: `contracts/src/tri_asset_amm.algo.ts`

Global state:
- `assetAId`, `assetBId`, `assetCId`
- `reserveA`, `reserveB`, `reserveC`
- `feeBps`
- `admin`
- `paused`
- `totalLpSupply`
- `lpAssetId` (reserved for future ASA LP-token mode)
- `totalLiquidity` (mirrors LP supply for backward compatibility)

Local state:
- `lpBalance` (per-account LP ownership)

Methods:
- `create_pool(assetA, assetB, assetC, amountA, amountB, amountC, feeBps)`
- `quote_swap_exact_in(assetInId, amountIn) -> amountOut`
- `swap_exact_in(assetInId, amountIn, minAmountOut) -> amountOut`
- `get_pool_state()`
- `add_liquidity(amountA, amountB, amountC, minLpOut) -> lpOut`
- `remove_liquidity(lpAmount, minAOut, minBOut, minCOut) -> (amountAOut, amountBOut, amountCOut)`
- `quote_add_liquidity(amountA, amountB, amountC) -> (lpOut, lpRaw, penaltyBps, imbalanceBps)`
- `quote_remove_liquidity(lpAmount) -> (amountAOut, amountBOut, amountCOut)`
- `get_lp_state() -> (totalLpSupply, userLpBalance, geometricL, poolImbalanceBps)`
- `get_pool_value() -> geometricL`
- `pause()` / `unpause()`

Swap validation for `swap_exact_in`:
- group size == 2
- txn[0] is ASA transfer
- sender match
- receiver = app address
- asset and amount match
- paused check

## Invariant / Math

Simplified deterministic integer math (round down only):

1. `amountInAfterFee = floor(amountIn * (10000 - feeBps) / 10000)`
2. Orbital-style geometric invariant:
   - `K = reserveA^2 + reserveB^2 + reserveC^2`
3. For a swap `assetIn -> assetOut` with dynamic third-reserve coupling:
   - `newReserveIn = reserveIn + amountInAfterFee`
   - `newReserveThird = reserveThird - couplingAdjustment`
   - `newReserveOut = floor(sqrt(K - newReserveIn^2 - newReserveThird^2))`
   - `amountOut = reserveOut - newReserveOut`
4. Require `amountOut >= minAmountOut`
5. Update reserves and send output ASA via inner tx

## Orbital-Inspired AMM

This MVP uses a geometric invariant approximation inspired by orbital/spherical AMMs:

- Invariant: `K = A^2 + B^2 + C^2`
- All assets influence price, including single-input/single-output swaps
- Contract solves output reserve via integer square root on-chain

Why this differs from constant-product:

- No pairwise `x*y=k` solve is used
- Swap output is derived from global 3-asset geometry
- Third asset reserve directly constrains and updates during each swap quote

## Dynamic Geometric Coupling

If a swap updates only two reserves while keeping the third reserve fixed, the geometry may still look 3D, but pricing behavior can collapse toward pairwise dynamics for that trade path.

This upgrade prevents that collapse by forcing the third reserve to move on every exact-input swap using deterministic integer coupling logic:

- Invariant: `K = A^2 + B^2 + C^2`
- Input reserve increases after fee
- Third reserve decreases by a deterministic coupling adjustment
- Output reserve is solved from the remaining invariant budget

Why this matters:

- The third reserve is no longer just symbolic in the equation.
- It materially changes execution output for each trade.
- Quotes/swaps are now true 3-reserve coupled geometric pricing, still AVM-safe and integer-only.

Positioning:

- Orbital-inspired geometric AMM design
- Not full Paradigm Orbital
- No ticks / concentrated or range-based liquidity

Limitations (intentional MVP scope):

- Integer-only (uint64) math with floor rounding
- No ticks, concentrated ranges, or dynamic curvature controls
- Dynamic imbalance fee (0.3% to 1.0%)
- First-pass LP accounting (not concentrated-liquidity / no range positions)

## LP Economics Design

Why swaps-first:
- MVP started by validating the orbital-inspired 3-reserve swap engine and AVM-safe integer math.
- LP economics were added as a second layer so swap behavior and invariant safety stayed stable.

LP ownership:
- LP shares are explicit and on-chain: `totalLpSupply` + per-user `lpBalance` in app local state.
- Initial pool creator receives initial LP supply equal to initial seeded liquidity baseline.

Deposit minting:
- Pool value metric uses geometric liquidity: `L = floor(sqrt(A^2 + B^2 + C^2))`.
- Deposit quote uses the same geometric metric for consistent integer-only behavior.
- Base mint: `lpRaw = floor(depositL * totalLpSupply / poolL)`.
- Mild imbalance adjustment reduces minted LP for highly one-sided deposits.

Withdrawal burning:
- Burned LP removes proportional reserves:
- `amountOutX = floor(reserveX * lpBurn / totalLpSupply)` for X in A/B/C.
- Accounting updates LP supply and reserves atomically.

Fee accrual:
- Swap fees stay in reserves (no external fee vault).
- As reserves grow from fees, `L/LP` (value per share) rises naturally over time.

What is exact vs approximate:
- Exact on-chain: reserve updates, LP mint/burn, swap execution, and proportional withdrawals.
- Approximate UX: frontend quote previews and geometric display are deterministic approximations of on-chain outcomes, with slippage protection in transactions.

## Prerequisites

- Node.js 22+
- AlgoKit CLI 2.5+
- Python env with `puyapy` through AlgoKit
- Funded TestNet account(s)

## Environment

Copy and fill:

```bash
cp .env.example .env
cp frontend/.env.local.example frontend/.env.local
```

Required in `.env`:
- `DEPLOYER_MNEMONIC`
- `USER_MNEMONIC` (can be same as deployer for MVP)
- network endpoints (defaults already TestNet AlgoNode)

## Setup & Run

From project root:

```bash
npm run bootstrap
```

### 0) Fund deployer via TestNet Dispenser API (recommended)

Authenticate once:

```bash
algokit dispenser login
```

Then set `ALGOKIT_DISPENSER_ACCESS_TOKEN` in `.env` and run:

```bash
npm run fund:testnet
```

This uses:
- `ensureFundedFromTestNetDispenserApi` for minimum balance targeting
- optional direct funding via `TOP_UP_MICROALGOS` if set > 0

### 1) Build contract artifacts

```bash
npm run build:contracts
```

### 2) Deploy contract (TestNet)

```bash
npm run deploy:testnet
```

Take printed `APP_ID` and set `AMM_APP_ID` in `.env` and `NEXT_PUBLIC_AMM_APP_ID` in `frontend/.env.local`.

### 3) Create 3 ASAs

```bash
npm run create:asas
```

Set returned IDs into:
- `.env` as `ASSET_A_ID`, `ASSET_B_ID`, `ASSET_C_ID`
- `frontend/.env.local` as `NEXT_PUBLIC_ASSET_A_ID`, `NEXT_PUBLIC_ASSET_B_ID`, `NEXT_PUBLIC_ASSET_C_ID`

### 4) Initialize pool with 1000 each

```bash
npm run init:pool
```

### 5) Run frontend

```bash
npm run dev:frontend
```

Open `http://localhost:3000`, connect Pera, and swap.

### 6) Scripted swap test (10 A -> B)

```bash
npm run swap:test
```

This performs atomic group:
- Txn0: ASA transfer `A` user -> app
- Txn1: app call `swap_exact_in` with `foreignAssets=[B]`

Then prints updated reserves.

### 7) LP and fee-growth tests

```bash
npm run lp:test
npm run fee-growth:test
```

These log:
- reserves before/after
- LP supply before/after
- geometric liquidity metric
- deposit/withdraw outcomes
- value-per-LP growth signal after swaps

## Demo Flow Checklist

1. Deploy contract
2. Create 3 ASAs
3. Initialize pool (1000 each)
4. Connect Pera wallet in UI
5. Swap `10 A -> B`
6. Observe updated reserves in UI and script output

## Notes

- Deterministic uint64-only math; no floating point in contract.
- Output always rounds down.
- Frontend quote preview uses same formula for UX estimate.
- Keep this MVP on TestNet only.
