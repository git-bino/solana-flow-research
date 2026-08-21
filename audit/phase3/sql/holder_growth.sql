-- 1 + 2 -- holder-count attainment and token fate, CLEAN universe only.
--
-- SUBSTITUTION, stated (ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР).  The brief asks for the
-- LIFETIME MAXIMUM holder count and bins 1-2 / 3-4 / 5-9 / 10-19 / 20-49 /
-- 50-99 / 100+.  The maximum needs a running holder count -- one window
-- partitioned by (mint, wallet) and a second by mint -- which is the shape that
-- cost 24.466 cr in result_flow_holder_anchor, above this step's whole budget.
-- Instead the bins come from THRESHOLD ATTAINMENT already stored in that matview
-- (the first time the count reached 3, 5, 10, 15, 20):
--     1_lt3, 2_3to4, 3_5to9, 4_10to14, 5_15to19, 6_20plus
-- "reached >= 5 / 10 / 20" is therefore EXACT; ">= 50 / 100" and the split of
-- 20-49 / 50-99 / 100+ are NOT available and are not guessed.
--
-- `final_x` exists only for tokens with an H3 anchor (result_flow_gapin), so the
-- 1_lt3 bin has none; that is reported as missing rather than filled in.
--
-- Rug labels use the definitions of sql/token_fate_baseline.sql query C.
-- ONE GROUPING SETS pass, no UNION ALL.
WITH cu AS (
    SELECT token_mint, t_last, max_x, lifetime_s, n_ev,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT * FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
anch AS (
    SELECT token_mint,
           max(if(anchor_kind = 'H3', 1, 0))  AS h3,
           max(if(anchor_kind = 'H5', 1, 0))  AS h5,
           max(if(anchor_kind = 'H10', 1, 0)) AS h10,
           max(if(anchor_kind = 'H15', 1, 0)) AS h15,
           max(if(anchor_kind = 'H20', 1, 0)) AS h20
    FROM dune.quantbino1695.result_flow_holder_anchor GROUP BY token_mint
),
fin AS (SELECT token_mint, n_holders_final, n_wallets_ever, n_buyers_ever
        FROM dune.quantbino1695.result_flow_hfinal),
gp AS (SELECT token_mint, final_x FROM dune.quantbino1695.result_flow_gapin),
cr AS (
    SELECT mint, min(user) AS creator FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
ctr AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000 AS seq,
           if(t.is_buy, CAST(t.token_amount AS double),
                       -CAST(t.token_amount AS double)) AS du
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cr ON cr.mint = t.mint AND cr.creator = t.user
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
run AS (
    SELECT mint, seq, sum(du) OVER (PARTITION BY mint ORDER BY seq
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS held
    FROM ctr
),
cagg AS (SELECT mint, max(held) AS peak_units, max_by(held, seq) AS last_held
         FROM run GROUP BY mint),
cp AS (SELECT DISTINCT mint FROM pumpdotfun_solana.pump_evt_completeevent
       WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-08-15'),
j AS (
    SELECT c.token_mint, c.max_x, c.lifetime_s, c.n_ev,
           f.n_holders_final, f.n_wallets_ever, f.n_buyers_ever, g.final_x,
           CASE WHEN coalesce(a.h20,0) = 1 THEN '6_20plus'
                WHEN coalesce(a.h15,0) = 1 THEN '5_15to19'
                WHEN coalesce(a.h10,0) = 1 THEN '4_10to14'
                WHEN coalesce(a.h5,0)  = 1 THEN '3_5to9'
                WHEN coalesce(a.h3,0)  = 1 THEN '2_3to4'
                ELSE '1_lt3' END AS bin,
           (coalesce(ca.peak_units, 0) > 0
              AND coalesce(ca.last_held, 0) <= 0.10 * coalesce(ca.peak_units, 0)) AS dev_dump,
           (to_unixtime(TIMESTAMP '2026-08-15 23:59:00') - to_unixtime(c.t_last) >= 21600
              AND coalesce(c.max_x, 0.0) < 60) AS dead,
           (coalesce(c.max_x, 0.0) >= 115 OR cp.mint IS NOT NULL) AS migrated
    FROM coh c
    LEFT JOIN anch a ON a.token_mint = c.token_mint
    LEFT JOIN fin  f ON f.token_mint = c.token_mint
    LEFT JOIN gp   g ON g.token_mint = c.token_mint
    LEFT JOIN cagg ca ON ca.mint = c.token_mint
    LEFT JOIN cp   ON cp.mint = c.token_mint
)
SELECT bin, CAST(count(*) AS double) AS n,
       approx_percentile(max_x, 0.50) AS mx50, approx_percentile(max_x, 0.90) AS mx90,
       approx_percentile(max_x, 0.95) AS mx95, max(max_x) AS mxmax,
       CAST(count_if(max_x > 40) AS double)/count(*)  AS s40,
       CAST(count_if(max_x > 60) AS double)/count(*)  AS s60,
       CAST(count_if(max_x > 80) AS double)/count(*)  AS s80,
       CAST(count_if(max_x >= 115) AS double)/count(*) AS s115,
       approx_percentile(lifetime_s, 0.50) AS life50,
       approx_percentile(lifetime_s, 0.90) AS life90,
       approx_percentile(final_x, 0.50) AS fx50,
       CAST(count_if(final_x IS NOT NULL) AS double) AS n_fx,
       CAST(count_if(dev_dump) AS double)/count(*) AS s_dd,
       CAST(count_if(dead) AS double)/count(*) AS s_dead,
       CAST(count_if(dev_dump OR dead) AS double)/count(*) AS s_rug,
       CAST(count_if(migrated) AS double)/count(*) AS s_mig,
       approx_percentile(CAST(n_holders_final AS double), 0.50) AS hf50,
       approx_percentile(CAST(n_holders_final AS double), 0.90) AS hf90,
       max(n_holders_final) AS hfmax,
       approx_percentile(CAST(n_wallets_ever AS double), 0.50) AS we50,
       approx_percentile(CAST(n_wallets_ever AS double), 0.90) AS we90,
       max(n_wallets_ever) AS wemax,
       CAST(count_if(n_wallets_ever >= 50) AS double)/count(*)  AS w50,
       CAST(count_if(n_wallets_ever >= 100) AS double)/count(*) AS w100
FROM j
GROUP BY GROUPING SETS ((), (bin))
ORDER BY bin
