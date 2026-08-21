-- 1 + 2 -- the 84-cell exit grid.  T x S x G = 7 x 4 x 3, on H15 and H20,
-- CLEAN universe only.
--
-- Whichever condition fires FIRST decides the exit.  Ties (two conditions met by
-- the SAME event) resolve stop > target > time for the REASON label only -- the
-- price is identical either way, because the delayed fill is the 3rd event after
-- that same trigger event.
--
-- OVERSHOOT: every exit uses the reserve the fill event LEFT, never the
-- threshold.  A trigger with fewer than 3 events after it falls back to the
-- observed `final_x` (still open at the window edge).
--
-- TIME ALREADY EXPIRED AT ENTRY (`ut_entry > anchor + T`) counts as NOT TRADED
-- for that T and is reported separately, not priced.
--
-- Fee 1.25% PER SIDE, cost_model's exact path, q in {0.05, 0.5}.  The fixed
-- cost enters as `2*fixed/q` and is applied afterwards, so it needs no column.
WITH e AS (
    SELECT en.token_mint, en.anchor_kind, en.x_a, en.anchor_unix, en.x_entry,
           en.ut_entry, en.seq_entry, en.final_x,
           tr.s95, tr.s90, tr.s85, tr.g60, tr.g70, tr.g15,
           tr.xt10, tr.xt16, tr.xt20, tr.xt30, tr.xt45, tr.xt60,
           tr.qt10, tr.qt16, tr.qt20, tr.qt30, tr.qt45, tr.qt60,
           dl.x95, dl.x90, dl.x85, dl.xg60, dl.xg70, dl.xg15,
           tb.ld
    FROM dune.quantbino1695.result_flow_eg_entry en
    JOIN dune.quantbino1695.result_flow_eg_trig tr
      ON tr.token_mint = en.token_mint AND tr.anchor_kind = en.anchor_kind
    LEFT JOIN dune.quantbino1695.result_flow_eg_delay dl
      ON dl.token_mint = en.token_mint AND dl.anchor_kind = en.anchor_kind
    JOIN (SELECT token_mint, date(launch_time) AS ld
          FROM dune.quantbino1695.result_flow_token_base) tb
      ON tb.token_mint = en.token_mint
    WHERE en.seq_entry IS NOT NULL AND en.x_entry IS NOT NULL
),
p AS (
    SELECT e.token_mint, e.anchor_kind, e.ld, e.x_a, e.x_entry, e.final_x,
           e.ut_entry, e.anchor_unix,
           u.lab, u.t_sec, u.t_seq, u.t_px, u.s_seq, u.s_px, u.g_seq, u.g_px
    FROM e CROSS JOIN UNNEST(ARRAY[

        ROW('T10_S95_x60', 10.0, qt10, xt10, s95, x95, g60, xg60),
        ROW('T10_S95_x70', 10.0, qt10, xt10, s95, x95, g70, xg70),
        ROW('T10_S95_xa15', 10.0, qt10, xt10, s95, x95, g15, xg15),
        ROW('T10_S90_x60', 10.0, qt10, xt10, s90, x90, g60, xg60),
        ROW('T10_S90_x70', 10.0, qt10, xt10, s90, x90, g70, xg70),
        ROW('T10_S90_xa15', 10.0, qt10, xt10, s90, x90, g15, xg15),
        ROW('T10_S85_x60', 10.0, qt10, xt10, s85, x85, g60, xg60),
        ROW('T10_S85_x70', 10.0, qt10, xt10, s85, x85, g70, xg70),
        ROW('T10_S85_xa15', 10.0, qt10, xt10, s85, x85, g15, xg15),
        ROW('T10_Sinf_x60', 10.0, qt10, xt10, CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60),
        ROW('T10_Sinf_x70', 10.0, qt10, xt10, CAST(NULL AS bigint), CAST(NULL AS double), g70, xg70),
        ROW('T10_Sinf_xa15', 10.0, qt10, xt10, CAST(NULL AS bigint), CAST(NULL AS double), g15, xg15),
        ROW('T16_S95_x60', 16.0, qt16, xt16, s95, x95, g60, xg60),
        ROW('T16_S95_x70', 16.0, qt16, xt16, s95, x95, g70, xg70),
        ROW('T16_S95_xa15', 16.0, qt16, xt16, s95, x95, g15, xg15),
        ROW('T16_S90_x60', 16.0, qt16, xt16, s90, x90, g60, xg60),
        ROW('T16_S90_x70', 16.0, qt16, xt16, s90, x90, g70, xg70),
        ROW('T16_S90_xa15', 16.0, qt16, xt16, s90, x90, g15, xg15),
        ROW('T16_S85_x60', 16.0, qt16, xt16, s85, x85, g60, xg60),
        ROW('T16_S85_x70', 16.0, qt16, xt16, s85, x85, g70, xg70),
        ROW('T16_S85_xa15', 16.0, qt16, xt16, s85, x85, g15, xg15),
        ROW('T16_Sinf_x60', 16.0, qt16, xt16, CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60),
        ROW('T16_Sinf_x70', 16.0, qt16, xt16, CAST(NULL AS bigint), CAST(NULL AS double), g70, xg70),
        ROW('T16_Sinf_xa15', 16.0, qt16, xt16, CAST(NULL AS bigint), CAST(NULL AS double), g15, xg15),
        ROW('T20_S95_x60', 20.0, qt20, xt20, s95, x95, g60, xg60),
        ROW('T20_S95_x70', 20.0, qt20, xt20, s95, x95, g70, xg70),
        ROW('T20_S95_xa15', 20.0, qt20, xt20, s95, x95, g15, xg15),
        ROW('T20_S90_x60', 20.0, qt20, xt20, s90, x90, g60, xg60),
        ROW('T20_S90_x70', 20.0, qt20, xt20, s90, x90, g70, xg70),
        ROW('T20_S90_xa15', 20.0, qt20, xt20, s90, x90, g15, xg15),
        ROW('T20_S85_x60', 20.0, qt20, xt20, s85, x85, g60, xg60),
        ROW('T20_S85_x70', 20.0, qt20, xt20, s85, x85, g70, xg70),
        ROW('T20_S85_xa15', 20.0, qt20, xt20, s85, x85, g15, xg15),
        ROW('T20_Sinf_x60', 20.0, qt20, xt20, CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60),
        ROW('T20_Sinf_x70', 20.0, qt20, xt20, CAST(NULL AS bigint), CAST(NULL AS double), g70, xg70),
        ROW('T20_Sinf_xa15', 20.0, qt20, xt20, CAST(NULL AS bigint), CAST(NULL AS double), g15, xg15),
        ROW('T30_S95_x60', 30.0, qt30, xt30, s95, x95, g60, xg60),
        ROW('T30_S95_x70', 30.0, qt30, xt30, s95, x95, g70, xg70),
        ROW('T30_S95_xa15', 30.0, qt30, xt30, s95, x95, g15, xg15),
        ROW('T30_S90_x60', 30.0, qt30, xt30, s90, x90, g60, xg60),
        ROW('T30_S90_x70', 30.0, qt30, xt30, s90, x90, g70, xg70),
        ROW('T30_S90_xa15', 30.0, qt30, xt30, s90, x90, g15, xg15),
        ROW('T30_S85_x60', 30.0, qt30, xt30, s85, x85, g60, xg60),
        ROW('T30_S85_x70', 30.0, qt30, xt30, s85, x85, g70, xg70),
        ROW('T30_S85_xa15', 30.0, qt30, xt30, s85, x85, g15, xg15),
        ROW('T30_Sinf_x60', 30.0, qt30, xt30, CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60),
        ROW('T30_Sinf_x70', 30.0, qt30, xt30, CAST(NULL AS bigint), CAST(NULL AS double), g70, xg70),
        ROW('T30_Sinf_xa15', 30.0, qt30, xt30, CAST(NULL AS bigint), CAST(NULL AS double), g15, xg15),
        ROW('T45_S95_x60', 45.0, qt45, xt45, s95, x95, g60, xg60),
        ROW('T45_S95_x70', 45.0, qt45, xt45, s95, x95, g70, xg70),
        ROW('T45_S95_xa15', 45.0, qt45, xt45, s95, x95, g15, xg15),
        ROW('T45_S90_x60', 45.0, qt45, xt45, s90, x90, g60, xg60),
        ROW('T45_S90_x70', 45.0, qt45, xt45, s90, x90, g70, xg70),
        ROW('T45_S90_xa15', 45.0, qt45, xt45, s90, x90, g15, xg15),
        ROW('T45_S85_x60', 45.0, qt45, xt45, s85, x85, g60, xg60),
        ROW('T45_S85_x70', 45.0, qt45, xt45, s85, x85, g70, xg70),
        ROW('T45_S85_xa15', 45.0, qt45, xt45, s85, x85, g15, xg15),
        ROW('T45_Sinf_x60', 45.0, qt45, xt45, CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60),
        ROW('T45_Sinf_x70', 45.0, qt45, xt45, CAST(NULL AS bigint), CAST(NULL AS double), g70, xg70),
        ROW('T45_Sinf_xa15', 45.0, qt45, xt45, CAST(NULL AS bigint), CAST(NULL AS double), g15, xg15),
        ROW('T60_S95_x60', 60.0, qt60, xt60, s95, x95, g60, xg60),
        ROW('T60_S95_x70', 60.0, qt60, xt60, s95, x95, g70, xg70),
        ROW('T60_S95_xa15', 60.0, qt60, xt60, s95, x95, g15, xg15),
        ROW('T60_S90_x60', 60.0, qt60, xt60, s90, x90, g60, xg60),
        ROW('T60_S90_x70', 60.0, qt60, xt60, s90, x90, g70, xg70),
        ROW('T60_S90_xa15', 60.0, qt60, xt60, s90, x90, g15, xg15),
        ROW('T60_S85_x60', 60.0, qt60, xt60, s85, x85, g60, xg60),
        ROW('T60_S85_x70', 60.0, qt60, xt60, s85, x85, g70, xg70),
        ROW('T60_S85_xa15', 60.0, qt60, xt60, s85, x85, g15, xg15),
        ROW('T60_Sinf_x60', 60.0, qt60, xt60, CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60),
        ROW('T60_Sinf_x70', 60.0, qt60, xt60, CAST(NULL AS bigint), CAST(NULL AS double), g70, xg70),
        ROW('T60_Sinf_xa15', 60.0, qt60, xt60, CAST(NULL AS bigint), CAST(NULL AS double), g15, xg15),
        ROW('Tinf_S95_x60', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s95, x95, g60, xg60),
        ROW('Tinf_S95_x70', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s95, x95, g70, xg70),
        ROW('Tinf_S95_xa15', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s95, x95, g15, xg15),
        ROW('Tinf_S90_x60', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s90, x90, g60, xg60),
        ROW('Tinf_S90_x70', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s90, x90, g70, xg70),
        ROW('Tinf_S90_xa15', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s90, x90, g15, xg15),
        ROW('Tinf_S85_x60', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s85, x85, g60, xg60),
        ROW('Tinf_S85_x70', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s85, x85, g70, xg70),
        ROW('Tinf_S85_xa15', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), s85, x85, g15, xg15),
        ROW('Tinf_Sinf_x60', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60),
        ROW('Tinf_Sinf_x70', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), g70, xg70),
        ROW('Tinf_Sinf_xa15', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), g15, xg15)
    ]) AS u(lab, t_sec, t_seq, t_px, s_seq, s_px, g_seq, g_px)
),
o AS (
    SELECT p.*,
           (t_sec IS NOT NULL AND ut_entry > anchor_unix + t_sec) AS expired,
           least(coalesce(t_seq, 9223372036854775807),
                 coalesce(s_seq, 9223372036854775807),
                 coalesce(g_seq, 9223372036854775807))            AS win_seq
    FROM p
),
v AS (
    SELECT o.*,
           CASE WHEN expired THEN 'not_traded'
                WHEN win_seq = 9223372036854775807 THEN 'held_to_end'
                WHEN s_seq IS NOT NULL AND s_seq = win_seq THEN 'stop'
                WHEN g_seq IS NOT NULL AND g_seq = win_seq THEN 'target'
                ELSE 'time' END AS reason,
           CASE WHEN expired THEN NULL
                WHEN win_seq = 9223372036854775807 THEN final_x
                WHEN s_seq IS NOT NULL AND s_seq = win_seq THEN coalesce(s_px, final_x)
                WHEN g_seq IS NOT NULL AND g_seq = win_seq THEN coalesce(g_px, final_x)
                ELSE coalesce(t_px, final_x) END AS x_exit
    FROM o
),
r AS (
    SELECT v.*,
           CASE WHEN x_exit IS NULL THEN NULL ELSE ((((32190000000.0 * 0.05 / (x_entry * (x_entry + 0.05))) * (x_exit + 0.05) * (x_exit + 0.05) / (32190000000.0 + (32190000000.0 * 0.05 / (x_entry * (x_entry + 0.05))) * (x_exit + 0.05))) * (1 - 0.0125) - 0.05 / (1 - 0.0125)) / 0.05) END AS r005,
           CASE WHEN x_exit IS NULL THEN NULL ELSE ((((32190000000.0 * 0.5 / (x_entry * (x_entry + 0.5))) * (x_exit + 0.5) * (x_exit + 0.5) / (32190000000.0 + (32190000000.0 * 0.5 / (x_entry * (x_entry + 0.5))) * (x_exit + 0.5))) * (1 - 0.0125) - 0.5 / (1 - 0.0125)) / 0.5)  END AS r050
    FROM v
),
w AS (
    SELECT r.*, percent_rank() OVER (PARTITION BY anchor_kind, lab, (r050 IS NULL)
                                     ORDER BY r050) AS pr
    FROM r
)
SELECT anchor_kind, lab, CAST(ld AS varchar) AS ld,
       CAST(count(*) AS double) AS n,
       CAST(count_if(reason = 'target') AS double)/count(*)      AS s_target,
       CAST(count_if(reason = 'stop') AS double)/count(*)        AS s_stop,
       CAST(count_if(reason = 'time') AS double)/count(*)        AS s_time,
       CAST(count_if(reason = 'held_to_end') AS double)/count(*) AS s_held,
       CAST(count_if(reason = 'not_traded') AS double)/count(*)  AS s_nt,
       avg(if(reason = 'target', x_exit / x_a)) AS xr_target,
       avg(if(reason = 'stop',   x_exit / x_a)) AS xr_stop,
       avg(if(reason = 'time',   x_exit / x_a)) AS xr_time,
       avg(if(reason = 'held_to_end', x_exit / x_a)) AS xr_held,
       sum(r050) AS s_r050,
       avg(r005) AS m005, avg(r050) AS m050,
       approx_percentile(r050, 0.50) AS med050,
       avg(if(pr < 0.99 AND r050 IS NOT NULL, r050)) AS trim01,
       avg(if(pr < 0.95 AND r050 IS NOT NULL, r050)) AS trim05,
       avg(if(pr < 0.90 AND r050 IS NOT NULL, r050)) AS trim10,
       CAST(count_if(r050 > 0) AS double)/nullif(count_if(r050 IS NOT NULL),0) AS pos
FROM w
GROUP BY GROUPING SETS ((anchor_kind, lab), (anchor_kind, lab, ld))
ORDER BY anchor_kind, lab, ld
