-- 3 -- PERMUTATION NULL for the clean universe, target r >= 1.76.
--
-- WHY IT IS CHEAP.  Permuting the LABEL within launch-day does not move any
-- feature's mid-rank -- only which rows are positive changes.  So one permuted
-- positive set gives all nine features' null AUCs at once, which is exactly the
-- max-of-cells null the selection correction needs, and the ranks are computed
-- ONCE rather than per iteration.
--
-- SCOPE, stated: 9 cells = 9 features on the CLEAN universe at the >= 1.76
-- target.  The other 45 cells (dirty universe, the 1.50 and 2.05 targets) are
-- NOT in the max, which makes the correction LESS conservative than a full
-- 54-cell correction would be; adding them could only raise the null max and so
-- raise the p-value.
--
-- The shuffle is a deterministic hash of (token, iteration), not `random()`:
-- reproducible, and safe against a CTE being re-evaluated.
-- Within each launch-day the number of positives is held at its observed value,
-- so the day-stratification the cluster structure requires is preserved exactly.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
hb AS (SELECT token_mint, x_a, t_a_s, max_x_after FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_n_holders, f_gini, f_top1, f_top3, f_creator,
              f_n_trades, f_n_buyers
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
tb AS (SELECT token_mint, date(launch_time) AS ld
       FROM dune.quantbino1695.result_flow_token_base),
j AS (
    SELECT hb.token_mint, hb.x_a, hb.t_a_s, tb.ld,
           hb.max_x_after / hb.x_a >= 1.76 AS y,
           hf.f_n_holders, hf.f_gini, hf.f_top1, hf.f_top3, hf.f_creator,
           hf.f_n_trades, hf.f_n_buyers
    FROM hb JOIN hf ON hf.token_mint = hb.token_mint
            JOIN cu ON cu.token_mint = hb.token_mint
            JOIN tb ON tb.token_mint = hb.token_mint
    WHERE cu.dev IS NOT NULL AND cu.dev < 1e-6
),
b AS (
    SELECT token_mint, ld, y,
           CAST(rank() OVER (ORDER BY CAST(f_n_holders AS double)) AS double)
             + (CAST(count(*) OVER (PARTITION BY CAST(f_n_holders AS double)) AS double) - 1)/2.0 AS m_n_holders,
           CAST(rank() OVER (ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_gini) AS double) - 1)/2.0 AS m_gini,
           CAST(rank() OVER (ORDER BY f_top1) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_top1) AS double) - 1)/2.0 AS m_top1,
           CAST(rank() OVER (ORDER BY f_top3) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_top3) AS double) - 1)/2.0 AS m_top3,
           CAST(rank() OVER (ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_creator) AS double) - 1)/2.0 AS m_creator_share,
           CAST(rank() OVER (ORDER BY CAST(f_n_trades AS double)) AS double)
             + (CAST(count(*) OVER (PARTITION BY CAST(f_n_trades AS double)) AS double) - 1)/2.0 AS m_n_trades,
           CAST(rank() OVER (ORDER BY CAST(f_n_buyers AS double)) AS double)
             + (CAST(count(*) OVER (PARTITION BY CAST(f_n_buyers AS double)) AS double) - 1)/2.0 AS m_n_buyers,
           CAST(rank() OVER (ORDER BY x_a) AS double)
             + (CAST(count(*) OVER (PARTITION BY x_a) AS double) - 1)/2.0 AS m_x_a,
           CAST(rank() OVER (ORDER BY t_a_s) AS double)
             + (CAST(count(*) OVER (PARTITION BY t_a_s) AS double) - 1)/2.0 AS m_t_a_s,
           1 AS one
    FROM j
),
dayn AS (SELECT ld, count(*) AS n_d, count_if(y) AS n1_d FROM b GROUP BY ld),
it AS (SELECT i FROM UNNEST(sequence(1, 200)) AS t(i)),
perm AS (
    SELECT b.*, it.i,
           row_number() OVER (PARTITION BY it.i, b.ld
                              ORDER BY abs(from_big_endian_64(
                                  xxhash64(to_utf8(b.token_mint || '|' || CAST(it.i AS varchar)))))
                             ) AS rk
    FROM b CROSS JOIN it
),
sel AS (
    SELECT p.* FROM perm p JOIN dayn d ON d.ld = p.ld WHERE p.rk <= d.n1_d
)
SELECT i, CAST(count(*) AS double) AS n1,
       sum(m_n_holders) AS s_n_holders,
       sum(m_gini) AS s_gini,
       sum(m_top1) AS s_top1,
       sum(m_top3) AS s_top3,
       sum(m_creator_share) AS s_creator_share,
       sum(m_n_trades) AS s_n_trades,
       sum(m_n_buyers) AS s_n_buyers,
       sum(m_x_a) AS s_x_a,
       sum(m_t_a_s) AS s_t_a_s
FROM sel GROUP BY i
