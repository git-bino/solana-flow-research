-- Phase 0 extract, v2.  NOT RUN: written while the Dune API returns 402.
--
-- Rewrite of sql/extract_chunk02.sql carrying every fix the external audit
-- produced (decisions.md, 2026-08-19).  Costs, runtime and row width are
-- DELIBERATELY not estimated here: the transfer join has never been measured
-- (probe A2 was blocked), so any number would be invented.
--
--   launch window  [{{LAUNCH_FROM}}, {{LAUNCH_TO}})
--   event window   [{{LAUNCH_FROM}}, {{EVENT_TO}} 23:59)
--   universe       createevent.virtual_sol_reserves = 30000000000
--   age cut        NONE, N = infinity
--   transfers      {{INCLUDE_TRANSFERS}}  ('true' | 'false')
--
-- Every timestamp literal is written with an explicit UTC zone (fix 7).  The
-- ClickHouse side learned this the hard way: a server in Asia/Ulaanbaatar shifted
-- bare timestamps by +8h (docs/phase0_clickhouse_load.md).
--
-- ---------------------------------------------------------------------------
-- THE SEVEN FIXES
--
-- 1. LABEL BOUNDARY.  Forward windows are (s, s+tau] again -- `RANGE BETWEEN 1
--    FOLLOWING`.  The 2026-08-17 change to a row boundary is REVERTED: it let a
--    label count trades that shared the trigger's slot, which the trigger's own
--    features cannot see.  Feature windows are unchanged: `<= trigger row`, so a
--    trade earlier in the same slot still counts as history.
--    `fwd_price_ret` prices off the END of slot s, not off the trigger row.
--
-- 2. ORDERING KEY.  `outer*64 + inner` is gone.  Ordering, windows and joins all
--    use the raw pair, and both columns are exported.  Probe C measured zero
--    collisions on 19,088,528 events with inner maxing at 51 -- but 51 is not far
--    from 64, and that was one 9-day window.
--
-- 3. TRANSFER-AWARE LEDGER.  See the `xf`, `pos` and `wstate` CTEs.  Two readings
--    of the receiving side are computed side by side and NEITHER is chosen.
--
-- 4. COST BASIS RESET.  A wallet that goes flat starts a new basis.  The old
--    all-history average survives as `cb_legacy`.
--
-- 5. BUY FEE.  The basis numerator adds `fee + creator_fee`.  The net-only
--    version survives as `cb_net`.
--
-- 6. y(t).  `virtual_token_reserves` is carried, `P(t) = x/y`, and the old
--    `x^2/(x0*y0)` survives as `p_launch` so the mayhem gap stays measurable.
--
-- 7. UTC everywhere.
-- ---------------------------------------------------------------------------

