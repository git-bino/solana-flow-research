-- Audit 3, defect 2 -- three exit conventions side by side.
--
-- (a) CURRENT: target crossing + 3 trades if hit, otherwise `final_x` -- the
--     token's LAST trade.  Not knowable when a trader would have to act.
-- (b) FIXED HORIZON H: exit at the target if it was hit BEFORE H, otherwise at
--     the reserve on the last trade at or before anchor + H.  Realtime-observable.
--     A token whose last trade falls before H is DEAD inside the horizon; that
--     case is valued BOTH ways and both are reported:
--       "сүүлийн x"  -- exit at the last observed reserve
--       "тэглэх"     -- proceeds are zero, so ret = -1/(1-f) = -101.27%
--     A token whose ENTRY (3rd trade after the anchor) falls after H cannot be
--     opened inside that horizon at all: NOT TRADED, counted separately.
-- (c) CLOSED ONLY: positions that never hit the target are EXCLUDED from
--     realized P&L and only counted.
--
-- `mh` = launch-time mayhem, carried through so defect 1 stays visible.
WITH ce AS (
    SELECT mint, bool_or(is_mayhem_mode) AS mayhem_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
tb AS (SELECT token_mint FROM dune.quantbino1695.result_flow_token_base),
coh AS (SELECT tb.token_mint, coalesce(ce.mayhem_launch, false) AS mh
        FROM tb LEFT JOIN ce ON ce.mint = tb.token_mint),
gi AS (SELECT token_mint, x_a, t_a_s, x_e3, t_e3, final_x, t_final_s, seq_u76
       FROM dune.quantbino1695.result_flow_gapin),
go AS (SELECT token_mint, x76_e3 FROM dune.quantbino1695.result_flow_gapout),
hb AS (SELECT token_mint, x_u76, t_u76 FROM dune.quantbino1695.result_flow_hbar),
hz AS (SELECT token_mint, x_h1, x_h6, x_h24 FROM dune.quantbino1695.result_flow_horizon),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
j AS (
    SELECT gi.*, go.x76_e3, hb.x_u76, hb.t_u76, hz.x_h1, hz.x_h6, hz.x_h24,
           hf.f_gini, hf.f_creator, coh.mh
    FROM gi JOIN hf ON hf.token_mint = gi.token_mint
            JOIN hb ON hb.token_mint = gi.token_mint
            JOIN coh ON coh.token_mint = gi.token_mint
            LEFT JOIN go ON go.token_mint = gi.token_mint
            LEFT JOIN hz ON hz.token_mint = gi.token_mint
),
rk AS (
    SELECT j.*,
           CAST(rank() OVER (ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_gini) AS double) - 1)/2.0 AS mg,
           CAST(rank() OVER (ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_creator) AS double) - 1)/2.0 AS mc,
           CAST(count(*) OVER () AS double) AS n_tot
    FROM j
),
lab AS (
    SELECT rk.*,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 3 THEN 'x' WHEN t_a_s < 10 THEN '3_3to10s'
                ELSE '4_gt10s' END AS tbk
    FROM rk
),
cellrows AS (
    SELECT lab.* FROM lab
    WHERE lab.tbk <> 'x' AND (lab.g3 = 1 OR lab.c3 = 1)
),
p AS (
    SELECT c.*, u.variant, u.h, u.zero_dead, u.closed_only
    FROM cellrows c CROSS JOIN UNNEST(ARRAY[

        ROW('a  final_x (одоогийн)', CAST(NULL AS double), false, false),
        ROW('b  H=1ц  сүүлийн x', 3600.0, false, false),
        ROW('b  H=1ц  тэглэх',    3600.0, true,  false),
        ROW('b  H=6ц  сүүлийн x', 21600.0, false, false),
        ROW('b  H=6ц  тэглэх',    21600.0, true,  false),
        ROW('b  H=24ц  сүүлийн x', 86400.0, false, false),
        ROW('b  H=24ц  тэглэх',    86400.0, true,  false),
        ROW('c  хаагдсан нь л', CAST(NULL AS double), false, true)
    ]) AS u(variant, h, zero_dead, closed_only)
),
o AS (
    SELECT p.*,
           (h IS NOT NULL AND t_e3 > h)                               AS entry_after_h,
           (seq_u76 IS NOT NULL AND (h IS NULL OR t_u76 <= h))        AS closed,
           (h IS NOT NULL AND t_final_s < h)                          AS dead_in_h,
           CASE WHEN h IS NULL THEN NULL
                WHEN h = 3600.0 THEN x_h1
                WHEN h = 21600.0 THEN x_h6
                ELSE x_h24 END                                        AS x_at_h
    FROM p
),
v AS (
    SELECT o.*,
           CASE
             WHEN x_e3 IS NULL THEN NULL
             WHEN entry_after_h THEN NULL
             WHEN closed_only AND NOT closed THEN NULL
             WHEN closed THEN coalesce(x76_e3, final_x)
             WHEN h IS NULL THEN final_x
             ELSE coalesce(x_at_h, final_x) END                       AS x_out,
           (x_e3 IS NOT NULL AND NOT entry_after_h
              AND NOT (closed_only AND NOT closed)
              AND NOT closed AND zero_dead AND dead_in_h)             AS is_zero
    FROM o
),
e AS (
    SELECT v.*,
           CASE WHEN x_out IS NULL THEN NULL
                WHEN is_zero THEN -1.0 / (1 - 0.0125)
                ELSE ((((32190000000.0 * 1.0 / (x_e3 * (x_e3 + 1.0))) * (x_out + 1.0) * (x_out + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_e3 * (x_e3 + 1.0))) * (x_out + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) END AS ret
    FROM v
),
w AS (SELECT e.*, percent_rank() OVER (PARTITION BY variant, mh, (ret IS NULL)
                                       ORDER BY ret) AS pr FROM e)
SELECT variant, mh,
       CAST(count(*) AS double) AS n,
       CAST(count_if(ret IS NULL) AS double) AS n_excluded,
       CAST(count_if(closed) AS double)/count(*) AS share_closed,
       CAST(count_if(NOT closed) AS double)/count(*) AS share_open,
       CAST(count_if(is_zero) AS double)/count(*) AS share_zeroed,
       avg(ret) AS mean_ret,
       approx_percentile(ret, 0.50) AS median_ret,
       avg(if(pr < 0.95 AND ret IS NOT NULL, ret)) AS trim05,
       CAST(count_if(ret > 0) AS double)/nullif(count_if(ret IS NOT NULL),0) AS pos
FROM w GROUP BY variant, mh
ORDER BY variant, mh
