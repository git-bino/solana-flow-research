# Headline numbers

Numbers only, with the spec section that defines each. No interpretation.
Snapshot 2026-08-19.

## Universe (§2.2, §2.4)

| | |
|---|---|
| Launch window, dev | [2026-05-10 00:00, 2026-07-03 00:00) UTC · 54 days |
| Event window | to 2026-08-15 23:59 UTC |
| Quote filter | `createevent.virtual_sol_reserves = 30000000000` |
| Age cut | none, N = ∞ |
| Activity / volume / lifetime / migration filters | none |
| Burst rows | **667,809** |
| Distinct tokens | **452,469** |
| Bursts per token | 1.476 |
| mayhem rows (§2.2 stratum) | **51,141 (7.66%)** |
| Launch days with ≥1 burst | 54 of 54 |
| Bursts per launch day | min 8,478 · max 17,576 · max/min 2.07 |
| Holdout (§6.1) | [2026-07-12, 2026-08-08) — never extracted, `data/holdout/` empty |
| Not extracted | chunk 7, launch [2026-07-03, 2026-07-12) |

### Per chunk (§2.4)

| chunk | launch window | burst rows | Dune credits |
|---|---|---|---|
| 1 | 2026-05-10 … 05-19 | 133,877 | 481.94 |
| 2 | 2026-05-19 … 05-28 | 108,385 | 304.97 |
| 3 | 2026-05-28 … 06-06 | 107,563 | 301.32 |
| 4 | 2026-06-06 … 06-15 | 94,544 | 271.90 |
| 5 | 2026-06-15 … 06-24 | 109,534 | 295.78 |
| 6 | 2026-06-24 … 07-03 | 113,906 | 362.04 |
| **total** | | **667,809** | **2,017.95** |

### Extract schema (§2.3)

| | |
|---|---|
| Columns | 60 (canonical, `src/extract_schema.py`) |
| Row width | 1,105.9 – 1,127.0 B (chunks 2–6) |
| Columns carrying NULL | 5 of 60: `quote_mint` 167,278 · `death_age_slot` 4,938 · `death_age_incl` 28 · `death_age_excl` 17 · `accel` 1 |
| §2.3 columns absent from the realised schema | `y`, `k`, `P_t` |

## KILL gate — curve reconstruction (§7 Phase 0 checks 1a / 1b / 1c)

Thresholds: 1a ≥ 99.99% on non-mayhem · 1b p99 < 1e-9 · 1c 100.00% and one distinct x₀.

| | window 1 | window 2 | window 4 | window 6 |
|---|---|---|---|---|
| launch | 05-10 … 05-19 | 05-19 … 05-28 | 06-06 … 06-15 | 06-24 … 07-03 |
| **1a** Δvsol, non-mayhem | 15,310,479 / 15,310,479 = 100.0000% | 15,381,582 / 15,381,582 = 100.0000% | 13,275,346 / 13,275,346 = 100.0000% | 14,580,264 / 14,580,264 = 100.0000% |
| **1a** Δvtok, non-mayhem | not measured | 100.0000% | 100.0000% | 100.0000% |
| **1b** p50 | 8.21e-12 | 9.596e-12 | 9.523e-12 | 8.149e-12 |
| **1b** p99 | 3.27e-11 | 3.257e-11 | 3.281e-11 | 3.278e-11 |
| **1b** max | 3.33e-11 | 3.333e-11 | 3.333e-11 | 3.333e-11 |
| **1c** first trade at x = 30 SOL | 241,718 / 241,718 = 100.00% | 218,096 / 218,096 = 100.00% | 218,814 / 218,814 = 100.00% | 230,515 / 230,515 = 100.00% |
| **1c** distinct implied x₀ | 1 | 1 | 1 | 1 |
| **verdict** | PASS | PASS | PASS | PASS |

Window 1 is cited from `docs/phase0_quote_mint_verify.md`, not re-run.
Windows 3 and 5 are **not measured**.
Non-mayhem mismatches across windows 2, 4, 6: **0 of 43,237,192 pairs**.

### mayhem, reported separately (not a pass/fail criterion)

