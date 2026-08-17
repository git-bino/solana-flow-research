-- Phase 0 — feasibility prototype: is f7 (OH_ratio, spec §1.2) expressible in
-- Dune SQL?  Feasibility only.  Phase 2 is not implemented here.
--
-- SCOPE SIMPLIFICATION (stated, not hidden): OH is computed only at burst_start
-- moments, not at every event.  f7 is a signal-instant feature and both Phase 3
-- tests (decile, hazard) operate on bursts, so burst-instant OH is what the
-- research needs.  §Phase 2's "every event" wording applies to the local
-- implementation; this prototype is narrower and the report says so.
--
-- The hard part is that OH(t) is an aggregate over per-wallet *state as of t*.
-- It is expressed here without a cross join: each wallet's running state is
-- valid over a half-open interval of sequence numbers, so bursts are matched to
-- state with an interval join.  Work is proportional to (state rows x bursts
-- they are visible to), not to (events x bursts).
--
--   seqd    events numbered per token in (slot, tx_index, ix_index) order
--   flow    net_flow_5slot as a difference of prefix sums, so the window cuts AT
--           the current row -- a plain RANGE frame would include same-slot rows
--           that execute later (spec §6.1)
--   bursts  §4.1 primary cell, 25-slot sessionisation
--   wstate  per (mint, wallet) running buy_lam / buy_units / held_units, with
--           next_seq giving the end of each state's validity
--   parts   interval join: the one wstate row per wallet that is current at the
--           burst, keeping only wallets that hold tokens and have ever bought
--
-- ARITHMETIC.  All *amounts* stay exact integers (bigint sums of lamports and
-- token units).  The two ratios are DOUBLE, because exact rational OH does not
-- fit Trino's DECIMAL:
--
--   cb(w) = buy_lam / (buy_units * 1000)          -- SOL per token
--   P(t)  = vsol^2 / (x0_lam * y0_units * 1000)   -- SOL per token
--
--   Putting these over a common denominator per wallet gives
--     (vsol^2 * buy_units - buy_lam * x0_lam * y0_units)
--     / (x0_lam * y0_units * buy_units * 1000)
--   whose denominator needs ~44 significant digits (3e28 x 1e15).  Trino's
--   DECIMAL is capped at 38, and DECIMAL(p1,s1) * DECIMAL(p2,s2) ->
--   DECIMAL(p1+p2, s1+s2) fails analysis past that cap, so squaring a scaled
--   price overflows before the division even happens.  That is the exact
--   operator where an exact-decimal version breaks; the resulting float error is
--   measured against src/oh_reference.py rather than assumed.

WITH sel AS (
    SELECT mint,
           max(CAST(virtual_sol_reserves   AS bigint)) AS x0_lam,
           max(CAST(virtual_token_reserves AS bigint)) AS y0_units
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-06-01'
      AND evt_block_date <  DATE '2026-06-02'
      AND quote_mint = '11111111111111111111111111111111'
    GROUP BY mint
    -- stage 1 selects 20 tokens by the frozen mint-hash rule (config.py
    -- SAMPLE_SQL_FRACTION); stage 2 drops the ORDER BY / LIMIT entirely.
    ORDER BY from_base(substr(lower(to_hex(sha256(to_utf8(concat(
        'solana-flow-research/phase0:', mint))))), 1, 8), 16)
    LIMIT 20
),
ev AS (
    SELECT s.mint, s.x0_lam, s.y0_units,
           t.evt_block_slot AS slot,
           t.evt_tx_index   AS txi,
           coalesce(t.evt_outer_instruction_index, 0) * 64
             + coalesce(t.evt_inner_instruction_index, 0) AS ixi,
           t.user AS wallet,
           t.is_buy,
           CAST(t.sol_amount   AS bigint) AS lam,
           CAST(t.token_amount AS bigint) AS units,
           CAST(t.virtual_sol_reserves AS bigint) AS vsol
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN sel s ON t.mint = s.mint
    WHERE t.evt_block_date >= DATE '2026-06-01'
      AND t.evt_block_date <= DATE '2026-06-11'
      AND t.evt_block_time <  TIMESTAMP '2026-06-11 23:59:00'
      AND t.quote_mint = '11111111111111111111111111111111'
),
seqd AS (
    SELECT *, row_number() OVER (PARTITION BY mint ORDER BY slot, txi, ixi) AS seq
    FROM ev
),
flow AS (
    SELECT mint, seq, slot, txi, ixi, vsol, x0_lam, y0_units,
           sum(if(is_buy, lam, -lam)) OVER (
               PARTITION BY mint ORDER BY slot, txi, ixi
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
           - coalesce(sum(if(is_buy, lam, -lam)) OVER (
               PARTITION BY mint ORDER BY slot
               RANGE BETWEEN UNBOUNDED PRECEDING AND 5 PRECEDING), 0) AS nf5_lam
    FROM seqd
),
qual AS (
    SELECT mint, seq, slot, txi, ixi, vsol, x0_lam, y0_units,
           lag(slot) OVER (PARTITION BY mint ORDER BY slot, txi, ixi) AS prev_slot
    FROM flow
    WHERE CAST(nf5_lam AS double) / 1e9
          >= greatest(3.0, 0.10 * CAST(vsol AS double) / 1e9)
),
bursts AS (
    SELECT mint, seq, slot, txi, ixi, vsol, x0_lam, y0_units
    FROM qual
    WHERE prev_slot IS NULL OR slot - prev_slot > 25
),
wstate AS (
    SELECT mint, wallet, seq,
           sum(if(is_buy, lam,   0))     OVER (PARTITION BY mint, wallet
               ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS buy_lam,
           sum(if(is_buy, units, 0))     OVER (PARTITION BY mint, wallet
               ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS buy_units,
           sum(if(is_buy, units, -units)) OVER (PARTITION BY mint, wallet
               ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS held_units,
           lead(seq) OVER (PARTITION BY mint, wallet ORDER BY seq) AS next_seq
    FROM seqd
),
parts AS (
    SELECT b.mint, b.seq, b.slot, b.txi, b.ixi, b.vsol,
           CAST(b.vsol AS double) / 1e9 AS x_sol,
           (CAST(b.vsol AS double) * CAST(b.vsol AS double))
             / (CAST(b.x0_lam AS double) * CAST(b.y0_units AS double) * 1000.0) AS price,
           w.wallet,
           CAST(w.buy_lam AS double) / (CAST(w.buy_units AS double) * 1000.0) AS cb,
           CAST(w.held_units AS double) / 1e6 AS held_tokens
    FROM bursts b
    JOIN wstate w
      ON w.mint = b.mint
     AND w.seq <= b.seq
     AND (w.next_seq IS NULL OR w.next_seq > b.seq)
    WHERE w.held_units > 0
      AND w.buy_units  > 0
),
contrib AS (
    SELECT mint, seq, slot, txi, ixi, x_sol, price, wallet,
           held_tokens * (price - cb) AS oh_w
    FROM parts
    WHERE cb < price
),
ranked AS (
    SELECT *, row_number() OVER (PARTITION BY mint, seq ORDER BY oh_w DESC) AS rnk
    FROM contrib
)
SELECT mint, slot, txi, ixi, seq,
       x_sol,
       price,
       sum(oh_w)                                    AS oh,
       sum(oh_w) / x_sol                            AS oh_ratio,
       sum(if(rnk <= 3, oh_w, 0)) / nullif(sum(oh_w), 0) AS oh_conc,
       count(*)                                     AS n_wallets
FROM ranked
GROUP BY mint, slot, txi, ixi, seq, x_sol, price
ORDER BY mint, seq
