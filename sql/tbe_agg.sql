-- 1 + 2 + 3 -- time-based exit W in {1,5,15,30,60}, the OPEN three-way split,
-- and the three PnL conventions.
--
-- CLASSIFICATION, precedence stated:
--   CLOSED       trigger exists, next trade exists, gap <= W
--   WINDOW_EDGE  otherwise, and the reference moment is within 6 h of the data
--                edge (2026-08-16 00:00:00) -- an observation artefact, and it
--                is checked FIRST so a token cut off by the edge is never
--                counted as DEAD
--   DEAD         otherwise, and there is no next trade at all or the gap is
--                >= 6 h
--   LATE_FILL    otherwise (a trade did happen, just after the W window)
-- The reference moment is the trigger; for a token that never triggered it is
-- the LAST observed trade, since no exit condition was ever evaluated.
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР: the brief's three-way split is defined off
-- the trigger and says nothing about never-triggered positions; they are folded
-- into the same test rather than dropped, and counted separately below.
--
-- PRICING     CLOSED and LATE_FILL at the next trade's reserve (`n_x`);
--             DEAD at the last observed reserve (`x_last`);
--             WINDOW_EDGE is NEVER priced, under any convention.
--   (i)   CLOSED only
--   (ii)  CLOSED + LATE_FILL
--   (iii) CLOSED + LATE_FILL + DEAD
--
-- ret is the k-free rearrangement (parity 4.940e-57 vs cost_model.net_pnl).
-- percent_rank partitions on `(... , ret IS NULL)` so NULL rows are never ranked.
WITH sub AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_pdhist3
    WHERE wr_med IS NOT NULL AND wr_p90 IS NOT NULL
      AND wr_med >= 0.572927597 AND wr_p90 >= 1.000000000
),
b AS (
    SELECT t.*, s.token_mint IS NOT NULL AS f2,
           to_unixtime(TIMESTAMP '2026-08-16 00:00:00') AS end_ut,
           coalesce(t.trig_ut, t.ut_last) AS ref_ut,
           t.n_ut - t.trig_ut AS gap
    FROM dune.quantbino1695.result_flow_tbe t
    LEFT JOIN sub s ON s.token_mint = t.token_mint
),
u AS (
    SELECT b.*, k.w
    FROM b CROSS JOIN UNNEST(ARRAY[1, 5, 15, 30, 60]) AS k(w)
),
c AS (
    SELECT ld, f2, w, x1, gap, n_x, x_last, trig_kind,
           CASE WHEN trig_kind <> 'NONE' AND gap IS NOT NULL AND gap <= w THEN 'CLOSED'
                WHEN end_ut - ref_ut < 21600 THEN 'WINDOW_EDGE'
                WHEN trig_kind = 'NONE' OR gap IS NULL OR gap >= 21600 THEN 'DEAD'
                ELSE 'LATE_FILL' END AS cls
    FROM u
),
p AS (
    SELECT ld, f2, w, cls, gap, trig_kind,
           CASE WHEN cls = 'CLOSED' THEN n_x END                        AS xe1,
           CASE WHEN cls IN ('CLOSED','LATE_FILL') THEN n_x END          AS xe2,
           CASE WHEN cls = 'DEAD' THEN x_last
                WHEN cls IN ('CLOSED','LATE_FILL') THEN n_x END          AS xe3,
           x1
    FROM c
),
r AS (
    SELECT ld, f2, w, cls, gap, trig_kind, x1,
           if(xe1 IS NOT NULL, ((0.5*(xe1+0.5)*(xe1+0.5)/(x1*(x1+0.5)+0.5*(xe1+0.5)))*0.9875 - 0.5/0.9875 - 0.002)/0.5) AS r1,
           if(xe2 IS NOT NULL, ((0.5*(xe2+0.5)*(xe2+0.5)/(x1*(x1+0.5)+0.5*(xe2+0.5)))*0.9875 - 0.5/0.9875 - 0.002)/0.5) AS r2,
           if(xe3 IS NOT NULL, ((0.5*(xe3+0.5)*(xe3+0.5)/(x1*(x1+0.5)+0.5*(xe3+0.5)))*0.9875 - 0.5/0.9875 - 0.002)/0.5) AS r3
    FROM p
),
k AS (
    SELECT r.*,
           percent_rank() OVER (PARTITION BY w, (r1 IS NULL) ORDER BY r1)      AS a1,
           percent_rank() OVER (PARTITION BY w, (r2 IS NULL) ORDER BY r2)      AS a2,
           percent_rank() OVER (PARTITION BY w, (r3 IS NULL) ORDER BY r3)      AS a3,
           percent_rank() OVER (PARTITION BY w, f2, (r1 IS NULL) ORDER BY r1)  AS s1,
           percent_rank() OVER (PARTITION BY w, f2, (r2 IS NULL) ORDER BY r2)  AS s2,
           percent_rank() OVER (PARTITION BY w, f2, (r3 IS NULL) ORDER BY r3)  AS s3
    FROM r
)
SELECT w, f2, ld, CAST(grouping(w, f2, ld) AS integer) AS gset,
       CAST(count(*) AS double)                        AS n,
       CAST(count_if(cls='CLOSED') AS double)          AS n_cl,
       CAST(count_if(cls='LATE_FILL') AS double)       AS n_lf,
       CAST(count_if(cls='DEAD') AS double)            AS n_dead,
       CAST(count_if(cls='WINDOW_EDGE') AS double)     AS n_edge,
       CAST(count_if(trig_kind='NONE') AS double)      AS n_notrig,
       approx_percentile(if(cls='CLOSED', gap), 0.50)  AS gap50,
       approx_percentile(if(cls='CLOSED', gap), 0.90)  AS gap90,
       approx_percentile(if(cls='LATE_FILL', gap), 0.50) AS lgap50,
       sum(r1) AS s1, CAST(count(r1) AS double) AS n1, CAST(count_if(r1>0) AS double) AS p1,
       sum(r2) AS s2, CAST(count(r2) AS double) AS n2, CAST(count_if(r2>0) AS double) AS p2,
       sum(r3) AS s3, CAST(count(r3) AS double) AS n3, CAST(count_if(r3>0) AS double) AS p3,
       approx_percentile(r1, 0.50) AS m1, approx_percentile(r2, 0.50) AS m2,
       approx_percentile(r3, 0.50) AS m3,
       sum(if(a1>0.01 AND a1<0.99, r1))/nullif(CAST(count_if(r1 IS NOT NULL AND a1>0.01 AND a1<0.99) AS double),0) AS A1t1,
       sum(if(a1>0.05 AND a1<0.95, r1))/nullif(CAST(count_if(r1 IS NOT NULL AND a1>0.05 AND a1<0.95) AS double),0) AS A1t5,
       sum(if(a1>0.10 AND a1<0.90, r1))/nullif(CAST(count_if(r1 IS NOT NULL AND a1>0.10 AND a1<0.90) AS double),0) AS A1t10,
       sum(if(a3>0.01 AND a3<0.99, r3))/nullif(CAST(count_if(r3 IS NOT NULL AND a3>0.01 AND a3<0.99) AS double),0) AS A3t1,
       sum(if(a3>0.05 AND a3<0.95, r3))/nullif(CAST(count_if(r3 IS NOT NULL AND a3>0.05 AND a3<0.95) AS double),0) AS A3t5,
       sum(if(a3>0.10 AND a3<0.90, r3))/nullif(CAST(count_if(r3 IS NOT NULL AND a3>0.10 AND a3<0.90) AS double),0) AS A3t10,
       sum(if(a2>0.05 AND a2<0.95, r2))/nullif(CAST(count_if(r2 IS NOT NULL AND a2>0.05 AND a2<0.95) AS double),0) AS A2t5,
       sum(if(s1>0.01 AND s1<0.99, r1))/nullif(CAST(count_if(r1 IS NOT NULL AND s1>0.01 AND s1<0.99) AS double),0) AS S1t1,
       sum(if(s1>0.05 AND s1<0.95, r1))/nullif(CAST(count_if(r1 IS NOT NULL AND s1>0.05 AND s1<0.95) AS double),0) AS S1t5,
       sum(if(s1>0.10 AND s1<0.90, r1))/nullif(CAST(count_if(r1 IS NOT NULL AND s1>0.10 AND s1<0.90) AS double),0) AS S1t10,
       sum(if(s3>0.01 AND s3<0.99, r3))/nullif(CAST(count_if(r3 IS NOT NULL AND s3>0.01 AND s3<0.99) AS double),0) AS S3t1,
       sum(if(s3>0.05 AND s3<0.95, r3))/nullif(CAST(count_if(r3 IS NOT NULL AND s3>0.05 AND s3<0.95) AS double),0) AS S3t5,
       sum(if(s3>0.10 AND s3<0.90, r3))/nullif(CAST(count_if(r3 IS NOT NULL AND s3>0.10 AND s3<0.90) AS double),0) AS S3t10,
       sum(if(s2>0.05 AND s2<0.95, r2))/nullif(CAST(count_if(r2 IS NOT NULL AND s2>0.05 AND s2<0.95) AS double),0) AS S2t5
FROM k GROUP BY GROUPING SETS ((w), (w, f2), (w, ld), (w, f2, ld))