WITH sel AS (
    SELECT mint,
           min(evt_block_time) AS created_at,
           max(CAST(virtual_sol_reserves   AS bigint)) AS x0_lam,
           max(CAST(virtual_token_reserves AS bigint)) AS y0_units,
           bool_or(is_mayhem_mode) AS mayhem_at_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '{{LAUNCH_FROM}}'
      AND evt_block_date <  DATE '{{LAUNCH_TO}}'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
guard AS (
    SELECT if(max(created_at) >= TIMESTAMP '{{LAUNCH_TO}} 00:00:00 UTC'
              OR min(created_at) < TIMESTAMP '{{LAUNCH_FROM}} 00:00:00 UTC',
              CAST(fail('LAUNCH WINDOW GUARD: a token outside the window entered '
                        || 'the cohort') AS integer),
              0) AS ok
    FROM sel
),
-- Trades.  `oix`/`iix` are the RAW instruction indices (fix 2); nothing packs them.
ev AS (
    SELECT s.mint, s.created_at, s.x0_lam, s.y0_units, s.mayhem_at_launch,
           t.evt_block_time AS bt,
           t.evt_block_slot AS slot,
           t.evt_tx_index   AS txi,
           coalesce(t.evt_outer_instruction_index, 0) AS oix,
           coalesce(t.evt_inner_instruction_index, 0) AS iix,
           t.user AS wallet,
           t.is_buy,
           CAST(t.sol_amount   AS bigint) AS lam,
           CAST(t.token_amount AS bigint) AS units,
           CAST(t.virtual_sol_reserves   AS bigint) AS vsol,
           CAST(t.virtual_token_reserves AS bigint) AS vtok,       -- fix 6
           CAST(coalesce(t.fee, 0)         AS bigint) AS fee_lam,  -- fix 5
           CAST(coalesce(t.creator_fee, 0) AS bigint) AS creator_fee_lam,
           coalesce(t.mayhem_mode, false) AS mayhem,
           t.quote_mint
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN sel s ON t.mint = s.mint
    WHERE t.evt_block_date >= DATE '{{LAUNCH_FROM}}'
      AND t.evt_block_date <= DATE '{{EVENT_TO}}'
      AND t.evt_block_time <  TIMESTAMP '{{EVENT_TO}} 23:59:00 UTC'
),
-- Fix 3.  SPL transfers on the same tokens, over the same window.
--
-- EXCLUSION RULE, stated explicitly: a pump.fun trade itself moves SPL tokens, so
-- the curve's own legs appear in this table.  They are removed by
-- `outer_executing_account <> '6EF8...F6P'` -- the account that INVOKED the
-- transfer, which for a curve trade is the pump.fun program.  Legs invoked by
-- other AMMs and routers are left in on purpose: they are real movements of a
-- holder's balance away from the curve, and dropping them would understate the
-- inventory the ledger is blind to.  `action = 'transfer'` drops mints and burns.
--
-- The whole CTE is gated on {{INCLUDE_TRANSFERS}}.  With 'false' it yields no
-- rows and every downstream aggregate collapses to the v1 ledger, which is what
-- the parity test asserts.  COST UNMEASURED: probe A2 never ran.
xf AS (
    SELECT x.token_mint_address AS mint,
           x.block_slot AS slot,
           x.tx_index   AS txi,
           coalesce(x.outer_instruction_index, 0) AS oix,
           coalesce(x.inner_instruction_index, 0) AS iix,
           x.from_owner,
           x.to_owner,
           CAST(x.amount AS bigint) AS units
    FROM tokens_solana.spl_token_transfers x
    JOIN sel s ON x.token_mint_address = s.mint
    WHERE '{{INCLUDE_TRANSFERS}}' = 'true'
      AND x.block_date >= DATE '{{LAUNCH_FROM}}'
      AND x.block_date <= DATE '{{EVENT_TO}}'
      AND x.block_time <  TIMESTAMP '{{EVENT_TO}} 23:59:00 UTC'
      AND x.action = 'transfer'
      AND x.outer_executing_account <> '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
      AND x.from_owner <> x.to_owner
),
seqd AS (
    SELECT *,
           row_number() OVER (PARTITION BY mint ORDER BY slot, txi, oix, iix) AS seq,
           if(is_buy, lam, -lam) AS signed_lam,
           CAST(vsol AS double) / 1e9 AS x_sol,
           CAST(vtok AS double) / 1e6 AS y_tok,
           min(slot) OVER (PARTITION BY mint) AS first_slot
    FROM ev
),
-- =====================================================================
-- Features (trailing, <= this row) and labels (forward, slot > s).
-- =====================================================================
flows AS (
    SELECT *,
           -- trailing flows: prefix through THIS row minus the prefix that ended
           -- w slots ago.  The minuend is a ROWS frame in full key order, so a
           -- trade later in the same slot is excluded; the subtrahend is a RANGE
           -- frame, so the window edge lands on a slot boundary.
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 4 PRECEDING), 0)  AS nf5_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 3 PRECEDING), 0)  AS nf3_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 12 PRECEDING), 0) AS nf12_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0) AS nf25_lam,
           count(*) OVER pfx
             - coalesce(count(*) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0)  AS n_trades_25,

           -- f8 / f9 inputs.  Still prefix-sum differences (the 2026-08-18 fix):
           -- a RANGE frame ending at CURRENT ROW would swallow same-slot
           -- successors, which §6.1 forbids.  `lam` is squared in double because
           -- (1e11)^2 overflows bigint.
           sum(CAST(lam AS double)) OVER pfx
             - coalesce(sum(CAST(lam AS double)) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0)  AS s1_25,
           sum(CAST(lam AS double) * CAST(lam AS double)) OVER pfx
             - coalesce(sum(CAST(lam AS double) * CAST(lam AS double)) OVER (
                 PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0)  AS s2_25,
           sum(if(lam IN (100000000, 500000000, 1000000000), 1, 0)) OVER pfx
             - coalesce(sum(if(lam IN (100000000, 500000000, 1000000000), 1, 0)) OVER (
                 PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0)  AS rnd_25,

           -- FIX 1: forward labels start at the NEXT SLOT.  `1 FOLLOWING` is the
           -- correct boundary and is restored; the row-boundary version counted
           -- same-slot successors the trigger's own features are blind to.
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 5 FOLLOWING), 0)  AS fwd_nf5_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 12 FOLLOWING), 0) AS fwd_nf12_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 37 FOLLOWING), 0) AS fwd_nf37_lam,

           -- FIX 1, price side: the baseline is the END of slot s, so a trade
           -- later in slot s moves the baseline but never the label's window.
           -- `max_by(.., seq)` over CURRENT ROW..CURRENT ROW is the last peer in s.
           max_by(vsol, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND CURRENT ROW) AS vsol_end_s,
           max_by(vtok, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND CURRENT ROW) AS vtok_end_s,
           -- x and y at the end of the forward window.  When (s, s+tau] is empty
           -- these fall back to the end of slot s, which is the intended base.
           max_by(vsol, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 5 FOLLOWING)  AS vsol_p5,
           max_by(vtok, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 5 FOLLOWING)  AS vtok_p5,
           max_by(vsol, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 12 FOLLOWING) AS vsol_p12,
           max_by(vtok, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 12 FOLLOWING) AS vtok_p12,
           max_by(vsol, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 37 FOLLOWING) AS vsol_p37,
           max_by(vtok, seq) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 37 FOLLOWING) AS vtok_p37,

           -- §5 latency flows, unchanged: these were already slot-based.
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
    WINDOW pfx AS (PARTITION BY mint ORDER BY slot, txi, oix, iix
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
deaths AS (
    SELECT *,
           min(if(nf3_lam <= 0, slot)) OVER (
               PARTITION BY mint ORDER BY slot, txi, oix, iix
               ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS death_slot
    FROM flows
),
slot_flow AS (
    SELECT mint, slot, sum(signed_lam) AS flow_lam
    FROM seqd GROUP BY mint, slot
),
qual AS (
    SELECT *, lag(slot) OVER (PARTITION BY mint ORDER BY slot, txi, oix, iix)
                  AS prev_q_slot
    FROM deaths
    WHERE CAST(nf5_lam AS double) / 1e9 >= greatest(3.0, 0.10 * x_sol)
),
bursts AS (
    SELECT * FROM qual WHERE prev_q_slot IS NULL OR slot - prev_q_slot > 25
),
-- =====================================================================
-- §4.3 trajectory, unchanged in construction: a = 1..75 is the slot offset.
-- =====================================================================
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
             + if(g.target_slot - 2 > g.burst_slot, coalesce(f2.flow_lam, 0), 0)
                                                                          AS nf3_excl_lam
    FROM grid g
    LEFT JOIN slot_flow f0 ON f0.mint = g.mint AND f0.slot = g.target_slot
    LEFT JOIN slot_flow f1 ON f1.mint = g.mint AND f1.slot = g.target_slot - 1
    LEFT JOIN slot_flow f2 ON f2.mint = g.mint AND f2.slot = g.target_slot - 2
),
traj AS (
    SELECT mint, seq,
           array_agg(CAST(nf3_incl_lam AS double) / 1e9 ORDER BY a) AS nf3_traj_75_incl_pre,
           max(if(a = 1, CAST(nf3_excl_lam AS double) / 1e9)) AS nf3_excl_pre_1,
           max(if(a = 2, CAST(nf3_excl_lam AS double) / 1e9)) AS nf3_excl_pre_2,
           count(*) AS traj_len,
           count_if(nf3_incl_lam <> 0) AS nonzero_incl,
           count_if(nf3_excl_lam <> 0) AS nonzero_excl,
           min(if(nf3_incl_lam <= 0, a)) AS death_age_incl,
           min(if(nf3_excl_lam <= 0, a)) AS death_age_excl
    FROM grid_nf3 GROUP BY mint, seq
),
-- =====================================================================
-- f3, unchanged: per-slot buyer sets joined on equality, narrowed to the slots
-- a burst can actually reach.
-- =====================================================================
needed_slots AS (
    SELECT DISTINCT b.mint, b.slot - off.k AS slot
    FROM bursts b CROSS JOIN UNNEST(sequence(0, 12)) AS off(k)
),
slot_buyers AS (
    SELECT e.mint, e.slot, array_agg(DISTINCT e.wallet) AS buyers
    FROM seqd e JOIN needed_slots n ON n.mint = e.mint AND n.slot = e.slot
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
    -- the trigger's own slot, restricted to rows at or before the trigger
    SELECT b.mint, b.seq, array_agg(DISTINCT e.wallet) AS buyers
    FROM bursts b
    JOIN seqd e ON e.mint = b.mint AND e.slot = b.slot AND e.is_buy
               AND (e.slot, e.txi, e.oix, e.iix) <= (b.slot, b.txi, b.oix, b.iix)
    GROUP BY b.mint, b.seq
),
f3 AS (
    SELECT p.mint, p.seq,
           cardinality(array_distinct(p.buyers || coalesce(sm.buyers, ARRAY[])))
             AS n_buyers_12slot
    FROM f3_prior p
    LEFT JOIN f3_same sm ON sm.mint = p.mint AND sm.seq = p.seq
),
-- =====================================================================
-- LEDGER (fixes 3, 4, 5).  Trades and transfers become one position stream.
-- =====================================================================
--
-- `kind` orders a transfer against a trade that shares an instruction slot:
-- 0 = trade, 1 = transfer out, 2 = transfer in.  Out before in so that a wallet
-- forwarding what it just received cannot go transiently negative on the pair.
pos AS (
    SELECT mint, wallet, slot, txi, oix, iix, 0 AS kind,
           if(is_buy, units, -units)                      AS d_units,
           if(is_buy, units, 0)                           AS d_units_buys,
           0                                              AS d_units_xf,
           if(is_buy, lam + fee_lam + creator_fee_lam, 0) AS d_lam_gross,  -- fix 5
           if(is_buy, lam, 0)                             AS d_lam_net,
           if(is_buy, units, 0)                           AS d_basis_units,
           CAST(NULL AS varchar)                          AS counterparty
    FROM ev
    UNION ALL
    SELECT mint, from_owner AS wallet, slot, txi, oix, iix, 1,
           -units, 0, 0, 0, 0, 0, to_owner FROM xf
    UNION ALL
    SELECT mint, to_owner AS wallet, slot, txi, oix, iix, 2,
           units, 0, units, 0, 0, 0, from_owner FROM xf
),
run AS (
    SELECT *,
           sum(d_units)      OVER w AS held,
           sum(d_units_buys) OVER w AS cum_buy_units,
           sum(d_units_xf)   OVER w AS cum_xf_units
    FROM pos
    WINDOW w AS (PARTITION BY mint, wallet ORDER BY slot, txi, oix, iix, kind
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
-- FIX 4: the basis restarts every time the balance reaches or crosses zero.
-- A running count of prior flat points is a segment id, and summing the basis
-- inputs within a segment is exactly "since the wallet was last flat".
segd AS (
    SELECT *,
           coalesce(sum(if(held <= 0, 1, 0)) OVER (
               PARTITION BY mint, wallet ORDER BY slot, txi, oix, iix, kind
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS seg_id
    FROM run
),
wstate AS (
    SELECT mint, wallet, slot, txi, oix, iix, kind, held,
           greatest(cum_buy_units - greatest(-1 * least(held - cum_buy_units
                                                        - cum_xf_units, 0), 0), 0)
                                                        AS held_from_buys_approx,
           cum_xf_units,
           -- fix 4 + 5: four bases, so every combination stays measurable
           sum(d_lam_gross)   OVER seg AS seg_lam_gross,
           sum(d_basis_units) OVER seg AS seg_units,
           sum(d_lam_net)     OVER seg AS seg_lam_net,
           sum(d_lam_gross)   OVER allh AS all_lam_gross,
           sum(d_basis_units) OVER allh AS all_units,
           sum(d_lam_net)     OVER allh AS all_lam_net,
           lead(ROW(slot, txi, oix, iix, kind)) OVER allh AS next_key
    FROM segd
    WINDOW seg  AS (PARTITION BY mint, wallet, seg_id ORDER BY slot, txi, oix, iix, kind
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
           allh AS (PARTITION BY mint, wallet ORDER BY slot, txi, oix, iix, kind
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
-- FIX 3, variant (b): the recipient inherits the sender's basis.
--
-- ONE HOP ONLY.  The sender's basis is taken from its BUY history, not from a
-- basis that may itself contain inherited tokens: the full version is a fixpoint
-- over the transfer graph and Trino cannot express it.  src/oh_reference.py's
-- Python path DOES propagate chains, so the two diverge wherever a transferred
-- token is transferred again.  The size of that divergence is UNMEASURED.
xf_basis AS (
    SELECT x.mint, x.slot, x.txi, x.oix, x.iix, x.to_owner, x.units,
           max_by(CAST(w.seg_lam_gross AS double)
                  / nullif(CAST(w.seg_units AS double) * 1000.0, 0),
                  (w.slot, w.txi, w.oix, w.iix)) AS sender_cb
    FROM xf x
    LEFT JOIN wstate w
      ON w.mint = x.mint AND w.wallet = x.from_owner AND w.kind = 0
     AND (w.slot, w.txi, w.oix, w.iix) <= (x.slot, x.txi, x.oix, x.iix)
    GROUP BY x.mint, x.slot, x.txi, x.oix, x.iix, x.to_owner, x.units
),
inherited AS (
    SELECT mint, to_owner AS wallet, slot, txi, oix, iix,
           units, coalesce(sender_cb, 0.0) * CAST(units AS double) AS inherited_value
    FROM xf_basis
),
-- The wallet state each burst sees: the last position row at or before it.
wat AS (
    SELECT b.mint, b.seq, w.wallet, w.held, w.held_from_buys_approx, w.cum_xf_units,
           w.seg_lam_gross, w.seg_units, w.seg_lam_net,
           w.all_lam_gross, w.all_units, w.all_lam_net,
           coalesce(inh.value_to_here, 0.0) AS inherited_value,
           coalesce(inh.units_to_here, 0)   AS inherited_units
    FROM bursts b
    JOIN wstate w
      ON w.mint = b.mint
     AND (w.slot, w.txi, w.oix, w.iix) <= (b.slot, b.txi, b.oix, b.iix)
     AND (w.next_key IS NULL
          OR w.next_key > ROW(b.slot, b.txi, b.oix, b.iix, 2))
    LEFT JOIN (
        SELECT i.mint, i.wallet, bb.seq,
               sum(i.inherited_value) AS value_to_here,
               sum(i.units)           AS units_to_here
        FROM inherited i
        JOIN bursts bb ON bb.mint = i.mint
         AND (i.slot, i.txi, i.oix, i.iix) <= (bb.slot, bb.txi, bb.oix, bb.iix)
        GROUP BY i.mint, i.wallet, bb.seq
    ) inh ON inh.mint = w.mint AND inh.wallet = w.wallet AND inh.seq = b.seq
),
-- =====================================================================
-- OH.  Four price/basis combinations are NOT emitted; the primary basis is
-- (reset + gross) and the primary price is x/y.  What IS emitted twice is the
-- TRANSFER variant, because the brief forbids choosing between (a) and (b).
-- =====================================================================
contrib AS (
    SELECT b.mint, b.seq, w.wallet,
           -- price at the trigger row (fix 6)
           (CAST(b.vsol AS double) / 1e9) / (CAST(b.vtok AS double) / 1e6) AS p_inst,
           -- variant (a): only tokens the wallet BOUGHT are priced
           CAST(w.held_from_buys_approx AS double) / 1e6 AS units_a,
           -- variant (b): everything held, with the inherited value in the basis
           CAST(greatest(w.held, 0) AS double) / 1e6     AS units_b,
           CAST(w.seg_lam_gross AS double)
             / nullif(CAST(w.seg_units AS double) * 1000.0, 0)             AS cb_a,
           (CAST(w.seg_lam_gross AS double) / 1000.0 + w.inherited_value)
             / nullif(CAST(w.seg_units + w.inherited_units AS double), 0)  AS cb_b
    FROM bursts b JOIN wat w ON w.mint = b.mint AND w.seq = b.seq
),
oh AS (
    SELECT mint, seq,
           sum(if(cb_a IS NOT NULL AND cb_a < p_inst AND units_a > 0,
                  units_a * (p_inst - cb_a), 0))                       AS oh_a,
           sum(if(cb_b IS NOT NULL AND cb_b < p_inst AND units_b > 0,
                  units_b * (p_inst - cb_b), 0))                       AS oh_b,
           count_if(cb_a IS NOT NULL AND cb_a < p_inst AND units_a > 0) AS oh_n_wallets_a,
           count_if(cb_b IS NOT NULL AND cb_b < p_inst AND units_b > 0) AS oh_n_wallets_b,
           sum(if(rnk_a <= 3 AND cb_a IS NOT NULL AND cb_a < p_inst AND units_a > 0,
                  units_a * (p_inst - cb_a), 0))                       AS oh_top3_a,
           sum(if(rnk_b <= 3 AND cb_b IS NOT NULL AND cb_b < p_inst AND units_b > 0,
                  units_b * (p_inst - cb_b), 0))                       AS oh_top3_b
    FROM (
        SELECT *,
               row_number() OVER (PARTITION BY mint, seq ORDER BY
                   if(cb_a IS NOT NULL AND cb_a < p_inst, units_a * (p_inst - cb_a), 0)
                   DESC) AS rnk_a,
               row_number() OVER (PARTITION BY mint, seq ORDER BY
                   if(cb_b IS NOT NULL AND cb_b < p_inst, units_b * (p_inst - cb_b), 0)
                   DESC) AS rnk_b
        FROM contrib
    )
    GROUP BY mint, seq
),
-- The four cost-basis conventions, aggregated per burst so they stay comparable
-- without exporting a row per wallet.  Weighted by the units each wallet holds.
cb_variants AS (
    SELECT b.mint, b.seq,
           sum(CAST(w.seg_lam_gross AS double)) / nullif(sum(CAST(w.seg_units AS double)) * 1000.0, 0) AS cb_reset_gross,
           sum(CAST(w.seg_lam_net   AS double)) / nullif(sum(CAST(w.seg_units AS double)) * 1000.0, 0) AS cb_net,
           sum(CAST(w.all_lam_gross AS double)) / nullif(sum(CAST(w.all_units AS double)) * 1000.0, 0) AS cb_legacy,
           sum(greatest(w.held_from_buys_approx, 0))                                                   AS held_from_buys,
           sum(greatest(w.cum_xf_units, 0))                                                            AS held_from_transfers
    FROM bursts b JOIN wat w ON w.mint = b.mint AND w.seq = b.seq
    GROUP BY b.mint, b.seq
)
SELECT
    -- identity and ordering (fix 2: the raw pair, no packing)
    b.mint                                              AS token_mint,
    b.slot,
    b.txi                                               AS tx_index,
    b.oix                                               AS outer_ix_index,
    b.iix                                               AS inner_ix_index,
    b.seq                                               AS event_seq,
    b.bt                                                AS block_time,
    date_trunc('minute', b.bt)                          AS minute_bucket,
    b.created_at                                        AS token_created_at,
    date_diff('second', b.created_at, b.bt) / 60.0      AS age_min,
    b.quote_mint,
    b.mayhem,
    b.mayhem_at_launch,
    b.x0_lam,
    b.y0_units,

    -- curve state (fix 6: y and both prices)
    b.x_sol                                             AS depth_x,
    b.y_tok                                             AS y_t,
    (b.x_sol - 30) / 85                                 AS curve_progress,
    b.x_sol / b.y_tok                                   AS p_t,
    (b.x_sol * b.x_sol)
      / (CAST(b.x0_lam AS double) / 1e9 * CAST(b.y0_units AS double) / 1e6) AS p_launch,

    -- trigger
    b.wallet                                            AS trigger_wallet,
    b.is_buy                                            AS trigger_is_buy,
    CAST(b.lam AS double) / 1e9                         AS trigger_sol,
    CAST(b.units AS double) / 1e6                       AS trigger_tokens,
    CAST(b.fee_lam + b.creator_fee_lam AS double) / 1e9 AS trigger_fee_sol,

    -- features f1-f9 (trailing, unchanged boundary)
    CAST(b.nf3_lam  AS double) / 1e9                    AS net_flow_3slot,
    CAST(b.nf5_lam  AS double) / 1e9                    AS net_flow_5slot,
    CAST(b.nf12_lam AS double) / 1e9                    AS net_flow_12slot,
    CAST(b.nf25_lam AS double) / 1e9                    AS net_flow_25slot,
    if(b.nf25_lam = 0, CAST(NULL AS double),
       CAST(b.nf5_lam AS double) / (CAST(b.nf25_lam AS double) / 5)) AS accel,
    f3.n_buyers_12slot,
    b.n_trades_25                                       AS n_trades_25slot,
    -- f8: coefficient of variation of trade size over the trailing 25 slots
    if(b.n_trades_25 = 0 OR b.s1_25 = 0, CAST(NULL AS double),
       sqrt(greatest(b.s2_25 / b.n_trades_25
                     - power(b.s1_25 / b.n_trades_25, 2), 0.0))
       / (b.s1_25 / b.n_trades_25))                     AS size_cv_25slot,
    -- f9: share of those trades at exactly 0.1 / 0.5 / 1.0 SOL
    if(b.n_trades_25 = 0, CAST(NULL AS double),
       CAST(b.rnd_25 AS double) / b.n_trades_25)        AS round_frac_25slot,
    b.slot - b.first_slot                               AS burst_age_slot,

    -- OH, both transfer variants (fix 3) -- NEITHER is the primary
    o.oh_a, o.oh_b,
    o.oh_a / b.x_sol                                    AS oh_ratio_a,
    o.oh_b / b.x_sol                                    AS oh_ratio_b,
    if(o.oh_a > 0, o.oh_top3_a / o.oh_a, 0.0)           AS oh_conc_a,
    if(o.oh_b > 0, o.oh_top3_b / o.oh_b, 0.0)           AS oh_conc_b,
    o.oh_n_wallets_a, o.oh_n_wallets_b,

    -- cost-basis conventions (fixes 4, 5)
    cv.cb_reset_gross, cv.cb_net, cv.cb_legacy,
    CAST(cv.held_from_buys AS double) / 1e6             AS held_from_buys,
    CAST(cv.held_from_transfers AS double) / 1e6        AS held_from_transfers,

    -- forward labels (fix 1: (s, s+tau], priced off the end of slot s)
    CAST(b.fwd_nf5_lam  AS double) / 1e9                AS fwd_net_flow_5slot,
    CAST(b.fwd_nf12_lam AS double) / 1e9                AS fwd_net_flow_12slot,
    CAST(b.fwd_nf37_lam AS double) / 1e9                AS fwd_net_flow_37slot,
    CAST(b.vsol_end_s AS double) / 1e9                  AS x_end_slot,
    CAST(b.vtok_end_s AS double) / 1e6                  AS y_end_slot,
    CAST(b.vsol_p5  AS double) / 1e9                    AS x_at_plus5,
    CAST(b.vsol_p12 AS double) / 1e9                    AS x_at_plus12,
    CAST(b.vsol_p37 AS double) / 1e9                    AS x_at_plus37,
    CAST(b.vtok_p5  AS double) / 1e6                    AS y_at_plus5,
    CAST(b.vtok_p12 AS double) / 1e6                    AS y_at_plus12,
    CAST(b.vtok_p37 AS double) / 1e6                    AS y_at_plus37,
    ((CAST(b.vsol_p12 AS double) / CAST(b.vtok_p12 AS double))
     / (CAST(b.vsol_end_s AS double) / CAST(b.vtok_end_s AS double))) - 1
                                                        AS fwd_price_ret_12slot,

    -- §5 latency
    CAST(b.v_lat1_lam AS double) / 1e9                  AS v_latency_1slot,
    CAST(b.v_lat2_lam AS double) / 1e9                  AS v_latency_2slot,
    CAST(b.v_lat3_lam AS double) / 1e9                  AS v_latency_3slot,
    CAST(b.v_lat7_lam AS double) / 1e9                  AS v_latency_7slot,
    CAST(b.v_lat8_lam AS double) / 1e9                  AS v_latency_8slot,

    -- §4.3 hazard
    tr.nf3_traj_75_incl_pre, tr.nf3_excl_pre_1, tr.nf3_excl_pre_2,
    tr.traj_len, tr.nonzero_incl, tr.nonzero_excl,
    tr.death_age_incl, tr.death_age_excl,
    b.death_slot - b.slot                               AS death_age_slot,
    tr.death_age_incl IS NULL                           AS censored_incl,
    tr.death_age_excl IS NULL                           AS censored_excl,
    b.death_slot IS NULL                                AS hazard_censored,

    -- §3d sensitivity flags
    CAST(b.nf5_lam AS double)/1e9 >= greatest(3.0, 0.05 * b.x_sol) AS qual_005,
    CAST(b.nf5_lam AS double)/1e9 >= greatest(3.0, 0.20 * b.x_sol) AS qual_020,

    g.ok                                                AS launch_window_guard
FROM bursts b
CROSS JOIN guard g
JOIN traj tr ON tr.mint = b.mint AND tr.seq = b.seq
JOIN f3      ON f3.mint = b.mint AND f3.seq = b.seq
JOIN oh o    ON o.mint  = b.mint AND o.seq  = b.seq
JOIN cb_variants cv ON cv.mint = b.mint AND cv.seq = b.seq
