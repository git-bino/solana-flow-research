-- 3 -- FIRST PASSAGE.  Which came first, the target or the stop.
--
-- ORDERING IS ON SLOT, as the task requires, because `x` is not monotone in
-- slot.  The SAME-SLOT case -- target and stop first touched in the same slot --
-- is counted in its OWN bucket and is never broken by a tiebreak.
--
-- CENSORING IS EXPLICIT.  A row where neither side was ever touched inside the
-- event window is `censored`.  It is never replaced by zero and never counted as
-- a loss.  win + loss + same_slot + censored = 1 by construction.
--
-- Anchors: H3/H5/H10/H15/H20 (holder count) and X60 (x >= 60), all built by the
-- same clock in the same execution, so the X60 comparison line is like-for-like.
WITH hp AS (
    SELECT * FROM dune.quantbino1695.result_flow_hpath_a
    UNION ALL SELECT * FROM dune.quantbino1695.result_flow_hpath_b
)
SELECT anchor_kind, '+20%' AS target, '-20%' AS stop,
       CAST(count(*) AS double) AS n,
       CAST(count_if(sl_g20 IS NOT NULL AND (sl_l20 IS NULL OR sl_g20 < sl_l20)) AS double)/count(*) AS win,
       CAST(count_if(sl_l20 IS NOT NULL AND (sl_g20 IS NULL OR sl_l20 < sl_g20)) AS double)/count(*) AS loss,
       CAST(count_if(sl_g20 IS NOT NULL AND sl_l20 IS NOT NULL AND sl_g20 = sl_l20) AS double)/count(*) AS same_slot,
       CAST(count_if(sl_g20 IS NULL AND sl_l20 IS NULL) AS double)/count(*) AS censored,
       approx_percentile(if(sl_g20 IS NOT NULL AND (sl_l20 IS NULL OR sl_g20 < sl_l20), t_g20_s), 0.50) AS t_win_p50,
       approx_percentile(if(sl_g20 IS NOT NULL AND (sl_l20 IS NULL OR sl_g20 < sl_l20), t_g20_s), 0.90) AS t_win_p90,
       approx_percentile(if(sl_l20 IS NOT NULL AND (sl_g20 IS NULL OR sl_l20 < sl_g20), t_l20_s), 0.50) AS t_loss_p50,
       approx_percentile(if(sl_l20 IS NOT NULL AND (sl_g20 IS NULL OR sl_l20 < sl_g20), t_l20_s), 0.90) AS t_loss_p90
FROM hp GROUP BY anchor_kind
UNION ALL
SELECT anchor_kind, '+20%' AS target, '-30%' AS stop,
       CAST(count(*) AS double) AS n,
       CAST(count_if(sl_g20 IS NOT NULL AND (sl_l30 IS NULL OR sl_g20 < sl_l30)) AS double)/count(*) AS win,
       CAST(count_if(sl_l30 IS NOT NULL AND (sl_g20 IS NULL OR sl_l30 < sl_g20)) AS double)/count(*) AS loss,
       CAST(count_if(sl_g20 IS NOT NULL AND sl_l30 IS NOT NULL AND sl_g20 = sl_l30) AS double)/count(*) AS same_slot,
       CAST(count_if(sl_g20 IS NULL AND sl_l30 IS NULL) AS double)/count(*) AS censored,
       approx_percentile(if(sl_g20 IS NOT NULL AND (sl_l30 IS NULL OR sl_g20 < sl_l30), t_g20_s), 0.50) AS t_win_p50,
       approx_percentile(if(sl_g20 IS NOT NULL AND (sl_l30 IS NULL OR sl_g20 < sl_l30), t_g20_s), 0.90) AS t_win_p90,
       approx_percentile(if(sl_l30 IS NOT NULL AND (sl_g20 IS NULL OR sl_l30 < sl_g20), t_l30_s), 0.50) AS t_loss_p50,
       approx_percentile(if(sl_l30 IS NOT NULL AND (sl_g20 IS NULL OR sl_l30 < sl_g20), t_l30_s), 0.90) AS t_loss_p90
FROM hp GROUP BY anchor_kind
UNION ALL
SELECT anchor_kind, '+20%' AS target, '-50%' AS stop,
       CAST(count(*) AS double) AS n,
       CAST(count_if(sl_g20 IS NOT NULL AND (sl_l50 IS NULL OR sl_g20 < sl_l50)) AS double)/count(*) AS win,
       CAST(count_if(sl_l50 IS NOT NULL AND (sl_g20 IS NULL OR sl_l50 < sl_g20)) AS double)/count(*) AS loss,
       CAST(count_if(sl_g20 IS NOT NULL AND sl_l50 IS NOT NULL AND sl_g20 = sl_l50) AS double)/count(*) AS same_slot,
       CAST(count_if(sl_g20 IS NULL AND sl_l50 IS NULL) AS double)/count(*) AS censored,
       approx_percentile(if(sl_g20 IS NOT NULL AND (sl_l50 IS NULL OR sl_g20 < sl_l50), t_g20_s), 0.50) AS t_win_p50,
       approx_percentile(if(sl_g20 IS NOT NULL AND (sl_l50 IS NULL OR sl_g20 < sl_l50), t_g20_s), 0.90) AS t_win_p90,
       approx_percentile(if(sl_l50 IS NOT NULL AND (sl_g20 IS NULL OR sl_l50 < sl_g20), t_l50_s), 0.50) AS t_loss_p50,
       approx_percentile(if(sl_l50 IS NOT NULL AND (sl_g20 IS NULL OR sl_l50 < sl_g20), t_l50_s), 0.90) AS t_loss_p90
