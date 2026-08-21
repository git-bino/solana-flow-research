-- 1 -- HOLDER-COUNT ANCHORS.  First moment a token's holder count reaches N.
--
-- ONE ROW PER (token, anchor).  Anchors: N in {3, 5, 10, 15, 20} plus the
-- x >= 60 anchor, carried in the SAME execution so the comparison in §3 uses an
-- identically-built clock.  Built as a MATERIALIZED VIEW; nothing is exported.
--
-- HOLDER DEFINITION.  A wallet holds when its running balance is > 0, where the
-- balance is TRANSFER-AWARE -- (bought - sold) + (received - sent), the same
-- mechanism as `oh_a` in extract_v2.  Transfer coverage was verified before
-- writing this: the xf matviews run 2026-05-10 .. 2026-08-15 with no gap and
-- their token scope, creations in [2026-05-10, 2026-07-03), contains the cohort.
--
-- RUNNING COUNT WITHOUT A LAG.  For each (mint, wallet, seq) the balance BEFORE
-- the event is exactly `b - du`, so the holder-count transition is
--     +1 when b > 0 and b - du <= 0      (wallet became a holder)
--     -1 when b <= 0 and b - du > 0      (wallet stopped holding)
-- and n_holders at an event is the running sum of those transitions over the
-- token's event stream.  No `lag` window is needed, which removes one sort.
--
-- SEQ.  A single ordering key across trades and transfers:
--     slot * 1e9 + tx_index * 1e4 + (outer_ix * 64 + inner_ix)
-- Slot in 2026 is ~4e8 so slot*1e9 stays inside bigint.  Legs sharing a
-- (mint, wallet, seq) are summed first, so no tie can split one wallet's balance
-- across two window rows.
--
-- TIME.  The transfer matviews carry `block_slot` but NOT `block_time`, so an
-- anchor that lands on a transfer has no timestamp of its own; `bt_ff` carries
-- the last known TRADE time forward.  Transfers are 592,642 rows against
-- 19,308,576 trades in this window (measured), so this affects few anchors, but
-- `t_a_s` is a last-trade time, not the transfer's own time, and is labelled so.
--
-- EVENT WINDOW.  [2026-05-10, 2026-05-20] -- the launch window plus one day.
-- A token whose holder count first reaches N after 2026-05-20 is absent; the
-- coverage counts in §1a state exactly how many tokens each anchor found.

WITH base AS (
    SELECT token_mint, launch_time, creator
    FROM dune.quantbino1695.result_flow_token_base
),
tr AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           CAST(t.evt_block_slot AS bigint) AS sl,
           t.evt_block_time AS bt,
           t.user AS w,
           if(t.is_buy, CAST(t.token_amount AS double),
                       -CAST(t.token_amount AS double))  AS du,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9  AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-05-20'
),
xf_raw AS (
    SELECT token_mint_address AS mint,
           CAST(block_slot AS bigint) * 1000000000
             + CAST(tx_index AS bigint) * 10000
             + CAST(coalesce(outer_ix_index, 0) * 64
                    + coalesce(inner_ix_index, 0) AS bigint) AS seq,
           CAST(block_slot AS bigint) AS sl,
           from_owner, to_owner, CAST(amount AS double) AS amount
    FROM ({{XF_UNION}}) u
    WHERE block_date >= DATE '2026-05-10' AND block_date <= DATE '2026-05-20'
),
xfr AS (
    SELECT mint, seq, sl, to_owner   AS w,  amount AS du FROM xf_raw
    UNION ALL
    SELECT mint, seq, sl, from_owner AS w, -amount AS du FROM xf_raw
),
legs AS (
    SELECT mint, seq, sl, bt, w, du, x FROM tr
    UNION ALL
    SELECT mint, seq, sl, CAST(NULL AS timestamp(3) with time zone), w, du,
           CAST(NULL AS double)
    FROM xfr
),
legs2 AS (
    SELECT mint, seq, w, sum(du) AS du,
           max(sl) AS sl, max(bt) AS bt, max(x) AS x
    FROM legs GROUP BY mint, seq, w
),
bal AS (
    SELECT mint, seq, w, sl, bt, x, du,
           sum(du) OVER (PARTITION BY mint, w ORDER BY seq
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS b
    FROM legs2
),
ev_delta AS (
    SELECT mint, seq, max(sl) AS sl, max(bt) AS bt, max(x) AS x,
           sum(CASE WHEN b > 0 AND b - du <= 0 THEN 1
                    WHEN b <= 0 AND b - du > 0 THEN -1
                    ELSE 0 END) AS d
    FROM bal GROUP BY mint, seq
),
hc AS (
    SELECT mint, seq, sl,
           sum(d) OVER (PARTITION BY mint ORDER BY seq
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS nh,
           last_value(bt) IGNORE NULLS OVER (PARTITION BY mint ORDER BY seq
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bt_ff,
           last_value(x) IGNORE NULLS OVER (PARTITION BY mint ORDER BY seq
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS x_ff
    FROM ev_delta
),
anch AS (
    SELECT mint, 'H3'  AS anchor_kind, 3 AS n_target, min(seq) AS seq_a,
           min_by(sl, seq) AS sl_a, min_by(bt_ff, seq) AS bt_a,
           min_by(x_ff, seq) AS x_a, min_by(nh, seq) AS nh_a
    FROM hc WHERE nh >= 3 GROUP BY mint
    UNION ALL
    SELECT mint, 'H5', 5, min(seq), min_by(sl, seq), min_by(bt_ff, seq),
           min_by(x_ff, seq), min_by(nh, seq)
    FROM hc WHERE nh >= 5 GROUP BY mint
    UNION ALL
    SELECT mint, 'H10', 10, min(seq), min_by(sl, seq), min_by(bt_ff, seq),
           min_by(x_ff, seq), min_by(nh, seq)
    FROM hc WHERE nh >= 10 GROUP BY mint
    UNION ALL
    SELECT mint, 'H15', 15, min(seq), min_by(sl, seq), min_by(bt_ff, seq),
           min_by(x_ff, seq), min_by(nh, seq)
    FROM hc WHERE nh >= 15 GROUP BY mint
    UNION ALL
    SELECT mint, 'H20', 20, min(seq), min_by(sl, seq), min_by(bt_ff, seq),
           min_by(x_ff, seq), min_by(nh, seq)
    FROM hc WHERE nh >= 20 GROUP BY mint
    UNION ALL
    SELECT mint, 'X60', 0, min(seq), min_by(sl, seq), min_by(bt_ff, seq),
           min_by(x_ff, seq), min_by(nh, seq)
    FROM hc WHERE x_ff >= 60 GROUP BY mint
)
SELECT a.mint AS token_mint,
       a.anchor_kind,
       a.n_target,
       a.seq_a,
       a.sl_a,
       to_unixtime(a.bt_a) - to_unixtime(b.launch_time) AS t_a_s,
       a.x_a,
       a.nh_a
FROM anch a
JOIN base b ON b.token_mint = a.mint
WHERE a.x_a IS NOT NULL
