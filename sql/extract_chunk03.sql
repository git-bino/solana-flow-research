-- Phase 0 extract — dev chunk 03.  Executed query, verbatim.
-- Identical to sql/extract_dev.sql except the launch/event window literals.
--
-- Pre-registered rule (spec v1.3 §2.4, decisions.md 2026-08-17): 10-day chunks,
-- ONE chunk first, real credits measured, then extrapolate.  This is that chunk.
--
--   launch window  [2026-05-28 00:00, 2026-06-06 00:00)   9 days
--   event window   [2026-05-28 00:00, 2026-08-15 23:59)  80 days
--   quote_mint     SOL only (§2.2)
--   age cut        NONE, N = infinity (§2.2 v1.3)
--   other filters  none - no activity, volume, lifetime or migration filter
--
-- HOLDOUT: launches in [2026-07-12, 2026-08-08) cannot enter this query - the
-- launch filter ends 2026-06-06, 36 days before the holdout opens.  The `guard`
-- CTE below turns that from a structural property into a hard assertion: the
-- query FAILS rather than returning a row if any launch falls outside the window.
--
-- Cohort: tokens created 2026-06-01, SOL-quote, events to 2026-06-11 23:59 —
-- the same 1-day cohort every other measurement used.
--
-- Row set = the §4.1 primary cell (0.10x, 5-slot window, 25-slot
-- sessionisation), so the row count is comparable with burst_inventory.
-- qual_005 / qual_020 flag whether the SAME event also clears the other two
-- thresholds; that is NOT the same as independently sessionising each threshold
-- (§3d), and the report says so.
--
-- Windows are slot-based (spec v1.2).  Trailing flows are differences of prefix
-- sums so the window cuts AT the current row (spec §6.1); forward windows are
-- labels, where lookahead is the point.

