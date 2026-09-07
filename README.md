# alpha-wolves — IMC Prosperity Trading Bots

This repo contains our team's algorithmic trading code, research notebooks, and manual-challenge
analysis for **IMC Prosperity**, a multi-round market-making/trading simulation competition.
Each round, IMC provides a simulated exchange with a handful of tradable products; contestants
submit a Python `Trader` class that receives an order-book snapshot every tick and returns orders,
with PnL settled against realistic (bot-driven) counterparties.

> **Folder-naming note (read this first):** the directory names on disk do **not** reliably match
> the actual competition round numbers — see [Round mapping](#round-mapping) below. This README
> documents what the code actually does per product, and calls out the mismatches explicitly.

## Table of contents

- [How Prosperity trading works here](#how-prosperity-trading-works-here)
- [Round mapping](#round-mapping)
- [Shared framework](#shared-framework)
- [Practice / Tutorial round — TOMATOES & EMERALDS](#practice--tutorial-round--tomatoes--emeralds)
- [Round 1 — ASH_COATED_OSMIUM & INTARIAN_PEPPER_ROOT](#round-1--ash_coated_osmium--intarian_pepper_root)
- [Round 3 — VELVETFRUIT_EXTRACT options & HYDROGEL_PACK](#round-3--velvetfruit_extract-options--hydrogel_pack)
- [Round 4 — HYDROGEL_PACK & counterparty-flow trading](#round-4--hydrogel_pack--counterparty-flow-trading)
- [Manual trading challenges](#manual-trading-challenges)
- [Results](#results)
- [Known issues & repo hygiene](#known-issues--repo-hygiene)
- [Repo layout](#repo-layout)

---

## How Prosperity trading works here

Every trader in this repo implements the same contract, defined by IMC's SDK
([`datamodel.py`](practice_round/datamodel.py)):

```python
class Trader:
    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        # state.order_depths[product]  -> current bids/asks (price -> volume)
        # state.position[product]      -> our current signed position
        # state.own_trades / market_trades -> fills since last tick (incl. named bot counterparties)
        # returns: orders to place, # conversions, and a traderData string we get back next tick
        ...
```

Because `traderData` is the only thing that survives between ticks, every trader here serializes
whatever state it needs (price history, regression coefficients, rolling IV, etc.) to JSON on the
way out and reloads it on the way in. Every trader also ships a copy-pasted `Logger` class that
compresses `TradingState`/orders into the compact JSON format IMC's visualizer expects
(`logger.flush(...)` at the end of `run`) — this boilerplate is identical across ~15 files in this
repo and could be factored into a shared module, but each round's submission had to be a single
self-contained file for upload.

Common building blocks reused across almost every strategy:
- **Position-limit-aware sizing** — every order size is clipped against `self.limits[product]` minus
  orders already queued this tick (`*_buy_orders` / `*_sell_orders` counters), so a trader never
  double-commits past its position cap within one `run()` call.
- **Wall-based fair value** — fair price = midpoint of the largest-volume ("wall") bid and ask
  levels, rather than the naive best bid/ask, on the theory that the level with the most resting
  volume is the "real" market-maker quote.
- **Quote-jumping** — when a rival maker is already quoting inside our intended spread, step one
  tick in front of them (`best_bid+1` / `best_ask-1`) instead of crossing the spread outright.
- **Take-then-make** — every strategy first sweeps any mispriced resting orders on the book
  (`search_buys`/`search_sells`), then posts its own passive quotes with whatever size budget is
  left.

## Round mapping

| Folder | Products found in the code | What it actually is |
|---|---|---|
| `practice_round/` | `TOMATOES`, `EMERALDS` (+ an abandoned `SQUID_INK` stub) | IMC's **Tutorial round** |
| `round1/` | `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT` | **Round 1** (correctly named) |
| `round1/trendfinding.ipynb` | Round 1 products in early cells, then `VELVETFRUIT_EXTRACT`/`VEV_*` options and `HYDROGEL_PACK` in later cells | Contains **Round 1** analysis *and*, appended later, **Round 3** options research (the notebook's own markdown header even says "Round 3 Analysis") |
| `round2/` | `VELVETFRUIT_EXTRACT`, `VEV_5000..5300` vouchers, `HYDROGEL_PACK` | Mislabeled — every file is versioned `-r3-*` and reads from `datasets/round3/`. **This is Round 3**, not Round 2. `datasets/round2/` is an empty placeholder, so no Round 2 code/data survives in this repo. |
| `round4/` | `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, `VEV_*` (analysis only) | **Round 4** (correctly named); named bot counterparties (`Mark 01/14/22/38/49/55/67`) become tradeable signal here |
| `datasets/round5..round8/` | — | Empty `.gitkeep` placeholders; the team's Prosperity run ended after Round 4 |

## Shared framework

- [`practice_round/datamodel.py`](practice_round/datamodel.py) — IMC's provided SDK types
  (`TradingState`, `OrderDepth`, `Order`, `Observation`, etc.), copied into most round folders.
- [`practice_round/example.py`](practice_round/example.py) — IMC's official starter template
  (VWAP "acceptable price" = running-total-price / running-total-volume, take any order past it).
  Everything else in the repo evolved from this skeleton.
- [`practice_round/reversion_algo`](practice_round/reversion_algo) — **not Prosperity code.** It's
  a standalone real-market Interactive Brokers pairs-trading bot (`ib_insync`, hedge-ratio z-score
  entry/exit/stop-loss between two stock tickers). It was kept as the conceptual template that the
  team explicitly ported into the TOMATOES z-score logic in `alphatrader-r0-v4/v5.py`.

## Practice / Tutorial round — TOMATOES & EMERALDS

Files: `practice_round/alphatrader-r0-v1.py` → `v5.py`, `alphatrader-squink.py`, `CBoilerV1.py`,
`68067/`.

**EMERALDS** trades in a tight, pegged band around a known fair value, so every version just hard-codes
`FAIR = 10000` and market-makes a fixed distance from it (9995/10005 in v1, tightened to 9996/10004
from v2 onward), taking any resting order priced better than 10000 and quote-jumping a tighter rival
maker. Position limit 80 throughout.

**TOMATOES** is noisier/drifting, so the strategy evolved considerably:

| Version | TOMATOES logic |
|---|---|
| v1 | Market-make around `(worst_bid+worst_ask)/2 ± 3`, limit 40 |
| v2 | Same, but fair price uses the *second*-worst book level; limit raised to 80 |
| v3 | Adds a 15-tick rolling VWAP history + takes orders >1.2σ from the rolling mean, with one-shot flags to avoid repeat-hitting the same side |
| v4/v5 | Full rewrite into a **z-score mean-reversion state machine**, with state persisted via `traderData` JSON: `MR_WINDOW=40–500` (varies by revision), `MR_ENTRY_Z=1.5`, `MR_EXIT_Z=0.4`, `MR_STOP_Z=3.5`, `MR_Z_SCALE=1.5`. Regimes: `|z| > STOP` → close position at market; `z < -ENTRY` → aggressive buy; `z > ENTRY` → aggressive sell; `|z| < EXIT` → unwind to flat; otherwise → normal wall-based take/make, skewed by `z_score * MR_Z_SCALE`. |

`alphatrader-squink.py` is a separate, un-renamed prototype exploring a **trend-following** variant
for TOMATOES instead: short(5)/long(30) moving-average crossover to gate which side can trade, a
10-tick rolling volatility window, and a "flash crash" override (`delta_vol > 2`) that flips to
trade the reversal. It also contains a dead, never-wired-in `SQUID_INK` market-making stub —
`SQUID_INK` isn't actually in this dataset. `CBoilerV1.py` is boilerplate forked from v1 (used as a
scratch base for branching experiments, not a distinct strategy in its own right).

## Round 1 — ASH_COATED_OSMIUM & INTARIAN_PEPPER_ROOT

Files: `round1/alphatrader-r1-v1.py`, `-v3.py`, `-final-review.py`, `-final-MR.py`,
`-squink.py`; manual challenge in [`datasets/round1/r1_manual.txt`](datasets/round1/r1_manual.txt).

Product names are renamed mid-competition versions of the practice-round pair (comments confirm
`ASH_COATED_OSMIUM` *was* `TOMATOES`/`EMERALDS`-style and `INTARIAN_PEPPER_ROOT` *was* `EMERALDS`);
both carry a position limit of 80. The strategy split into two different philosophies once the data
showed the two products behave very differently:

**ASH_COATED_OSMIUM — fixed-anchor mean reversion (final version, `trade_osmium`)**

Osmium oscillates tightly around 10,000, so the final strategy (`alphatrader-r1-final-MR.py`) drops
the computed wall-mid entirely in favor of a hard anchor and a discrete entry/target state machine:

```
FAIR = 10000; ENTRY_STEP = 1; MIN_TARGET = 15; STEP_SIZE = 3; MAX_TAKE = 15
best_ask <= FAIR - ENTRY_STEP  → target = min(limit, MIN_TARGET + discount/ENTRY_STEP * STEP_SIZE)
                                  take cheap asks up to target, then quote passively at FAIR
best_bid >= FAIR + ENTRY_STEP  → mirror image on the short side
otherwise                      → neutral market-make around FAIR (adaptive spread, quote_size=10)
```

Deeper mispricing → bigger inventory target; reaching the opposite signal naturally unwinds/flips
the position (no explicit stop-loss is needed).

**INTARIAN_PEPPER_ROOT — regression-following (`trade_pepper`)**

Fits `scipy.stats.linregress` (or `numpy.polyfit` fallback) on up to the last 1,000 market trades
(`t_rel = (timestamp - t0)/1000` seconds vs. price) every tick, and uses the fitted line's
extrapolated value as a directional price forecast. Quotes are centered on a separate wall-based
mid, widened to 15 ticks on a side with no competing quotes (else 8), stepped in front of any rival
maker. The final version aggressively takes asks up to `fair + 8` (depth 10) but only ever posts the
**buy** side — the sell leg is commented out, making this a long-only momentum strategy in its
shipped form.

Strategy evolution: v1 paired the regression with a full OLS significance filter (only trade when
`p < 0.1`) and a 5% trailing stop; v3 replaced that with explicit time-of-day regimes (aggressive
directional entry in the first/last 20% of the trading day, pure market-making midday); the
final-review/final-MR versions stripped all of that back down to the bare regression + one-sided
taker, judged simpler and more robust than the regime-switching versions.

`alphatrader-squink.py` here is again an un-renamed earlier prototype (trading `TOMATOES`/`EMERALDS`
directly) rather than a squid-ink-specific strategy.

## Round 3 — VELVETFRUIT_EXTRACT options & HYDROGEL_PACK

Files: `round2/alphatrader-r3-v3.py`, `round2/alphatrader-r3-gamma.py`, `round2/anal.ipynb`,
`round1/trendfinding.ipynb` (later cells); manual challenge in
[`datasets/round3/r3_manual`](datasets/round3/r3_manual). *(See [Round mapping](#round-mapping) —
this is filed under `round2/` but is Round 3 content.)*

This round introduced a European-call-style options chain, **VEV_<strike>**, on the underlying
**VELVETFRUIT_EXTRACT (VFE)**, plus an unrelated pure market-making product, **HYDROGEL_PACK**.
Position limits: VFE 200, VEV_5000/5100 200, VEV_5200 75, VEV_5300 50, HYDROGEL_PACK 200. The raw
dataset also lists deep strikes (4000/4500/5400/5500/6000/6500) that the live trader never touches —
only the four liquid strikes 5000–5300 are traded.

**Research pipeline (`anal.ipynb` + the tail of `round1/trendfinding.ipynb`)** — this is the most
quantitatively involved analysis in the repo:
1. Priced VEV options with a CRR binomial tree, then backed out **Black-Scholes implied volatility**
   per strike via `scipy.optimize.brentq` root-finding.
2. Found a clear **vol skew** (~0.00034 at K=4500 down to ~0.00017–0.00018 at K=5000–5300) and fit a
   **linear IV-vs-time trend per strike** (`np.polyfit`, degree 1) — explicitly "for hardcoding into
   the trader."
3. Fit an **Ornstein–Uhlenbeck** mean-reversion model to VFE itself: `theta ≈ 0.0025`/tick,
   half-life ≈ 280 ticks, `mu ≈ 5250.7`, equilibrium std ≈ 16 — this directly informed the
   `VFE_PRIOR=5257` / `VFE_ENTRY=10` constants used later.
4. Tested order-flow imbalance (OFI) vs. next-tick return (modest −0.32 correlation) and explored a
   Merton jump-diffusion model as an alternative pricer (numerically unstable, not adopted).
5. Cross-strike and cross-instrument consistency checks: anchoring IV on one strike (`VEV_5200`) and
   pricing the others off it to isolate genuine cross-strike mispricing from noise; fitting a
   rolling quadratic IV smile across strikes and treating deviations from the smile as the trade
   signal; and even solving for an **options-implied VFE spot** (jointly inverting two strikes'
   Black-Scholes prices for `(S, σ)`) to detect dislocations between the options market and the
   underlying's own quoted mid-price.

**Live trader (`alphatrader-r3-v3.py`)** ships a simplified version of that research:

```
S      = trader's own smoothed VFE fair value:  0.7 * PRIOR(5257) + 0.3 * slow_EMA(mid, alpha=0.001)
T      = (50,000 - global_tick) ticks to a fixed 5-day expiry horizon
iv(K)  = hardcoded per-strike linear fit:  IV_SLOPE[K] * global_t + IV_INTERCEPT[K]
fair   = BlackScholes(S, K, T, r=0, iv(K))          # d1/d2 with N() the normal CDF
```
No live IV solving and **no delta/gamma hedging** — it's pure mispricing capture: buy a voucher when
`market_ask <= fair - 1 tick`, sell when `market_bid >= fair + 1 tick`, laddering position size
(`VEV_ADD_QTY` per extra `VEV_ADD_STEP` of mispricing) rather than hedging directional VFE exposure.
`HYDROGEL_PACK` is a self-contained inventory-skewed market maker (edge 4 ticks, quote size 10,
position cap 30, skew coefficient `-0.3 * position`), unrelated to the options book.

Despite its name suggesting Greeks-based hedging, **`alphatrader-r3-gamma.py` has nothing to do with
delta/gamma at all** — it's an earlier, minimal, VFE-only mean-reversion module (the same
`0.7*PRIOR + 0.3*EMA` fair-value formula, `CLIP=30`, `ENTRY=10`) that was later folded into `v3.py`
as the Black-Scholes underlying signal. "Gamma" was just an internal version codename.

## Round 4 — HYDROGEL_PACK & counterparty-flow trading

Files: `round4/new/alphatrader-r4-v4.py`, `round4/analysis.ipynb`.

Same product set as Round 3 (`HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, `VEV_*`), but the trade log now
carries **named bot counterparties** (`Mark 01, 14, 22, 38, 49, 55, 67`), and the round's real
innovation is exploiting them rather than pricing options — the live trader doesn't touch `VEV_*` at
all.

**`trade_hydrogel`** is a straightforward microprice market maker: fair value
`(bid*ask_vol + ask*bid_vol)/(bid_vol+ask_vol)`, inventory-skew trimming past `SKEW_THRESH=20`
(`SKEW_QTY=10`), and passive quotes (`QUOTE_SIZE=25`) skewed by `position/limit`, spread 4 ticks
(10 if a side of the book is empty).

**`trade_vfe`** hardcodes a counterparty list:
```python
FOLLOW_TRADERS = {"Mark 67"}          # comment claims: 83% win rate, +1.9 avg fwd return
FADE_TRADERS   = {"Mark 22", "Mark 49"}  # comment claims: 14-22% win rate
```
and each tick scans `state.market_trades` for these names, market-ordering `FOLLOW_QTY=15` in the
direction Mark 67 just traded (or opposite Mark 22/49), on top of the same skew-trim + imbalance-
skewed passive quoting used for hydrogel.

**`analysis.ipynb`** — "Alpha hunting: per-trader signed-flow vs forward return" — is the notebook
that this logic is *supposed* to be based on. Methodology: per-trade edge vs. mid (are they paying
through the spread or trading favorably?), then a rolling-sum signed-flow-vs-forward-return Pearson
correlation per trader, scanned across several window/horizon combinations. What it actually found:

- **Mark 55** has a small, *consistently positive* flow→forward-return correlation across all three
  days (≈ +0.09 to +0.11 at a 5,000/5,000-tick window) — a genuine "follow" signal.
- **Mark 14** has a small, *consistently negative* correlation (≈ −0.08 to −0.11) — a genuine "fade"
  signal, and its mirror-image relationship to HYDROGEL_PACK's Mark 38 flow is noted too.
- A backtested composite signal, `rolling_sum(Mark55 flow) − rolling_sum(Mark14 flow)` scaled into a
  ±200 position via a 95th-percentile normalizer, produced roughly **+15,000 PnL** over 3 days at a
  15,000-tick window (the notebook's own prose claims "~+50k", which the printed backtest table
  doesn't actually support).
- Mark 67 and Mark 22/49 (the pair actually hardcoded into the live trader) show **unstable,
  sign-flipping correlations day to day** in the same table — e.g. Mark 67: +0.045, −0.212, −0.336
  across days 1–3 — the opposite of a reliable edge.

**This is a real discrepancy worth flagging**: the shipped `alphatrader-r4-v4.py` follows/fades
Mark 67/22/49, but the notebook's own numbers say the actionable, stable pair is Mark 55 (follow) /
Mark 14 (fade). The in-code comments citing "83% win rate" for Mark 67 don't match anything printed
in `analysis.ipynb` — it looks like the live version was hand-tuned from an earlier/rougher pass and
never reconciled with the final notebook conclusions.

The notebook also separately found order-book imbalance (OBI) to be predictive at local price
extrema (≈ −0.26 at peaks, +0.30 at troughs vs. ~0 baseline) and priced the VEV chain's consensus
implied vol at ≈1.27% — neither of which made it into the live trader.

## Manual trading challenges

Each round also included a non-coding "manual" challenge (a one-shot optimization/game-theory
problem, not live trading). Write-ups:

- **[`datasets/round1/r1_manual.txt`](datasets/round1/r1_manual.txt)** — optimal single-shot bid
  pricing under price-time priority for two goods ("Dryland Flax", "Ember Mushroom"), each with a
  resale value and fee structure. Solved by computing executable fill quantity at each candidate
  bid price (accounting for queue priority ahead of your order) and maximizing
  `quantity × (resale − fees − bid)`. Result: bid 29 for Dryland Flax (5,000 units, profit 5,000) and
  bid 18 for Ember Mushroom (35,000 units, profit 66,500) — **total optimized profit 71,500.**
- **[`datasets/round3/r3_manual`](datasets/round3/r3_manual)** — a two-round sealed-bid auction
  against N sellers with reserve prices uniform on [670, 920] and resale value 920. Part 1 (pure
  optimization) gives the closed-form optimal bid as the midpoint, `b1* = 795`. Part 2 adds a
  game-theoretic penalty, `((920-μ)/(920-b2))³`, applied whenever your bid `b2` is below the
  average bid `μ` across all teams — the analysis shows this penalty term has no interior optimum
  inside the valid range (the unconstrained derivative solves to `b2=420`, outside `[670,920]`), so
  the penalized profit function is strictly increasing and the right policy is
  `b2* = max(795, estimated μ)`, rounded to the nearest 5.

## Results

- The one **submitted tutorial run** we have a log for (`datasets/tutorial/submission.log`) ended at
  **TOMATOES +1265.30 / EMERALDS +1050.00 (≈ +2,315 total)** over a 200,000-timestamp day.
- A separate local backtest (`practice_round/68067/`) crashed every tick with `KeyError: 'EMERALDS'`
  (an `example.py`-style trader indexing `state.market_trades[product]` for a product with no market
  trades yet) and placed no orders — it drifted to roughly **-618.78** by end of day purely from
  passive market moves. A useful reminder to defensively `.get()` dict lookups against per-tick
  state rather than assuming every product has trades every tick.
- Git history records two informal milestones during Round 1 development: *"tanush trading algo make
  9.8k W"* and *"FINAL 10.3K ON PROSPERITY"* — the team's best local-backtest PnL before the final
  Round 1 submission was cut.

## Known issues & repo hygiene

- **Folder/round naming mismatch**: `round2/` is actually Round 3 content (see
  [Round mapping](#round-mapping)); `round1/trendfinding.ipynb` mixes Round 1 and Round 3 analysis
  in one notebook. Worth a rename pass (`round2/` → `round3/`) if the repo is revisited.
- **`round1/alphatrader-r1-v5`** is a plain file with no `.py` extension, and is byte-identical to
  `alphatrader-r1-v3.py` — looks like an accidental duplicate/rename-without-extension rather than a
  real v5 iteration (the actual "v5" strategic evolution for Round 1 is `alphatrader-r1-final-MR.py`).
- **`practice_round/alphatrader-r0-v4.py`** has a structural indentation bug: the passive
  market-making quote block for TOMATOES sits inside the `else` (normal-regime) branch, so it never
  fires while a stop-loss/entry/exit regime is active — only order-taking happens in those regimes,
  with no resting quotes. Worth checking whether this survived into later versions before reusing
  that code.
- **`round4/alphatrader-r4-v4.py`**'s hardcoded follow/fade counterparty list (Mark 67 / Mark 22,49)
  doesn't match the stable correlations actually reported in `round4/analysis.ipynb` (Mark 55 /
  Mark 14) — see [Round 4](#round-4--hydrogel_pack--counterparty-flow-trading) above.
- **`practice_round/reversion_algo`** is unrelated real-market (Interactive Brokers) code kept for
  reference — don't mistake it for a Prosperity submission.
- The per-file `Logger`/`Trader` boilerplate (state compression for IMC's visualizer, position-limit
  bookkeeping) is duplicated near-verbatim across ~15 files, since each round's submission has to be
  a single self-contained script; there's no shared package.

## Repo layout

```
practice_round/   Tutorial round (TOMATOES, EMERALDS) — v1-v5 iterations, squid-ink prototype,
                   IB pairs-trading reference script, one local backtest (68067/)
round1/           Round 1 (ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT) — v1/v3/final-review/final-MR,
                   plus a notebook mixing Round 1 and Round 3 analysis
round2/           Actually Round 3 (VELVETFRUIT_EXTRACT + VEV_* options, HYDROGEL_PACK) —
                   options-pricing trader + Black-Scholes/vol-skew research notebook
round4/           Round 4 (HYDROGEL_PACK, VELVETFRUIT_EXTRACT) — counterparty-flow trader +
                   signed-flow/forward-return research notebook
datasets/         Raw price/trade CSVs and manual-challenge write-ups per round
```