| | window 2 | window 4 | window 6 |
|---|---|---|---|
| mayhem-touching pairs | 3,831,342 | 5,594,368 | 4,427,276 |
| Δvsol matched | 39.48% | 41.08% | 41.28% |
| Δvtok matched | 100.00% | 100.00% | 100.00% |
| \|Δ(x·y)/(x·y)\| p50 | not measured | 0.0765 | 0.0743 |
| \|Δ(x·y)/(x·y)\| p99 | not measured | 0.4601 | 0.4606 |
| \|Δ(x·y)/(x·y)\| max | not measured | 8.690 | 8.036 |

`P(t)` uses launch `k = x₀·y₀` from createevent in both the SQL and the Python
reference (§1.1; `docs/phase0_k_source.md`).

## Phase 3a — baseline and power (§7 Phase 3a)

Cell: §4.1 primary — burst threshold 0.10x, τ = 12 slots, mayhem excluded.
n = 667,809 − 51,141 = **616,668**.

### A. Unconditional `fwd_net_flow_12slot` (SOL). Mean not reported (§6.4).

| | |
|---|---|
| median | **0.558073** |
| 10% trimmed mean | **1.232737** |
| p1 · p5 · p10 · p25 | −9.435831 · −4.826950 · −3.788413 · −1.231989 |
| p75 · p90 · p95 · p99 | 3.900000 · 9.029645 · 14.034276 · 30.294551 |
| min · max | −84.999999999 · 81.647334366 |
| share > 0 | **60.30%** |

### B. Clusters (§6.3)

| | |
|---|---|
| distinct tokens | 409,671 |
| distinct minutes (UTC) | 80,254 |
| bursts per token: median · p90 · max | 1 · 3 · 74 |
| bursts per minute: median · p90 · max | 7 · 14 · 67 |

### C. Power

Pigeonhole two-way cluster bootstrap (token × minute), 8 decile assignments ×
250 replicates = 2,000, seed 20260819. i.i.d. bootstrap not used.

| | row-level deciles | token-level deciles |
|---|---|---|
| SE(median d10 − median d1) | 0.044896 SOL | 0.043882 SOL |
| MDE at 80% power, α = 0.05 (2.8016 × SE) | **0.125779 SOL** | **0.122938 SOL** |

| | |
|---|---|
| Analytic i.i.d. reference SE (comparison only) | 0.025244 SOL |
| Design effect | 3.0× in variance, 1.74× in SE |
| L2 latency (§5) | 1000 ms = 2.5 slots |
| median `v_latency_2slot` · `v_latency_3slot` | 0.000000 · 0.000000 |
| V at 2.5 slots, median | **0.000000 SOL** (26.39% of rows exactly zero) |
| V p75 · p90 · p99 | 0.409886 · 2.070035 · 9.304122 |
| BE = (1+V/x)²(1+q/x)²(1+fees) − 1 at x=50, q=1, fees=0.025 | **0.066410** |
| ΔV required = x(√(1+BE) − 1) | **1.633565 SOL** |

### D. Verdict

| | |
|---|---|
| MDE as a share of the economic threshold | 7.5 – 7.7% |
| Power at threshold-sized effects | ≈ 100.00% |
| **Power ≥ 80% (§7 Phase 3a)** | **YES** |
| §7 exception ("power < 80% means insufficient data, not absent signal") | does not activate |

## Test suite (§8.2 requirement 8)

| | |
|---|---|
| Tests | **122, all passing** (`pytest tests/ -q`, 2026-08-19) |
| Parity cohort | 200 hash-ordered tokens, 15,017 events, 88 burst rows |
| Trajectory parity | 88 × 75 elements, 0 differences |

## ClickHouse load

| | |
|---|---|
| Table | `flow.burst`, MergeTree, `ORDER BY (token_mint, slot, tx_index, ix_index)` |
| Rows | 667,809 |
| Size on disk | 333.99 MiB |
| Post-load asserts | 11 of 11 pass |

## Dune budget

| | |
|---|---|
| Extract, chunks 1–6 | 2,017.95 credits |
| KILL gate, windows 2, 4, 6 | 67.19 credits |
| Remaining at snapshot | 26.84 of 2,500 (period resets 2026-08-31) |