WITH sel AS (
    SELECT mint,
           min(evt_block_time) AS created_at,
           max(CAST(virtual_sol_reserves   AS bigint)) AS x0_lam,
           max(CAST(virtual_token_reserves AS bigint)) AS y0_units,
           bool_or(is_mayhem_mode) AS mayhem_at_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-28'
      AND evt_block_date <  DATE '2026-06-06'
      -- FIX 9 (2026-08-18): the universe filter is the DECLARED initial reserve,
      -- not trade-side quote_mint.  Measured (docs/phase0_quote_filter_source.md):
      -- createevent.virtual_sol_reserves is present on 100% of creates, takes
      -- exactly two values, and separates the quote asset perfectly -- 229,192
      -- trade-confirmed SOL tokens all at 30000000000, 5,475 trade-confirmed USDC
      -- all at 4292000000, zero overlap.  It is readable at launch and needs no
      -- trade data, so it works across the 3-hour window on 2026-05-21 where USDC
      -- curves already existed with quote_mint still NULL.
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
guard AS (
    SELECT if(max(created_at) >= TIMESTAMP '2026-06-06 00:00:00'
              OR min(created_at) < TIMESTAMP '2026-05-28 00:00:00',
              CAST(fail('LAUNCH WINDOW GUARD: a token outside [2026-05-28, 2026-06-06)'
                        || ' entered the cohort') AS integer),
              0) AS ok
    FROM sel
),
ev AS (
    SELECT s.mint, s.created_at, s.x0_lam, s.y0_units, s.mayhem_at_launch,
           t.evt_block_time AS bt,
           t.evt_block_slot AS slot,
           t.evt_tx_index   AS txi,
           coalesce(t.evt_outer_instruction_index, 0) * 64
             + coalesce(t.evt_inner_instruction_index, 0) AS ixi,
           t.user AS wallet,
           t.is_buy,
           CAST(t.sol_amount   AS bigint) AS lam,
           CAST(t.token_amount AS bigint) AS units,
           CAST(t.virtual_sol_reserves AS bigint) AS vsol,
           coalesce(t.mayhem_mode, false) AS mayhem,
           t.quote_mint
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN sel s ON t.mint = s.mint
    WHERE t.evt_block_date >= DATE '2026-05-28'
      AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time <  TIMESTAMP '2026-08-15 23:59:00'
      -- No trade-side quote filter: the token is already restricted by the join to
      -- `sel`, and quote_mint is constant within a token (0 of 248,657 tokens had
      -- MIN <> MAX).  It is carried as a stratum column instead (§2.3).
),
seqd AS (
    SELECT *,
           row_number() OVER (PARTITION BY mint ORDER BY slot, txi, ixi) AS seq,
           if(is_buy, lam, -lam) AS signed_lam,
           CAST(vsol AS double) / 1e9 AS x_sol,
           CAST(lam  AS double) / 1e9 AS sol_abs
    FROM ev
),
flows AS (
    SELECT *,
           -- trailing net flow, prefix-sum difference: slot in (s-w, s], cut at this row
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 3 PRECEDING), 0)  AS nf3_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 5 PRECEDING), 0)  AS nf5_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 12 PRECEDING), 0) AS nf12_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0) AS nf25_lam,
           -- f3: distinct buyers over the trailing 12 slots.  count(DISTINCT) is
           -- not allowed as a window function in Trino, so the window collects
           -- the wallets and cardinality(array_distinct(...)) counts them.
           -- FIX 4 (2026-08-18): f8 / f9 rebuilt as prefix-sum differences.
           -- They used `RANGE BETWEEN 25 PRECEDING AND CURRENT ROW`, and with
           -- `ORDER BY slot` that frame treats every row sharing the current slot
           -- as a peer -- including trades that execute LATER in
           -- (tx_index, ix_index) order.  That is intra-slot lookahead (§6.1);
           -- measured on 88 rows, the peer rule reproduced the old f8 exactly
           -- (88/88) while the causal rule matched 26-28/88.
           --
           -- The correct window is slot in (s-25, s] AND key <= this row.  Both
           -- halves come free from the same construction f1 uses: the minuend is
           -- a ROWS frame in full key order, so it cuts AT this row; the
           -- subtrahend is a SUM over a RANGE frame ending at 25 PRECEDING, which
           -- is peer-deterministic because summing all rows with slot <= s-25 does
           -- not depend on their order.
           --
           -- CV and round_frac are expressible in sums, so nothing else is needed:
           --   CV = sqrt(Sx2/n - (Sx/n)^2) / (Sx/n),  round_frac = Sround / n.
           sum(sol_abs) OVER pfx
             - coalesce(sum(sol_abs) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0) AS sx_25,
           sum(sol_abs * sol_abs) OVER pfx
             - coalesce(sum(sol_abs * sol_abs) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0) AS sx2_25,
           sum(if(lam IN (100000000, 500000000, 1000000000), 1, 0)) OVER pfx
             - coalesce(sum(if(lam IN (100000000, 500000000, 1000000000), 1, 0)) OVER (
                 PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0) AS sround_25,
           count(*) OVER pfx
             - coalesce(count(*) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0) AS n_trades_25,
           -- forward labels (§4.2): lookahead is intended here
           -- FIX 6 (2026-08-18): the label boundary is the trigger ROW, not its slot.
           -- `RANGE 1 FOLLOWING ...` starts at the next SLOT, so it skipped trades
           -- sharing the trigger's slot that execute later -- trades `x_at_plus`
           -- could already see.  Mirror of the trailing construction: sum over
           -- everything with slot <= s+tau, minus the prefix through this row.
           -- The minuend is peer-deterministic (a SUM over all rows at slot <= s+tau);
           -- the subtrahend is a ROWS frame in full key order, so it cuts AT this row.
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN UNBOUNDED PRECEDING AND 5 FOLLOWING), 0)
             - sum(signed_lam) OVER pfx                        AS fwd_nf5_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN UNBOUNDED PRECEDING AND 12 FOLLOWING), 0)
             - sum(signed_lam) OVER pfx                        AS fwd_nf12_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN UNBOUNDED PRECEDING AND 37 FOLLOWING), 0)
             - sum(signed_lam) OVER pfx                        AS fwd_nf37_lam,
           -- x at t+tau: last observed reserve inside the forward window
           -- FIX 7: `last_value` over a RANGE frame picks an arbitrary peer when the
           -- final slot holds several trades (36/88 bursts in the parity sample).
           -- `max_by(vsol, seq)` names the tie-break explicitly: seq is unique in
           -- (slot, tx_index, ix_index) order, so this is the LAST row with
           -- slot <= s+tau -- the semantics decisions.md confirmed as correct.
           max_by(vsol, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 5 FOLLOWING)  AS vsol_p5,
           max_by(vsol, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 12 FOLLOWING) AS vsol_p12,
           max_by(vsol, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 37 FOLLOWING) AS vsol_p37,
           -- §5: V = flow landing during latency.  L1 = 1 slot, L2 = 1000ms
           -- ~ 2.5 slots (2 and 3 both kept), L3 = 3000ms ~ 7.5 slots (7 and 8).
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 1 FOLLOWING), 0) AS v_lat1_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 2 FOLLOWING), 0) AS v_lat2_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 3 FOLLOWING), 0) AS v_lat3_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 7 FOLLOWING), 0) AS v_lat7_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 8 FOLLOWING), 0) AS v_lat8_lam
    FROM seqd
    WINDOW pfx AS (PARTITION BY mint ORDER BY slot, txi, ixi
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
-- §4.3 / §3c: the first future slot at which the trailing 3-slot flow is no
-- longer positive.  One scalar reconstructs the whole hazard curve, provided
-- "still positive" is absorbing; the 75-value trajectory is measured separately.
deaths AS (
    SELECT *,
           min(if(nf3_lam <= 0, slot)) OVER (
               PARTITION BY mint ORDER BY slot, txi, ixi
               ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS death_slot,
           CAST(NULL AS double) AS traj_placeholder
    FROM flows
),
-- FIX 1 (2026-08-18): the trajectory is now slot-indexed and fixed length.
-- The previous `array_agg OVER (RANGE 1 FOLLOWING AND 75 FOLLOWING)` collected
-- one element per EVENT inside those slots (length median 28.3, max 788), so the
-- index carried no meaning.  Now: index a = 1..75 is the slot offset from the
-- burst, the value is net_flow_3slot at slot s+a, and a slot with no event
-- contributes 0.  Built by expanding sequence(1,75) per burst and LEFT JOINing
-- the per-slot table, so cardinality is exactly 75 on every row (asserted below).
--
-- Two conventions worth naming: within a slot holding several events the value is
-- the LAST one in (tx_index, ix_index) order (end-of-slot state), and an eventless
-- slot is 0 as specified -- note that the trailing 3-slot window evaluated at an
-- eventless slot would generally be non-zero, so this is the specified quantity
-- rather than the window's mathematical value.
-- FIX 3 (2026-08-18): nf3 on a dense slot grid, as a rolling 3-slot SUM.
-- The previous version took `max_by(nf3_lam, ...)` -- the trailing value carried
-- by the LAST EVENT in that slot -- and 0 when the slot held no event.  Wrong on
-- both counts: nf3(a) is the sum of flow over slots in (a-3, a], which is
-- non-zero whenever a-1 or a-2 traded even if slot a itself is empty.
--
-- So the per-slot table now holds the SUM of signed flow in each slot, and the
-- window is assembled on the dense grid as slot_flow(a) + slot_flow(a-1) +
-- slot_flow(a-2).  Written as three equi-joins rather than one range join
-- (`sf.slot > target - 3 AND sf.slot <= target`): a non-equi join over the
-- 14,300 x 75 grid becomes a nested loop, while equality joins stay hash joins.
--
-- Two variants, because §4.3 does not say whether the window at a = 1, 2 may
-- reach back past the burst slot:
--   nf3_traj_75_incl_pre  window spans (a-3, a] unconditionally
--   nf3_traj_75_excl_pre  only slots strictly after burst_slot contribute
-- Both are produced; which one is primary is not decided here.
slot_flow AS (
    SELECT mint, slot, sum(signed_lam) AS flow_lam
    FROM seqd
    GROUP BY mint, slot
),
qual AS (
    SELECT *,
           lag(slot) OVER (PARTITION BY mint ORDER BY slot, txi, ixi) AS prev_q_slot
    FROM deaths
    WHERE CAST(nf5_lam AS double) / 1e9 >= greatest(3.0, 0.10 * x_sol)
),
bursts AS (
    SELECT * FROM qual WHERE prev_q_slot IS NULL OR slot - prev_q_slot > 25
),
grid AS (
    SELECT b.mint, b.seq, b.slot AS burst_slot, off.a, b.slot + off.a AS target_slot
    FROM bursts b CROSS JOIN UNNEST(sequence(1, 75)) AS off(a)
),
grid_nf3 AS (
    SELECT g.mint, g.seq, g.a,
           coalesce(f0.flow_lam, 0) + coalesce(f1.flow_lam, 0)
             + coalesce(f2.flow_lam, 0)                                  AS nf3_incl_lam,
           if(g.target_slot     > g.burst_slot, coalesce(f0.flow_lam, 0), 0)
             + if(g.target_slot - 1 > g.burst_slot, coalesce(f1.flow_lam, 0), 0)
             + if(g.target_slot - 2 > g.burst_slot, coalesce(f2.flow_lam, 0), 0) AS nf3_excl_lam
    FROM grid g
    LEFT JOIN slot_flow f0 ON f0.mint = g.mint AND f0.slot = g.target_slot
    LEFT JOIN slot_flow f1 ON f1.mint = g.mint AND f1.slot = g.target_slot - 1
    LEFT JOIN slot_flow f2 ON f2.mint = g.mint AND f2.slot = g.target_slot - 2
),
traj AS (
    -- FIX 8 (2026-08-18): the excl_pre trajectory collapses to two scalars.
    -- nf3(a) spans slots (s+a-3, s+a], i.e. s+a-2 .. s+a, so every slot in it is
    -- strictly after the burst slot once a >= 3 and the two variants coincide
    -- there.  Verified on chunk 1 rather than argued: 133,877 rows x 73 elements
    -- = 9,773,021 comparisons, zero mismatches.  Only a = 1 and a = 2 carry
    -- information, and they differ from incl_pre on 100% of rows.
    SELECT mint, seq,
           array_agg(CAST(nf3_incl_lam AS double) / 1e9 ORDER BY a) AS nf3_traj_75_incl_pre,
           max(if(a = 1, CAST(nf3_excl_lam AS double) / 1e9)) AS nf3_excl_pre_1,
           max(if(a = 2, CAST(nf3_excl_lam AS double) / 1e9)) AS nf3_excl_pre_2,
           min(if(nf3_incl_lam <= 0, a)) AS death_age_incl,
           min(if(nf3_excl_lam <= 0, a)) AS death_age_excl,
           count_if(nf3_incl_lam <> 0)   AS nonzero_incl,
           count_if(nf3_excl_lam <> 0)   AS nonzero_excl
    FROM grid_nf3
    GROUP BY mint, seq
),
-- FIX 5 (2026-08-18): f3 rebuilt as a join, and the NULL buyer removed.
-- Distinct counting is not additive, so the prefix-sum trick that fixes f8/f9
-- cannot express it.  Instead each burst joins back to its own token's events
-- under `e.seq <= b.seq` -- seq is row_number over (slot, tx_index, ix_index),
-- so that single predicate IS the causal cut, peers included or excluded exactly
-- as they should be -- plus `e.slot > b.slot - 12` for the window.
-- Only burst rows need f3, so the join is bounded by (bursts x window), not by
-- (events x events).
-- The NULL defect disappears with it: the old
-- `cardinality(array_distinct(array_agg(if(is_buy, wallet)) OVER ...))` kept the
-- NULL that `if(is_buy, wallet)` emits for every sell and counted it as a buyer,
-- inflating n_buyers by exactly 1 whenever the window held a sell.  Here only
-- buys enter the join at all.
-- FIX 5b (2026-08-18): f3 via per-slot buyer sets + equi-joins.
-- The first correct version joined bursts to events on `e.seq <= b.seq AND
-- e.slot > b.slot - 12`.  Two inequalities give Trino no join key, so it
-- degenerates to a nested loop: measured at 8.844 credits / 188s on 200 tokens,
-- against 1.075 / 7.7s before the fix.  Correct but unaffordable at 90 days.
--
-- This version keeps the same semantics and restores equality joins.  Buyers are
-- collected once per (mint, slot); the window (s-12, s] is then slots s-11..s-1,
-- reached by expanding sequence(1,11) and joining on slot equality, plus the
-- burst's own slot handled separately so the intra-slot cut `e.seq <= b.seq` is
-- applied exactly where it matters -- and only there, over a single slot.
-- OPTIMISATION (2026-08-18): build buyer sets only for the slots a burst can
-- see.  Measured on the 1-day cohort: the unrestricted version built 759,387
-- (mint, slot) buyer arrays where only 29,725 are ever probed -- 25.5x more rows
-- than needed, 96.1% of the work discarded.  That is the cause of the 22.7s ->
-- 116s regression the previous round measured.  Semantics are unchanged; the
-- regression test compares f3 element by element across the change.
needed_slots AS (
    SELECT DISTINCT b.mint, b.slot - off.k AS slot
    FROM bursts b CROSS JOIN UNNEST(sequence(0, 12)) AS off(k)
),
slot_buyers AS (
    SELECT e.mint, e.slot, array_agg(DISTINCT e.wallet) AS buyers
    FROM seqd e
    JOIN needed_slots n ON n.mint = e.mint AND n.slot = e.slot
    WHERE e.is_buy
    GROUP BY e.mint, e.slot
),
f3_prior AS (
    SELECT b.mint, b.seq,
           array_distinct(flatten(array_agg(coalesce(sb.buyers, ARRAY[])))) AS buyers
    FROM bursts b
    CROSS JOIN UNNEST(sequence(1, 11)) AS off(k)
    LEFT JOIN slot_buyers sb ON sb.mint = b.mint AND sb.slot = b.slot - off.k
    GROUP BY b.mint, b.seq
),
f3_same AS (
    SELECT b.mint, b.seq, array_agg(DISTINCT e.wallet) AS buyers
    FROM bursts b
    JOIN seqd e ON e.mint = b.mint AND e.slot = b.slot AND e.seq <= b.seq AND e.is_buy
    GROUP BY b.mint, b.seq
),
f3 AS (
    SELECT p.mint, p.seq,
           cardinality(array_distinct(
               p.buyers || coalesce(sm.buyers, ARRAY[]))) AS n_buyers_12slot
    FROM f3_prior p
    LEFT JOIN f3_same sm ON sm.mint = p.mint AND sm.seq = p.seq
),
wstate AS (
    SELECT mint, wallet, seq,
           sum(if(is_buy, lam,   0))      OVER w AS buy_lam,
           sum(if(is_buy, units, 0))      OVER w AS buy_units,
           sum(if(is_buy, units, -units)) OVER w AS held_units,
           lead(seq) OVER (PARTITION BY mint, wallet ORDER BY seq) AS next_seq
    FROM seqd
    WINDOW w AS (PARTITION BY mint, wallet ORDER BY seq
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
contrib AS (
    SELECT b.mint, b.seq,
           w.wallet,
           (CAST(w.held_units AS double) / 1e6)
             * ((CAST(b.vsol AS double) * CAST(b.vsol AS double))
                  / (CAST(b.x0_lam AS double) * CAST(b.y0_units AS double) * 1000.0)
                - CAST(w.buy_lam AS double) / (CAST(w.buy_units AS double) * 1000.0)) AS oh_w
    FROM bursts b
    JOIN wstate w
      ON w.mint = b.mint AND w.seq <= b.seq
     AND (w.next_seq IS NULL OR w.next_seq > b.seq)
    WHERE w.held_units > 0 AND w.buy_units > 0
      AND CAST(w.buy_lam AS double) / (CAST(w.buy_units AS double) * 1000.0)
          < (CAST(b.vsol AS double) * CAST(b.vsol AS double))
            / (CAST(b.x0_lam AS double) * CAST(b.y0_units AS double) * 1000.0)
),
oh AS (
    SELECT mint, seq,
           sum(oh_w) AS oh,
           sum(if(rnk <= 3, oh_w, 0)) AS oh_top3,
           count(*) AS oh_n_wallets
    FROM (SELECT *, row_number() OVER (PARTITION BY mint, seq ORDER BY oh_w DESC) AS rnk
          FROM contrib)
    GROUP BY mint, seq
)
SELECT
    -- identity and context
    b.mint                                              AS token_mint,
    b.slot,
    b.txi                                               AS tx_index,
    b.ixi                                               AS ix_index,
    b.bt                                                AS block_time,
    b.seq                                               AS event_seq,
    b.created_at                                        AS token_created_at,
    date_diff('second', b.created_at, b.bt) / 60.0      AS age_min,
    date_trunc('minute', b.bt)                          AS minute_bucket,
    b.mayhem, b.mayhem_at_launch,
    b.quote_mint,
    b.x0_lam, b.y0_units,
    b.wallet                                            AS trigger_wallet,
    b.is_buy                                            AS trigger_is_buy,
    CAST(b.lam AS double) / 1e9                         AS trigger_sol,
    CAST(b.units AS double) / 1e6                       AS trigger_tokens,
    -- f1, f2
    CAST(b.nf3_lam  AS double) / 1e9                    AS net_flow_3slot,
    CAST(b.nf5_lam  AS double) / 1e9                    AS net_flow_5slot,
    CAST(b.nf12_lam AS double) / 1e9                    AS net_flow_12slot,
    CAST(b.nf25_lam AS double) / 1e9                    AS net_flow_25slot,
    CAST(b.nf5_lam AS double)
      / nullif(CAST(b.nf25_lam AS double) / 5.0, 0)     AS accel,
    -- f3, f4, f5, f6
    coalesce(f3.n_buyers_12slot, 0)                     AS n_buyers_12slot,
    b.x_sol                                             AS depth_x,
    (b.x_sol - 30.0) / 85.0                             AS curve_progress,
    0                                                   AS burst_age_slot,
    -- f7, f7b
    coalesce(o.oh, 0)                                   AS oh,
    coalesce(o.oh, 0) / b.x_sol                         AS oh_ratio,
    if(coalesce(o.oh, 0) > 0, o.oh_top3 / o.oh, 0)       AS oh_conc,  -- FIX 2: §1.2 says 0 <= OH_conc <= 1; with OH = 0 concentration is
                                                            -- undefined, so 0, matching src/oh_reference.py
    coalesce(o.oh_n_wallets, 0)                         AS oh_n_wallets,
    -- f8, f9
    sqrt(greatest(b.sx2_25 / b.n_trades_25
                  - power(b.sx_25 / b.n_trades_25, 2), 0))
      / nullif(b.sx_25 / b.n_trades_25, 0)              AS size_cv_25slot,
    CAST(b.sround_25 AS double) / b.n_trades_25         AS round_frac_25slot,
    b.n_trades_25                                       AS n_trades_25slot,
    -- §3d threshold flags on this same event (not independently sessionised)
    CAST(b.nf5_lam AS double)/1e9 >= greatest(3.0, 0.05 * b.x_sol) AS qual_005,
    CAST(b.nf5_lam AS double)/1e9 >= greatest(3.0, 0.20 * b.x_sol) AS qual_020,
    -- §4.2 forward labels
    CAST(b.fwd_nf5_lam  AS double) / 1e9                AS fwd_net_flow_5slot,
    CAST(b.fwd_nf12_lam AS double) / 1e9                AS fwd_net_flow_12slot,
    CAST(b.fwd_nf37_lam AS double) / 1e9                AS fwd_net_flow_37slot,
    CAST(b.vsol_p5  AS double) / 1e9                    AS x_at_plus5,
    CAST(b.vsol_p12 AS double) / 1e9                    AS x_at_plus12,
    CAST(b.vsol_p37 AS double) / 1e9                    AS x_at_plus37,
    -- §5 latency flow V
    CAST(b.v_lat1_lam AS double) / 1e9                  AS v_latency_1slot,
    CAST(b.v_lat2_lam AS double) / 1e9                  AS v_latency_2slot,
    CAST(b.v_lat3_lam AS double) / 1e9                  AS v_latency_3slot,
    CAST(b.v_lat7_lam AS double) / 1e9                  AS v_latency_7slot,
    CAST(b.v_lat8_lam AS double) / 1e9                  AS v_latency_8slot,
    -- §4.3 hazard
    b.death_slot - b.slot                               AS death_age_slot,
    b.death_slot IS NULL                                AS hazard_censored,
    -- doubtful: only needed if "still positive" is not absorbing
    tr.nf3_traj_75_incl_pre,
    tr.nf3_excl_pre_1,
    tr.nf3_excl_pre_2,
    cardinality(tr.nf3_traj_75_incl_pre) AS traj_len,
    tr.death_age_incl,
    tr.death_age_excl,
    tr.death_age_incl IS NULL AS censored_incl,
    tr.death_age_excl IS NULL AS censored_excl,
    tr.nonzero_incl,
    tr.nonzero_excl,
    g.ok AS launch_window_guard
FROM bursts b
CROSS JOIN guard g
LEFT JOIN oh o ON o.mint = b.mint AND o.seq = b.seq
LEFT JOIN traj tr ON tr.mint = b.mint AND tr.seq = b.seq
LEFT JOIN f3 ON f3.mint = b.mint AND f3.seq = b.seq
ORDER BY b.mint, b.seq
