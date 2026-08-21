-- 3 (floor) + 4 (sequence) -- both from existing matviews.
--
-- FLOOR: `min_x_all` over the token's whole life, clean universe.
-- SEQUENCE: which of stop / target fires first, from result_flow_eg_trig.
--   NOTE: eg_trig evaluates conditions on events AFTER THE ENTRY (3 events past
--   the anchor), not from the anchor itself.  Stated, not silently equated.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
m AS (
    SELECT g.min_x_all
    FROM dune.quantbino1695.result_flow_mig g JOIN coh c ON c.token_mint = g.token_mint
    WHERE g.n_ev > 0
),
t AS (
    SELECT e.s95, e.s90, e.s85, e.g60, e.g15,
           e.u95, e.u90, e.u85, e.ug60, e.ug15, en.anchor_unix
    FROM dune.quantbino1695.result_flow_eg_trig e
    JOIN coh c ON c.token_mint = e.token_mint
    JOIN dune.quantbino1695.result_flow_eg_entry en
      ON en.token_mint = e.token_mint AND en.anchor_kind = e.anchor_kind
    WHERE e.anchor_kind = 'H20'
),
p AS (
    SELECT t.*, u.slab, u.glab, u.s_seq, u.g_seq, u.s_ut, u.g_ut
    FROM t CROSS JOIN UNNEST(ARRAY[
        ROW('0.95', 'x60',   s95, g60, u95, ug60), ROW('0.95', 'xa15', s95, g15, u95, ug15),
        ROW('0.90', 'x60',   s90, g60, u90, ug60), ROW('0.90', 'xa15', s90, g15, u90, ug15),
        ROW('0.85', 'x60',   s85, g60, u85, ug60), ROW('0.85', 'xa15', s85, g15, u85, ug15)
    ]) AS u(slab, glab, s_seq, g_seq, s_ut, g_ut)
)
SELECT 'floor' AS part, '-' AS a, '-' AS b, CAST(count(*) AS double) AS n,
       approx_percentile(min_x_all, 0.01) AS v1, approx_percentile(min_x_all, 0.05) AS v2,
       approx_percentile(min_x_all, 0.10) AS v3, approx_percentile(min_x_all, 0.50) AS v4,
       CAST(count_if(min_x_all < 30) AS double)/count(*) AS v5,
       CAST(count_if(min_x_all < 32) AS double)/count(*) AS v6,
       CAST(count_if(min_x_all < 35) AS double)/count(*) AS v7,
       CAST(count_if(min_x_all < 38) AS double)/count(*) AS v8
FROM m
UNION ALL
SELECT 'seq', slab, glab, CAST(count(*) AS double),
       CAST(count_if(g_seq IS NOT NULL AND (s_seq IS NULL OR g_seq < s_seq)) AS double)/count(*),
       CAST(count_if(s_seq IS NOT NULL AND (g_seq IS NULL OR s_seq < g_seq)) AS double)/count(*),
       CAST(count_if(s_seq IS NULL AND g_seq IS NULL) AS double)/count(*),
       approx_percentile(if(g_seq IS NOT NULL AND (s_seq IS NULL OR g_seq < s_seq),
                            g_ut - anchor_unix), 0.50),
       approx_percentile(if(s_seq IS NOT NULL AND (g_seq IS NULL OR s_seq < g_seq),
                            s_ut - anchor_unix), 0.50),
       NULL, NULL, NULL
FROM p GROUP BY slab, glab
ORDER BY part, a, b
