-- 1г -- distribution features AT the holder anchor.
--
-- Per-token, so §4 can group tokens by `gini` / `creator_share`; the §1г
-- percentile table is aggregated off this matview afterwards.
--
-- NO LOOKAHEAD.  The ledger sums legs with `seq <= seq_a` only -- the anchor
-- event itself is included (it is what made the count reach N), nothing after
-- it is.  `seq` is the same composite key the anchor was found with, so the cut
-- is exact and not a timestamp approximation.
--
-- LEDGER IS TRANSFER-AWARE, the same mechanism as `oh_a`.
WITH base AS (
    SELECT token_mint, launch_time, creator
    FROM dune.quantbino1695.result_flow_token_base
),
a AS (
    SELECT token_mint, anchor_kind, seq_a
    FROM dune.quantbino1695.result_flow_holder_anchor
    WHERE anchor_kind IN ({{KINDS}})
),
tr AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           t.user AS w, t.is_buy,
           if(t.is_buy, CAST(t.token_amount AS double),
                       -CAST(t.token_amount AS double)) AS du
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
           from_owner, to_owner, CAST(amount AS double) AS amount
    FROM ({{XF_UNION}}) u
    WHERE block_date >= DATE '2026-05-10' AND block_date <= DATE '2026-05-20'
),
legs AS (
    SELECT mint, seq, w, du FROM tr
    UNION ALL SELECT mint, seq, to_owner,   amount FROM xf_raw
    UNION ALL SELECT mint, seq, from_owner, -amount FROM xf_raw
),
led AS (
    SELECT a.token_mint, a.anchor_kind, l.w, sum(l.du) AS u
    FROM a JOIN legs l ON l.mint = a.token_mint AND l.seq <= a.seq_a
    GROUP BY a.token_mint, a.anchor_kind, l.w
),
trc AS (
    SELECT a.token_mint, a.anchor_kind,
           count(*) AS n_trades,
           count(DISTINCT if(t.is_buy, t.w)) AS n_buyers,
           max(b.creator) AS creator
    FROM a JOIN tr t ON t.mint = a.token_mint AND t.seq <= a.seq_a
           JOIN base b ON b.token_mint = a.token_mint
    GROUP BY a.token_mint, a.anchor_kind
),
hrank AS (
    SELECT l.token_mint, l.anchor_kind, l.w, l.u, c.creator,
           row_number() OVER (PARTITION BY l.token_mint, l.anchor_kind
                              ORDER BY l.u DESC) AS rk_d,
           row_number() OVER (PARTITION BY l.token_mint, l.anchor_kind
                              ORDER BY l.u ASC)  AS rk_a,
           count(*) OVER (PARTITION BY l.token_mint, l.anchor_kind) AS n_h,
           sum(l.u) OVER (PARTITION BY l.token_mint, l.anchor_kind) AS tot
    FROM led l JOIN trc c ON c.token_mint = l.token_mint
                         AND c.anchor_kind = l.anchor_kind
    WHERE l.u > 0
),
hagg AS (
    SELECT token_mint, anchor_kind, max(n_h) AS n_holders, max(tot) AS tot,
           sum(u) FILTER (WHERE rk_d = 1)  AS top1,
           sum(u) FILTER (WHERE rk_d <= 3) AS top3,
           sum(u) FILTER (WHERE w = creator) AS cre,
           sum(CAST(rk_a AS double) * u) AS wsum
    FROM hrank GROUP BY token_mint, anchor_kind
)
SELECT c.token_mint, c.anchor_kind,
       CAST(h.n_holders AS bigint)                    AS f_n_holders,
       if(h.tot > 0, h.top1 / h.tot, 1.0)             AS f_top1,
       if(h.tot > 0, h.top3 / h.tot, 1.0)             AS f_top3,
       if(h.tot > 0, coalesce(h.cre, 0) / h.tot, 0.0) AS f_creator,
       if(h.n_holders > 1 AND h.tot > 0,
          2.0 * h.wsum / (CAST(h.n_holders AS double) * h.tot)
            - (CAST(h.n_holders AS double) + 1) / CAST(h.n_holders AS double),
          0.0)                                        AS f_gini,
       CAST(c.n_trades AS bigint)                     AS f_n_trades,
       CAST(c.n_buyers AS bigint)                     AS f_n_buyers
FROM trc c JOIN hagg h ON h.token_mint = c.token_mint
                      AND h.anchor_kind = c.anchor_kind
