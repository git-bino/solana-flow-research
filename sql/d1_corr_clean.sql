-- 1 (clean) -- Spearman and AUC on the NON-NULL population only.
--
-- ⚠ DEFECT this fixes, found in sql/d1_vs_xa.sql: `rank() OVER (ORDER BY x)`
-- assigns ranks to rows whose `x` is NULL (Trino puts them last), so an AUC or
-- a correlation built on those ranks silently includes the 1,366 tokens that
-- have no `sol_in` -- a population whose win rate is 72.04%, i.e. nothing like
-- the rest.  This is the same defect class as the `percent_rank()` NULL issue
-- fixed earlier in the execution-gap work.  Here every rank is taken after
-- `WHERE sol_in IS NOT NULL`, so the ranked set and the scored set are the same.
WITH b AS (
    SELECT p.win, p.x_a, a.sol_in,
           if(p.x_a > 30.0, a.sol_in / (p.x_a - 30.0)) AS ratio
    FROM dune.quantbino1695.result_flow_pd p
    JOIN dune.quantbino1695.result_flow_wanch a ON a.token_mint = p.token_mint
    WHERE a.sol_in IS NOT NULL
),
r AS (
    SELECT win, ratio,
           CAST(rank() OVER (ORDER BY sol_in) AS double)
             + (CAST(count(*) OVER (PARTITION BY sol_in) AS double)-1)/2.0 AS md,
           CAST(rank() OVER (ORDER BY x_a) AS double)
             + (CAST(count(*) OVER (PARTITION BY x_a) AS double)-1)/2.0 AS mx
    FROM b
),
r2 AS (
    SELECT r.*,
           CAST(rank() OVER (ORDER BY ratio) AS double)
             + (CAST(count(*) OVER (PARTITION BY ratio) AS double)-1)/2.0 AS mr
    FROM r WHERE ratio IS NOT NULL
)
SELECT CAST(count(*) AS double) AS n,
       CAST(count_if(win) AS double) AS n_win,
       corr(md, mx) AS sp_d1_xa,
       corr(mr, mx) AS sp_ratio_xa,
       (sum(if(win, md, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc_d1,
       (sum(if(win, mx, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc_xa,
       (sum(if(win, mr, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc_r
FROM r2
