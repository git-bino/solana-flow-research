-- 2 (top seller, CORRECTED) + 4 -- anchor-time predictors -> drawdown outcome.
--
-- DEFECT FIXED (mine): the first version counted WALLETS whose class matched the
-- token's top-seller class, which double-counts and exceeded 100%.  The top
-- seller is one wallet per token, so the count must be over DISTINCT TOKENS.
--
-- `creator_share_a` = creator units / all positive units at the anchor.
-- `creator_out`     = the creator holds nothing at the anchor.
-- `top1_nc_share`   = largest NON-creator holder's share at the anchor.
-- The brief also lists "EARLY holders' total share": at the anchor EVERY holder
-- is early by construction, so that quantity is identically 1.0 and is reported
-- as degenerate rather than given a guessed alternative reading.
WITH s AS (SELECT * FROM dune.quantbino1695.result_flow_ddsell),
tok AS (
    SELECT token_mint, anchor_kind,
           sum(if(u_anchor > 0, u_anchor, 0.0))                     AS tot_u,
           sum(if(cls = 'CREATOR' AND u_anchor > 0, u_anchor, 0.0)) AS cre_u,
           max(if(cls <> 'CREATOR' AND u_anchor > 0, u_anchor, 0.0)) AS top1_nc_u,
           max(if(cls = 'CREATOR', sold_units, 0.0)) > 0            AS creator_sold,
           max_by(cls, sold_units)                                  AS top_seller_cls
    FROM s GROUP BY token_mint, anchor_kind
),
d AS (SELECT * FROM dune.quantbino1695.result_flow_dd WHERE seq_drop IS NOT NULL),
j AS (
    SELECT t.token_mint, t.anchor_kind, t.top_seller_cls, t.creator_sold,
           if(t.tot_u > 0, t.cre_u / t.tot_u, 0.0)      AS cre_share,
           if(t.tot_u > 0, t.top1_nc_u / t.tot_u, 0.0)  AS top1_nc_share,
           t.cre_u <= 0                                 AS creator_out,
           d.x_drop / d.x_a                             AS drop_ratio,
           d.max_x_after / d.x_a                        AS max_ratio,
           d.seq_60 IS NOT NULL                         AS hit60,
           (d.seq_60 IS NOT NULL AND d.seq_60 < d.seq_drop) AS hit60_before
    FROM tok t JOIN d ON d.token_mint = t.token_mint AND d.anchor_kind = t.anchor_kind
),
b AS (
    SELECT j.*,
           CASE WHEN cre_share <= 0 THEN '1_cre_0'
                WHEN cre_share < 0.05 THEN '2_cre_lt5'
                WHEN cre_share < 0.15 THEN '3_cre_5to15'
                WHEN cre_share < 0.30 THEN '4_cre_15to30'
                ELSE '5_cre_ge30' END AS cre_bin,
           CASE WHEN top1_nc_share < 0.10 THEN '1_t1_lt10'
                WHEN top1_nc_share < 0.20 THEN '2_t1_10to20'
                WHEN top1_nc_share < 0.35 THEN '3_t1_20to35'
                ELSE '4_t1_ge35' END AS t1_bin
    FROM j
)
SELECT anchor_kind, cre_bin, t1_bin, creator_out, top_seller_cls,
       CAST(count(*) AS double) AS n,
       approx_percentile(drop_ratio, 0.10) AS dr10,
       approx_percentile(drop_ratio, 0.50) AS dr50,
       approx_percentile(max_ratio, 0.50)  AS mr50,
       approx_percentile(max_ratio, 0.95)  AS mr95,
       CAST(count_if(hit60) AS double)/count(*)        AS s60,
       CAST(count_if(hit60_before) AS double)/count(*) AS s60b,
       CAST(count_if(creator_sold) AS double)/count(*) AS s_cre_sold,
       approx_percentile(cre_share, 0.50)   AS cs50,
       approx_percentile(top1_nc_share, 0.50) AS t150
FROM b
GROUP BY GROUPING SETS ((anchor_kind), (anchor_kind, top_seller_cls),
                        (anchor_kind, cre_bin), (anchor_kind, t1_bin),
                        (anchor_kind, creator_out), (anchor_kind, creator_out, cre_bin))
ORDER BY anchor_kind, cre_bin, t1_bin, creator_out, top_seller_cls
