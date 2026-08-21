-- 2(c) -- launch-day cluster bootstrap input for the ratio D1/(x_a - 30).
-- Same construction as sql/pd_auc_bins.sql: per (launch day, 60 global quantile
-- bin) the winner and loser counts; the bootstrap runs locally at 0 credits.
WITH b AS (
    SELECT p.ld, p.win,
           if(p.x_a > 30.0, a.sol_in / (p.x_a - 30.0)) AS ratio
    FROM dune.quantbino1695.result_flow_pd p
    LEFT JOIN dune.quantbino1695.result_flow_wanch a ON a.token_mint = p.token_mint
),
r AS (
    SELECT ld, win,
           CAST(rank() OVER (ORDER BY ratio) AS double)
             + (CAST(count(*) OVER (PARTITION BY ratio) AS double)-1)/2.0 AS m,
           CAST(count(*) OVER () AS double) AS nf
    FROM b WHERE ratio IS NOT NULL
)
SELECT ld AS d, least(60, greatest(1, CAST(ceil(60.0*m/nf) AS integer))) AS b,
       CAST(count_if(win) AS bigint) AS np, CAST(count_if(NOT win) AS bigint) AS nn
FROM r GROUP BY ld, least(60, greatest(1, CAST(ceil(60.0*m/nf) AS integer)))
