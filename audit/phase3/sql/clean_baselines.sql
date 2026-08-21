-- 2 -- the baseline numbers, clean universe against contaminated, side by side.
-- Reads matviews only.  `universe`: clean = invariant < 1e-6, dirty = >= 1e-6,
-- no_ev = the token never traded (the invariant is undefined there).
WITH c AS (
    SELECT token_mint, mayhem_flag, n_ev, lifetime_s,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
u AS (
    SELECT token_mint, n_ev, lifetime_s,
           CASE WHEN dev IS NULL THEN 'no_ev' WHEN dev < 1e-6 THEN 'clean' ELSE 'dirty' END AS uni
    FROM c
),
b AS (
    SELECT u.uni, u.n_ev, u.lifetime_s, t.max_x, t.launch_time, t.t_60, t.t_115
    FROM u JOIN dune.quantbino1695.result_flow_token_base t ON t.token_mint = u.token_mint
),
g AS (
    SELECT uni, max_x, lifetime_s, n_ev,
           to_unixtime(t_60)  - to_unixtime(launch_time) AS t60_s,
           to_unixtime(t_115) - to_unixtime(launch_time) AS t115_s
    FROM b
)
SELECT uni, CAST(count(*) AS double) AS n,
       CAST(count_if(max_x IS NOT NULL) AS double) AS n_traded,
       approx_percentile(max_x, 0.10) AS mx10, approx_percentile(max_x, 0.25) AS mx25,
       approx_percentile(max_x, 0.50) AS mx50, approx_percentile(max_x, 0.75) AS mx75,
       approx_percentile(max_x, 0.90) AS mx90, approx_percentile(max_x, 0.95) AS mx95,
       approx_percentile(max_x, 0.99) AS mx99, max(max_x) AS mxmax,
       CAST(count_if(max_x > 40)  AS double)/nullif(count_if(max_x IS NOT NULL),0) AS s40,
       CAST(count_if(max_x > 60)  AS double)/nullif(count_if(max_x IS NOT NULL),0) AS s60,
       CAST(count_if(max_x > 80)  AS double)/nullif(count_if(max_x IS NOT NULL),0) AS s80,
       CAST(count_if(max_x >= 115) AS double)/nullif(count_if(max_x IS NOT NULL),0) AS s115,
       approx_percentile(t60_s, 0.50) AS t60_p50, approx_percentile(t115_s, 0.50) AS t115_p50,
       approx_percentile(lifetime_s, 0.50) AS life_p50,
       approx_percentile(lifetime_s, 0.90) AS life_p90,
       approx_percentile(CAST(n_ev AS double), 0.50) AS nev_p50,
       approx_percentile(CAST(n_ev AS double), 0.90) AS nev_p90
FROM g GROUP BY uni
UNION ALL
SELECT 'ALL', CAST(count(*) AS double), CAST(count_if(max_x IS NOT NULL) AS double),
       approx_percentile(max_x, 0.10), approx_percentile(max_x, 0.25),
       approx_percentile(max_x, 0.50), approx_percentile(max_x, 0.75),
       approx_percentile(max_x, 0.90), approx_percentile(max_x, 0.95),
       approx_percentile(max_x, 0.99), max(max_x),
       CAST(count_if(max_x > 40)  AS double)/nullif(count_if(max_x IS NOT NULL),0),
       CAST(count_if(max_x > 60)  AS double)/nullif(count_if(max_x IS NOT NULL),0),
       CAST(count_if(max_x > 80)  AS double)/nullif(count_if(max_x IS NOT NULL),0),
       CAST(count_if(max_x >= 115) AS double)/nullif(count_if(max_x IS NOT NULL),0),
       approx_percentile(t60_s, 0.50), approx_percentile(t115_s, 0.50),
       approx_percentile(lifetime_s, 0.50), approx_percentile(lifetime_s, 0.90),
       approx_percentile(CAST(n_ev AS double), 0.50), approx_percentile(CAST(n_ev AS double), 0.90)
FROM g
ORDER BY uni
