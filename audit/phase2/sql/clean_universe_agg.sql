-- 1 -- the invariant, its distribution, and the 2x2 against the createevent flag.
-- Reads result_flow_clean only.  `dev` is NULL for tokens with no trade event.
WITH c AS (
    SELECT *,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
d AS (SELECT *, dev < 1e-6 AS is_clean FROM c)
SELECT 'dist' AS part, '-' AS a, '-' AS b, CAST(count(*) AS double) AS n,
       approx_percentile(dev, 0.50) AS v1, approx_percentile(dev, 0.90) AS v2,
       approx_percentile(dev, 0.99) AS v3, max(dev) AS v4,
       CAST(count_if(dev IS NULL) AS double) AS v5
FROM d
UNION ALL
SELECT 'thresh', CAST(t AS varchar), '-', CAST(count_if(dev < t) AS double),
       CAST(count_if(dev < t) AS double)/count(*), NULL, NULL, NULL, NULL
FROM d CROSS JOIN UNNEST(ARRAY[1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-3, 1e-2]) AS u(t)
GROUP BY t
UNION ALL
SELECT 'crosstab', CAST(is_clean AS varchar), CAST(mayhem_flag AS varchar),
       CAST(count(*) AS double),
       approx_percentile(dev, 0.50), approx_percentile(dev, 0.90),
       max(dev), min(dev), CAST(count_if(n_ev = 0) AS double)
FROM d GROUP BY is_clean, mayhem_flag
ORDER BY part, a, b
