-- 3(A) -- per-token holder-count variables at the drawdown.  Same ledger and
-- same definitions as sql/holder_stability.sql; only the final grain differs
-- (one row per token instead of one row per bin), so §3 can group by them.
-- Tokens with no drawdown (seq_drop IS NULL) have no such moment and are absent.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
a AS (
    SELECT d.token_mint, d.seq_a, d.seq_drop
    FROM dune.quantbino1695.result_flow_dd d JOIN coh c ON c.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20' AND d.seq_drop IS NOT NULL
),
tr AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           t.user AS w,
           if(t.is_buy, CAST(t.token_amount AS double), -CAST(t.token_amount AS double)) AS du
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
xf_raw AS (
    SELECT token_mint_address AS mint,
           CAST(block_slot AS bigint) * 1000000000
             + CAST(tx_index AS bigint) * 10000
             + CAST(coalesce(outer_ix_index, 0) * 64
                    + coalesce(inner_ix_index, 0) AS bigint) AS seq,
           from_owner, to_owner, CAST(amount AS double) AS amount
    FROM ({{XF_UNION}}) u
    WHERE block_date >= DATE '2026-05-10' AND block_date <= DATE '2026-08-15'
),
legs AS (
    SELECT mint, seq, w, du FROM tr
    UNION ALL SELECT mint, seq, to_owner,    amount FROM xf_raw
    UNION ALL SELECT mint, seq, from_owner, -amount FROM xf_raw
),
wl AS (
    SELECT a.token_mint, l.w,
           sum(if(l.seq <= a.seq_a, l.du, 0.0)) AS u_anchor,
           sum(l.du)                            AS u_drop
    FROM a JOIN legs l ON l.mint = a.token_mint AND l.seq <= a.seq_drop
    GROUP BY a.token_mint, l.w
)
SELECT token_mint,
       CAST(count_if(u_drop > 0) AS bigint)                             AS n_hold_drop,
       CAST(count_if(u_anchor > 0 AND u_drop <= 0) AS bigint)           AS n_exit,
       CAST(count_if(u_anchor <= 0 AND u_drop > 0) AS bigint)           AS n_new,
       CAST(count_if(u_anchor > 0 AND u_drop > 0) AS bigint)            AS n_of20_left
FROM wl GROUP BY token_mint
