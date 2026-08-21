-- 2 (aggregate) -- who sold, by class.  Reads result_flow_ddsell + dd.
-- One GROUPING SETS pass; the token-level CTE is referenced once.
WITH s AS (SELECT * FROM dune.quantbino1695.result_flow_ddsell),
tok AS (
    SELECT token_mint, anchor_kind,
           sum(if(u_anchor > 0, u_anchor, 0.0))                       AS tot_u,
           sum(if(cls = 'CREATOR' AND u_anchor > 0, u_anchor, 0.0))   AS cre_u,
           sum(if(cls = 'CREATOR', sold_units, 0.0))                  AS cre_sold,
           sum(sold_sol)                                              AS all_sold_sol,
           max_by(cls, sold_units)                                    AS top_seller_cls,
           max(sold_units)                                            AS top_seller_units
    FROM s GROUP BY token_mint, anchor_kind
),
j AS (
    SELECT s.*, t.tot_u, t.cre_u, t.cre_sold, t.top_seller_cls
    FROM s JOIN tok t ON t.token_mint = s.token_mint AND t.anchor_kind = s.anchor_kind
)
SELECT anchor_kind, cls,
       CAST(count(*) AS double)                                   AS n_wallets,
       CAST(sum(n_sells) AS double)                               AS n_sells,
       sum(sold_sol)                                              AS sold_sol,
       sum(sold_units)                                            AS sold_units,
       CAST(count_if(sold_units > 0) AS double)                   AS n_sellers,
       CAST(count(DISTINCT if(sold_units > 0, token_mint)) AS double) AS n_tokens_with_seller,
       CAST(count(DISTINCT token_mint) AS double)                 AS n_tokens,
       CAST(count_if(top_seller_cls = cls AND sold_units > 0) AS double) AS n_top_seller
FROM j
GROUP BY GROUPING SETS ((anchor_kind), (anchor_kind, cls))
ORDER BY anchor_kind, cls
