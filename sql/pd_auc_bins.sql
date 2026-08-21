-- 3 -- launch-day cluster bootstrap input.
--
-- WHY BINS.  A per-token export is 25,353 rows x 8 features; at the measured
-- retrieval price (11.748 cr per 1e6 result bytes) that is far past this task's
-- budget.  Instead the exact quantities the bootstrap needs are exported:
-- per (feature, launch day, global quantile bin) the count of winners and
-- losers.  From those the cluster-pair Mann-Whitney matrix U[c][c'] is built
-- LOCALLY, and every bootstrap replicate is an exact reweighting of it --
--     AUC_b = sum_cc' m_c m_c' U[c][c'] / ((sum m_c P_c)(sum m_c N_c))
-- so B = 1,000 replicates cost 0 credits.
--
-- ⚠ DISCRETISATION.  Pairs inside one bin are scored 0.5 (as ties).  With 60
-- global quantile bins the resulting AUC bias is bounded by 1/(2*60) = 0.0083.
-- It affects the CI ONLY: the point AUC is the exact mid-rank value already
-- measured in sql/pd_discrim.sql, and the two are reported side by side.
-- Variables with fewer than 60 distinct values are binned exactly, no error.
--
-- CLUSTER = launch date, 9 days in [2026-05-10, 2026-05-19).
WITH p AS (SELECT * FROM dune.quantbino1695.result_flow_pd),
s AS (SELECT * FROM dune.quantbino1695.result_flow_pdstab),
h AS (SELECT * FROM dune.quantbino1695.result_flow_pdhist),
b AS (
    SELECT p.token_mint, p.ld, p.win, p.t_a_s,
           CAST(s.n_hold_drop AS double) AS n_hold_drop,
           CAST(s.n_of20_left AS double) AS n_of20_left,
           CAST(s.n_new AS double)       AS n_new,
           h.wr_med, h.wr_p90, h.n_wr20, h.share_exp
    FROM p LEFT JOIN s ON s.token_mint = p.token_mint
           LEFT JOIN h ON h.token_mint = p.token_mint
),
long AS (
    SELECT ld, win, u.feat, u.val
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW(1, t_a_s),       ROW(2, n_hold_drop), ROW(3, n_of20_left), ROW(4, n_new),
        ROW(5, wr_med),      ROW(6, wr_p90),      ROW(7, n_wr20),      ROW(8, share_exp)
    ]) AS u(feat, val)
    WHERE u.val IS NOT NULL
),
rk AS (
    SELECT feat, ld, win,
           CAST(rank() OVER (PARTITION BY feat ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, val) AS double) - 1)/2.0 AS m,
           CAST(count(*) OVER (PARTITION BY feat) AS double) AS nf
    FROM long
)
SELECT feat AS f, ld AS d,
       least(60, greatest(1, CAST(ceil(60.0 * m / nf) AS integer))) AS b,
       CAST(count_if(win) AS bigint)     AS np,
       CAST(count_if(NOT win) AS bigint) AS nn
FROM rk GROUP BY feat, ld, least(60, greatest(1, CAST(ceil(60.0 * m / nf) AS integer)))
