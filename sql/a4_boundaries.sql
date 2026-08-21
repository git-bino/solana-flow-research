-- AUDIT 4 FIX 1 (b) -- B1/B2 AUC and the nearest-rank p80 boundaries on the
-- CAUSAL universe, using result_flow_pdhist3 (prior history also built on the
-- causal universe).  NULLs are removed BEFORE any ranking.
WITH coh AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_clean WHERE mayhem_flag = false
),
h AS (
    SELECT h.token_mint, h.wr_med, h.wr_p90, p.win
    FROM dune.quantbino1695.result_flow_pdhist3 h
    JOIN coh c ON c.token_mint = h.token_mint
    JOIN dune.quantbino1695.result_flow_pd p ON p.token_mint = h.token_mint
    WHERE h.wr_med IS NOT NULL AND h.wr_p90 IS NOT NULL
),
r AS (
    SELECT h.*,
           row_number() OVER (ORDER BY wr_med) AS rn1,
           row_number() OVER (ORDER BY wr_p90) AS rn2,
           CAST(count(*) OVER () AS bigint) AS n,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double)-1)/2.0 AS m1,
           CAST(rank() OVER (ORDER BY wr_p90) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_p90) AS double)-1)/2.0 AS m2
    FROM h
),
b AS (
    SELECT max(n) AS n,
           max(if(rn1 = CAST(ceil(0.8 * n) AS bigint), wr_med)) AS b1,
           max(if(rn2 = CAST(ceil(0.8 * n) AS bigint), wr_p90)) AS b2
    FROM r
)
SELECT CAST(max(r.n) AS double) AS n_pop,
       max(b.b1) AS b1, max(b.b2) AS b2,
       (sum(if(r.win, r.m1, 0.0)) - CAST(count_if(r.win) AS double)*(CAST(count_if(r.win) AS double)+1)/2.0)
         / nullif(CAST(count_if(r.win) AS double)*CAST(count_if(NOT r.win) AS double),0) AS auc_b1,
       (sum(if(r.win, r.m2, 0.0)) - CAST(count_if(r.win) AS double)*(CAST(count_if(r.win) AS double)+1)/2.0)
         / nullif(CAST(count_if(r.win) AS double)*CAST(count_if(NOT r.win) AS double),0) AS auc_b2,
       CAST(count_if(r.wr_med >= b.b1 AND r.wr_p90 >= b.b2) AS double) AS n_sub,
       CAST(count_if(r.win AND r.wr_med >= b.b1 AND r.wr_p90 >= b.b2) AS double)
         / nullif(CAST(count_if(r.wr_med >= b.b1 AND r.wr_p90 >= b.b2) AS double),0) AS s60_sub
FROM r CROSS JOIN b
