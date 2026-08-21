-- 1 + 2 + 3 + 4 -- is D1_sol_in the same thing as x_a?
--
-- CLEAN universe only (max|x*y/k0 - 1| < 1e-6), H20 anchor, x_a = the reserve
-- AFTER the anchor event, target = x >= 60 reached after the anchor.
--
-- ONE source scan.  All quintiles are GLOBAL mid-rank quintiles (rank +
-- (tie_count-1)/2, never `ntile`), computed once in `r`, then read by every
-- grouping set.  No UNNEST anywhere, so the UNNEST x window blow-up cannot
-- happen; the branches are GROUPING SETS, not UNION ALL, so no CTE is
-- re-executed.
--
-- The 5x5 cross-tab (qd, qx) serves §1's cross-tab, §2(a) -- read down a fixed
-- qx row -- and §2(b) -- read across a fixed qd row.  It is the same table read
-- two ways, so it is computed once.
--
-- SPEARMAN is Pearson on the mid-ranks, so `corr(md, mx)` on the rank columns
-- is the Spearman coefficient (ties handled by the mid-rank, which is what
-- Spearman's tie correction does).
--
-- RATIO = D1 / (x_a - 30).  30 is the launch reserve, so `x_a - 30` is the net
-- SOL the curve took in up to the anchor and the ratio is the share of it that
-- came from the 20 anchor wallets' gross buys.  It is NULL when x_a = 30.
-- Gross buys are not net flow, so the ratio is not bounded by 1.
--
-- PRICE GAIN to 60 is (60/x_a)^2 - 1, since P = x^2/k.
--
-- ⚠ GROUPING SETS COLLISION, found and fixed in this file.  A first version
-- selected rows by "which key columns are NULL".  That is ambiguous: the ()
-- set emits qd=qx=qr=b5=NULL, and the (b5, qd) set ALSO emits a row with
-- b5=NULL (tokens whose wr_med is NULL) and qd=NULL (tokens whose sol_in is
-- NULL), which is a different 1,366-row population.  The two are
-- indistinguishable without `grouping()`.  Fixed two ways: `b5` is coalesced so
-- it is never NULL, and `grouping(...)` is emitted as `gset` so every row
-- states which set produced it.
WITH p AS (
    SELECT token_mint, ld, x_a, win, min_x_win, max_x_after, lifetime_s
    FROM dune.quantbino1695.result_flow_pd
),
b AS (
    SELECT p.*, a.sol_in, h.wr_med,
           if(p.x_a > 30.0, a.sol_in / (p.x_a - 30.0)) AS ratio
    FROM p LEFT JOIN dune.quantbino1695.result_flow_wanch  a ON a.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_pdhist h ON h.token_mint = p.token_mint
),
r AS (
    SELECT b.*,
           CAST(rank() OVER (ORDER BY sol_in) AS double)
             + (CAST(count(*) OVER (PARTITION BY sol_in) AS double)-1)/2.0 AS md,
           CAST(count(*) OVER (PARTITION BY (sol_in IS NULL)) AS double) AS nd,
           CAST(rank() OVER (ORDER BY x_a) AS double)
             + (CAST(count(*) OVER (PARTITION BY x_a) AS double)-1)/2.0 AS mx,
           CAST(count(*) OVER () AS double) AS nx,
           CAST(rank() OVER (ORDER BY ratio) AS double)
             + (CAST(count(*) OVER (PARTITION BY ratio) AS double)-1)/2.0 AS mr,
           CAST(count(*) OVER (PARTITION BY (ratio IS NULL)) AS double) AS nr,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double)-1)/2.0 AS mw,
           CAST(count(*) OVER (PARTITION BY (wr_med IS NULL)) AS double) AS nw
    FROM b
),
q AS (
    SELECT win, x_a, sol_in, ratio, min_x_win, max_x_after, lifetime_s, md, mx, mr,
           if(sol_in IS NULL, NULL, least(5,greatest(1,CAST(ceil(5.0*md/nd) AS integer)))) AS qd,
           least(5,greatest(1,CAST(ceil(5.0*mx/nx) AS integer)))                          AS qx,
           if(ratio  IS NULL, NULL, least(5,greatest(1,CAST(ceil(5.0*mr/nr) AS integer)))) AS qr,
           if(wr_med IS NULL, NULL, least(5,greatest(1,CAST(ceil(5.0*mw/nw) AS integer)))) AS qw
    FROM r
),
z AS (SELECT q.*, coalesce(qw = 5, false) AS b5 FROM q)
SELECT qd, qx, qr, b5,
       CAST(grouping(qd, qx, qr, b5) AS integer) AS gset,
       CAST(count(*) AS double)                                AS n,
       CAST(count_if(win) AS double)/count(*)                   AS s60,
       corr(md, mx)                                             AS spearman,
       approx_percentile(x_a, 0.50)                             AS xa50,
       approx_percentile(sol_in, 0.50)                          AS d1_50,
       approx_percentile(ratio, 0.10)                           AS r10,
       approx_percentile(ratio, 0.25)                           AS r25,
       approx_percentile(ratio, 0.50)                           AS r50,
       approx_percentile(ratio, 0.75)                           AS r75,
       approx_percentile(ratio, 0.90)                           AS r90,
       approx_percentile(power(60.0 / x_a, 2) - 1.0, 0.50)       AS gain50,
       approx_percentile(if(win, min_x_win / x_a), 0.10)         AS w10,
       approx_percentile(if(win, min_x_win / x_a), 0.25)         AS w25,
       approx_percentile(if(NOT win, min_x_win / x_a), 0.25)     AS l25,
       approx_percentile(if(NOT win, min_x_win / x_a), 0.50)     AS l50,
       approx_percentile(if(NOT win, min_x_win / x_a), 0.75)     AS l75,
       approx_percentile(max_x_after / x_a, 0.50)                AS mx50,
       approx_percentile(max_x_after / x_a, 0.90)                AS mx90,
       approx_percentile(max_x_after / x_a, 0.95)                AS mx95,
       approx_percentile(lifetime_s, 0.50)                       AS life50,
       (sum(if(win, md, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc_d1,
       (sum(if(win, mr, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc_r
FROM z
GROUP BY GROUPING SETS ((), (qd), (qx), (qd, qx), (qr), (b5, qd))
ORDER BY qd, qx, qr, b5
