-- 4 (check) -- where do the losers that NEVER fell 5% sit in the wr_med
-- quintiles?  §4 reports 100.00% loser removal at L = 0.95 inside B1q5, so the
-- tokens that make the ALL-population figure 98.46% must live somewhere else.
-- Minimal shape on purpose: one join, one window pair, one GROUP BY, no UNNEST.
WITH b AS (
    SELECT p.win, p.min_x_win / p.x_a AS r, h.wr_med
    FROM dune.quantbino1695.result_flow_pd p
    LEFT JOIN dune.quantbino1695.result_flow_pdhist h ON h.token_mint = p.token_mint
),
rk AS (
    SELECT win, r, wr_med,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double) - 1)/2.0 AS m,
           CAST(count(*) OVER (PARTITION BY (wr_med IS NULL)) AS double) AS nf
    FROM b
),
g AS (
    SELECT win, r,
           CASE WHEN wr_med IS NULL THEN 0
                ELSE least(5, greatest(1, CAST(ceil(5.0 * m / nf) AS integer))) END AS q
    FROM rk
)
SELECT q, CAST(count(*) AS double) AS n,
       CAST(count_if(NOT win) AS double)                  AS n_los,
       CAST(count_if(NOT win AND r > 0.95) AS double)     AS los_above_95,
       CAST(count_if(NOT win AND r > 0.90) AS double)     AS los_above_90,
       CAST(count_if(win) AS double)                      AS n_win,
       CAST(count_if(win AND r > 0.95) AS double)         AS win_above_95
FROM g GROUP BY GROUPING SETS ((), (q)) ORDER BY q
