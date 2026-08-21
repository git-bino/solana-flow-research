-- 2 -- WHO SOLD between the anchor and the drawdown.  Matview, clean universe.
--
-- ONE scan of tradeevent, ONE GROUP BY (mint, anchor, wallet).  The anchor
-- ledger and the in-window sells are both derived from the same joined stream
-- with conditional aggregates, so the heavy CTE is referenced ONCE -- a second
-- reference would re-execute it (`cond` 60.697 cr, `clean_baselines` 3.805).
--
-- CLASSES (pre-registered):
--   CREATOR : the wallet equals createevent's creator
--   EARLY   : held_units > 0 AT the anchor (i.e. one of the 15/20)
--   LATE    : first became a holder after the anchor
-- The ledger is TRANSFER-AWARE: transfer legs carry sol = 0 and are counted
-- only towards the anchor balance, never as sells.
--
-- Tokens with no drawdown are excluded here and counted separately in §1.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
cr AS (
    SELECT mint, min(user) AS creator FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
a AS (
    SELECT d.token_mint, d.anchor_kind, d.seq_a, d.seq_drop, d.x_a, cr.creator
    FROM dune.quantbino1695.result_flow_dd d
    JOIN coh c ON c.token_mint = d.token_mint
    LEFT JOIN cr ON cr.mint = d.token_mint
    WHERE d.seq_drop IS NOT NULL
),
tr AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           t.user AS w,
           if(t.is_buy, CAST(t.token_amount AS double),
                       -CAST(t.token_amount AS double)) AS du,
           CAST(t.sol_amount AS double) / 1e9 AS sol,
           t.is_buy
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN coh c ON c.token_mint = t.mint
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
    SELECT mint, seq, w, du, sol, is_buy FROM tr
    UNION ALL SELECT mint, seq, to_owner,    amount, 0.0, CAST(NULL AS boolean) FROM xf_raw
    UNION ALL SELECT mint, seq, from_owner, -amount, 0.0, CAST(NULL AS boolean) FROM xf_raw
),
j AS (
    SELECT a.token_mint, a.anchor_kind, a.creator, a.x_a, a.seq_a,
           l.w, l.seq, l.du, l.sol, l.is_buy
    FROM a JOIN legs l ON l.mint = a.token_mint AND l.seq <= a.seq_drop
),
wl AS (
    SELECT token_mint, anchor_kind, w,
           max(creator) AS creator,
           sum(if(seq <= seq_a, du, 0.0))                                AS u_anchor,
           sum(if(seq > seq_a AND is_buy = false, -du, 0.0))             AS sold_units,
           sum(if(seq > seq_a AND is_buy = false, sol, 0.0))             AS sold_sol,
           CAST(count_if(seq > seq_a AND is_buy = false) AS bigint)      AS n_sells,
           sum(if(seq > seq_a AND is_buy = true, sol, 0.0))              AS bought_sol
    FROM j GROUP BY token_mint, anchor_kind, w
),
cls AS (
    SELECT wl.*,
           CASE WHEN w = creator THEN 'CREATOR'
                WHEN u_anchor > 0 THEN 'EARLY' ELSE 'LATE' END AS cls
    FROM wl
)
SELECT token_mint, anchor_kind, w AS wallet, cls, u_anchor, sold_units, sold_sol,
       n_sells, bought_sol
FROM cls
WHERE sold_units > 0 OR u_anchor > 0
