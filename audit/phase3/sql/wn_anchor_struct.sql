-- 3 -- structure of the anchor itself.  Everything is cut at seq_a, so nothing
-- after the anchor can enter: `S1` sums only legs with seq <= seq_a, `S2` reads
-- `u_anchor` (the balance AT the anchor), `S3` is the gap between two anchors
-- that both precede it, `S4` counts trades up to the anchor.
--
-- S1  total SOL the 20 anchor wallets BOUGHT up to the anchor.
-- S2  largest NON-CREATOR holder share of the anchor supply.
-- S3  seconds from the 10th holder to the 20th (H20.t_a_s - H10.t_a_s).
-- S4  number of trades up to the anchor (result_flow_hfeat_b.f_n_trades).
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
a AS (
    SELECT d.token_mint, d.seq_a
    FROM dune.quantbino1695.result_flow_dd d JOIN coh c ON c.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20'
),
aw AS (SELECT token_mint, wallet, cls, u_anchor
       FROM dune.quantbino1695.result_flow_ddsell
       WHERE anchor_kind = 'H20' AND u_anchor > 0),
-- S1: one scan, cut at seq_a
ev AS (
    SELECT t.mint, t.user AS w,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           CAST(t.sol_amount AS double) / 1e9 AS sol, t.is_buy
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-05-20'
),
s1 AS (
    SELECT a.token_mint, sum(if(e.is_buy, e.sol, 0.0)) AS sol_in
    FROM a JOIN aw ON aw.token_mint = a.token_mint
           JOIN ev e ON e.mint = a.token_mint AND e.w = aw.wallet AND e.seq <= a.seq_a
    GROUP BY a.token_mint
),
s2 AS (
    SELECT token_mint,
           max(if(cls <> 'CREATOR', u_anchor)) / nullif(sum(u_anchor), 0) AS top1_nc,
           CAST(count(*) AS double) AS n_hold_a
    FROM aw GROUP BY token_mint
),
s3 AS (
    SELECT h20.token_mint, h20.t_a_s - h10.t_a_s AS t10_20
    FROM dune.quantbino1695.result_flow_holder_anchor h20
    JOIN dune.quantbino1695.result_flow_holder_anchor h10
      ON h10.token_mint = h20.token_mint AND h10.anchor_kind = 'H10'
    WHERE h20.anchor_kind = 'H20'
),
s4 AS (
    SELECT token_mint, f_n_trades, f_n_buyers, f_gini, f_creator
    FROM dune.quantbino1695.result_flow_hfeat_b WHERE anchor_kind = 'H20'
)
SELECT a.token_mint, s1.sol_in, s2.top1_nc, s2.n_hold_a, s3.t10_20,
       s4.f_n_trades, s4.f_n_buyers, s4.f_gini, s4.f_creator
FROM a LEFT JOIN s1 ON s1.token_mint = a.token_mint
       LEFT JOIN s2 ON s2.token_mint = a.token_mint
       LEFT JOIN s3 ON s3.token_mint = a.token_mint
       LEFT JOIN s4 ON s4.token_mint = a.token_mint
