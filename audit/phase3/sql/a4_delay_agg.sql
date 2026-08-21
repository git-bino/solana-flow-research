-- AUDIT 4 FIX 3 (agg) -- CLOSED share, closed-only E[ret] and trim5 by exit
-- delay.  ONE UNNEST (4 levels) BEFORE the windows; no fallback anywhere -- a
-- NULL fill leaves the position OPEN and unpriced at that delay.
WITH sub AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_pdhist3
    WHERE wr_med IS NOT NULL AND wr_p90 IS NOT NULL
      AND wr_med >= 0.572927597 AND wr_p90 >= 1.000000000
),
d AS (
    SELECT a.*, s.token_mint IS NOT NULL AS f2
    FROM dune.quantbino1695.result_flow_a4delay a
    LEFT JOIN sub s ON s.token_mint = a.token_mint
),
u AS (
    SELECT f2, x1, g_seq, t_seq, k.lx, k.gx, k.qx
    FROM d CROSS JOIN UNNEST(ARRAY[
        ROW(0, g0, q0), ROW(1, g1, q1), ROW(3, g3, q3), ROW(8, g8, q8)
    ]) AS k(lx, gx, qx)
),
r AS (
    SELECT f2, lx,
           CASE WHEN g_seq IS NOT NULL AND (t_seq IS NULL OR g_seq <= t_seq) THEN gx
                WHEN t_seq IS NOT NULL THEN qx END AS x_exit,
           x1
    FROM u
),
z AS (
    SELECT f2, lx,
           if(x_exit IS NOT NULL,
              ((0.5*(x_exit+0.5)*(x_exit+0.5) / (x1*(x1+0.5) + 0.5*(x_exit+0.5))) * 0.9875
               - 0.5/0.9875 - 0.002) / 0.5) AS ret
    FROM r
),
p AS (
    SELECT z.*,
           percent_rank() OVER (PARTITION BY lx, (ret IS NULL) ORDER BY ret)     AS pa,
           percent_rank() OVER (PARTITION BY lx, f2, (ret IS NULL) ORDER BY ret) AS pf
    FROM z
)
SELECT lx, f2, CAST(grouping(lx, f2) AS integer) AS gset,
       CAST(count(*) AS double)                   AS n,
       CAST(count_if(ret IS NOT NULL) AS double)  AS n_closed,
       sum(ret)                                   AS s_closed,
       approx_percentile(ret, 0.50)               AS med,
       CAST(count_if(ret > 0) AS double)          AS n_pos,
       sum(if(pa > 0.05 AND pa < 0.95, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pa > 0.05 AND pa < 0.95) AS double),0) AS t5_a,
       sum(if(pf > 0.05 AND pf < 0.95, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pf > 0.05 AND pf < 0.95) AS double),0) AS t5_f
FROM p GROUP BY GROUPING SETS ((lx), (lx, f2))
ORDER BY lx, f2