FROM hp GROUP BY anchor_kind
UNION ALL
SELECT anchor_kind, '+36%' AS target, '-20%' AS stop,
       CAST(count(*) AS double) AS n,
       CAST(count_if(sl_g36 IS NOT NULL AND (sl_l20 IS NULL OR sl_g36 < sl_l20)) AS double)/count(*) AS win,
       CAST(count_if(sl_l20 IS NOT NULL AND (sl_g36 IS NULL OR sl_l20 < sl_g36)) AS double)/count(*) AS loss,
       CAST(count_if(sl_g36 IS NOT NULL AND sl_l20 IS NOT NULL AND sl_g36 = sl_l20) AS double)/count(*) AS same_slot,
       CAST(count_if(sl_g36 IS NULL AND sl_l20 IS NULL) AS double)/count(*) AS censored,
       approx_percentile(if(sl_g36 IS NOT NULL AND (sl_l20 IS NULL OR sl_g36 < sl_l20), t_g36_s), 0.50) AS t_win_p50,
       approx_percentile(if(sl_g36 IS NOT NULL AND (sl_l20 IS NULL OR sl_g36 < sl_l20), t_g36_s), 0.90) AS t_win_p90,
       approx_percentile(if(sl_l20 IS NOT NULL AND (sl_g36 IS NULL OR sl_l20 < sl_g36), t_l20_s), 0.50) AS t_loss_p50,
       approx_percentile(if(sl_l20 IS NOT NULL AND (sl_g36 IS NULL OR sl_l20 < sl_g36), t_l20_s), 0.90) AS t_loss_p90
FROM hp GROUP BY anchor_kind
UNION ALL
SELECT anchor_kind, '+36%' AS target, '-30%' AS stop,
       CAST(count(*) AS double) AS n,
       CAST(count_if(sl_g36 IS NOT NULL AND (sl_l30 IS NULL OR sl_g36 < sl_l30)) AS double)/count(*) AS win,
       CAST(count_if(sl_l30 IS NOT NULL AND (sl_g36 IS NULL OR sl_l30 < sl_g36)) AS double)/count(*) AS loss,
       CAST(count_if(sl_g36 IS NOT NULL AND sl_l30 IS NOT NULL AND sl_g36 = sl_l30) AS double)/count(*) AS same_slot,
       CAST(count_if(sl_g36 IS NULL AND sl_l30 IS NULL) AS double)/count(*) AS censored,
       approx_percentile(if(sl_g36 IS NOT NULL AND (sl_l30 IS NULL OR sl_g36 < sl_l30), t_g36_s), 0.50) AS t_win_p50,
       approx_percentile(if(sl_g36 IS NOT NULL AND (sl_l30 IS NULL OR sl_g36 < sl_l30), t_g36_s), 0.90) AS t_win_p90,
       approx_percentile(if(sl_l30 IS NOT NULL AND (sl_g36 IS NULL OR sl_l30 < sl_g36), t_l30_s), 0.50) AS t_loss_p50,
       approx_percentile(if(sl_l30 IS NOT NULL AND (sl_g36 IS NULL OR sl_l30 < sl_g36), t_l30_s), 0.90) AS t_loss_p90
FROM hp GROUP BY anchor_kind
UNION ALL
SELECT anchor_kind, '+36%' AS target, '-50%' AS stop,
       CAST(count(*) AS double) AS n,
       CAST(count_if(sl_g36 IS NOT NULL AND (sl_l50 IS NULL OR sl_g36 < sl_l50)) AS double)/count(*) AS win,
       CAST(count_if(sl_l50 IS NOT NULL AND (sl_g36 IS NULL OR sl_l50 < sl_g36)) AS double)/count(*) AS loss,
       CAST(count_if(sl_g36 IS NOT NULL AND sl_l50 IS NOT NULL AND sl_g36 = sl_l50) AS double)/count(*) AS same_slot,
       CAST(count_if(sl_g36 IS NULL AND sl_l50 IS NULL) AS double)/count(*) AS censored,
       approx_percentile(if(sl_g36 IS NOT NULL AND (sl_l50 IS NULL OR sl_g36 < sl_l50), t_g36_s), 0.50) AS t_win_p50,
       approx_percentile(if(sl_g36 IS NOT NULL AND (sl_l50 IS NULL OR sl_g36 < sl_l50), t_g36_s), 0.90) AS t_win_p90,
       approx_percentile(if(sl_l50 IS NOT NULL AND (sl_g36 IS NULL OR sl_l50 < sl_g36), t_l50_s), 0.50) AS t_loss_p50,
       approx_percentile(if(sl_l50 IS NOT NULL AND (sl_g36 IS NULL OR sl_l50 < sl_g36), t_l50_s), 0.90) AS t_loss_p90
FROM hp GROUP BY anchor_kind
ORDER BY anchor_kind, target, stop
