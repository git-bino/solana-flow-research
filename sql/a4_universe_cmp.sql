-- AUDIT 4 FIX 1 (a) -- the two universes side by side.
--   OLD: max|x*y/k0 - 1| < 1e-6   -- computed over the token's WHOLE LIFE
--   NEW: createevent.is_mayhem_mode = false  -- known at launch
-- One source (result_flow_clean) joined to the H20 anchor table; no UNION ALL,
-- no UNNEST, grouping() not needed because there is a single output row.
WITH c AS (
    SELECT token_mint, mayhem_flag, n_ev,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
j AS (
    SELECT c.token_mint, c.mayhem_flag, c.n_ev,
           c.dev IS NOT NULL AND c.dev < 1e-6 AS inv_clean,
           p.win, p.x_a, p.t_60_s, p.token_mint IS NOT NULL AS has_anchor
    FROM c LEFT JOIN dune.quantbino1695.result_flow_pd p ON p.token_mint = c.token_mint
)
SELECT CAST(count_if(inv_clean AND n_ev > 0) AS double)                      AS n_old,
       CAST(count_if(NOT mayhem_flag AND n_ev > 0) AS double)                AS n_new,
       CAST(count_if(NOT mayhem_flag AND NOT inv_clean AND n_ev > 0) AS double) AS n_dirty_flagfalse,
       CAST(count_if(mayhem_flag AND inv_clean AND n_ev > 0) AS double)      AS n_flagtrue_clean,
       CAST(count_if(inv_clean AND has_anchor) AS double)                    AS a_old,
       CAST(count_if(NOT mayhem_flag AND has_anchor) AS double)              AS a_new,
       CAST(count_if(inv_clean AND has_anchor AND win) AS double)
         / nullif(CAST(count_if(inv_clean AND has_anchor) AS double),0)      AS s60_old,
       CAST(count_if(NOT mayhem_flag AND has_anchor AND win) AS double)
         / nullif(CAST(count_if(NOT mayhem_flag AND has_anchor) AS double),0) AS s60_new,
       approx_percentile(if(inv_clean AND has_anchor, x_a), 0.50)            AS xa_old,
       approx_percentile(if(NOT mayhem_flag AND has_anchor, x_a), 0.50)      AS xa_new,
       approx_percentile(if(inv_clean AND has_anchor AND win, t_60_s), 0.50) AS t60_old,
       approx_percentile(if(NOT mayhem_flag AND has_anchor AND win, t_60_s), 0.50) AS t60_new
FROM j
