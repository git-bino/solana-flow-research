-- The numeric tertile cut-offs, on the EXACT population the rule's figures use:
-- result_flow_gapin INNER JOIN hfeat INNER JOIN hbar INNER JOIN token_base,
-- mid-rank, before any cell filter.  `src/anchor_rule.py` now REQUIRES
-- `tertile_cut`, so the number has to be written down.
WITH gi AS (SELECT token_mint FROM dune.quantbino1695.result_flow_gapin),
hb AS (SELECT token_mint FROM dune.quantbino1695.result_flow_hbar),
tb AS (SELECT token_mint FROM dune.quantbino1695.result_flow_token_base),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
j AS (SELECT hf.f_gini, hf.f_creator FROM gi JOIN hf ON hf.token_mint = gi.token_mint
      JOIN hb ON hb.token_mint = gi.token_mint JOIN tb ON tb.token_mint = gi.token_mint),
rk AS (
    SELECT j.*,
           CAST(rank() OVER (ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_gini) AS double) - 1)/2.0 AS mg,
           CAST(rank() OVER (ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_creator) AS double) - 1)/2.0 AS mc,
           CAST(count(*) OVER () AS double) AS n_tot
    FROM j
),
l AS (SELECT rk.*, least(3, greatest(1, CAST(ceil(3.0*mg/n_tot) AS integer))) AS g3,
             least(3, greatest(1, CAST(ceil(3.0*mc/n_tot) AS integer))) AS c3 FROM rk)
SELECT 'gini' AS feat, g3 AS tercile, CAST(count(*) AS double) AS n,
       min(f_gini) AS lo, max(f_gini) AS hi FROM l GROUP BY g3
UNION ALL
SELECT 'creator_share', c3, CAST(count(*) AS double), min(f_creator), max(f_creator)
FROM l GROUP BY c3
ORDER BY feat, tercile
