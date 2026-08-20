-- 1 (divergent cell) -- the only cell where the invariant and the flag disagree:
-- createevent says mayhem, the invariant says the curve never moved.
-- Up to 20 examples with their measured deviation.
WITH c AS (
    SELECT token_mint, mayhem_flag, n_ev, k0, xy_min, xy_max, max_x,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
)
SELECT token_mint, mayhem_flag, n_ev, dev, k0, max_x
FROM c
WHERE mayhem_flag AND dev IS NOT NULL AND dev < 1e-6
ORDER BY dev DESC
LIMIT 20
