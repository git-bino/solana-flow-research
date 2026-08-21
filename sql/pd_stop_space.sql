-- 4 -- stop space.  `min_x_win / x_a <= L` is EXACTLY "the path touched L", so
-- the whole survival table comes from result_flow_pd with no new scan.
--
-- Three populations side by side:
--   ALL   -- every clean H20 token
--   B1q5  -- top quintile of wr_med, the strongest LOOKAHEAD-FREE variable
--   A2q5  -- top quintile of n_hold_drop, the strongest variable overall, which
--            is measured at the drawdown and is NOT lookahead-free
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР: the brief says "the strongest variable's top
-- group"; two variables are strongest under two different readings, so both are
-- reported rather than one being picked.
--
-- ⚠ ASYMMETRIC WINDOW, stated: for a winner `min_x_win` runs only to the
-- 60-crossing (t_60 median 17.9 s); for a loser it runs over the whole forward
-- path (lifetime median 7,528 s).  A stop compared this way gives the loser far
-- more time to touch the level.  No time limit is imposed here.
WITH p AS (SELECT * FROM dune.quantbino1695.result_flow_pd),
h AS (SELECT * FROM dune.quantbino1695.result_flow_pdhist),
s AS (SELECT * FROM dune.quantbino1695.result_flow_pdstab),
b AS (
    SELECT p.token_mint, p.win, p.min_x_win / p.x_a AS r, h.wr_med,
           CAST(s.n_hold_drop AS double) AS nhd
    FROM p LEFT JOIN h ON h.token_mint = p.token_mint
           LEFT JOIN s ON s.token_mint = p.token_mint
),
rk AS (
    SELECT b.*,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double) - 1)/2.0 AS m1,
           CAST(count(*) OVER (PARTITION BY (wr_med IS NULL)) AS double) AS n1,
           CAST(rank() OVER (ORDER BY nhd) AS double)
             + (CAST(count(*) OVER (PARTITION BY nhd) AS double) - 1)/2.0 AS m2,
           CAST(count(*) OVER (PARTITION BY (nhd IS NULL)) AS double) AS n2
    FROM b
),
pop AS (
    SELECT r, win, u.lab
    FROM rk CROSS JOIN UNNEST(ARRAY['ALL', 'B1q5', 'A2q5']) AS u(lab)
    WHERE u.lab = 'ALL'
       OR (u.lab = 'B1q5' AND wr_med IS NOT NULL AND ceil(5.0*m1/n1) >= 5)
       OR (u.lab = 'A2q5' AND nhd    IS NOT NULL AND ceil(5.0*m2/n2) >= 5)
),
lv AS (
    SELECT pop.lab, pop.win, pop.r, u.L
    FROM pop CROSS JOIN UNNEST(ARRAY[0.95, 0.90, 0.875, 0.85, 0.825,
                                     0.80, 0.775, 0.75, 0.70]) AS u(L)
)
SELECT lab, L,
       CAST(count_if(win) AS double)                          AS n_win,
       CAST(count_if(NOT win) AS double)                       AS n_los,
       CAST(count_if(win AND r <= L) AS double)/count_if(win)  AS w_hit,
       CAST(count_if(NOT win AND r <= L) AS double)/count_if(NOT win) AS l_hit,
       CAST(count_if(win AND r > L) AS double)                 AS w_keep,
       CAST(count_if(NOT win AND r > L) AS double)             AS l_keep,
       CAST(count_if(win AND r > L) AS double)
         / nullif(CAST(count_if(r > L) AS double), 0)          AS keep_rate
FROM lv GROUP BY lab, L ORDER BY lab, L DESC
