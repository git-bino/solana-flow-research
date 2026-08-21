-- 1 -- forward path with REALISTIC EXECUTION for the 45-combination exit grid.
--
-- CLEAN universe only, H20 anchor, x_a = reserve AFTER the anchor event.
--
-- ENTRY: the 3rd event after the anchor.  EXIT: the 3rd event at or after the
-- moment a condition first holds.  Both are implemented with ONE window,
-- `lead(x, 3)`, so the "price 3 events later" is attached to every event and the
-- exit price of any trigger is just that column read at the trigger event.  This
-- is the OVERSHOOT price -- the reserve actually standing after the fill -- not
-- the price at which the condition was met.
--
-- Triggers, all evaluated strictly AFTER the entry event:
--   time    ut - anchor_unix >= T   for T in {10, 20, 30, 60} s
--   stop    x <= x_a * S            for S in {0.90, 0.85}
--   target  x >= 60, x >= 1.5*x_a, x >= 2.0*x_a
-- T = infinity and S = infinity are not stored; they are the absence of that
-- trigger and are handled when the combinations are formed.
--
-- ⚠ The anchor can land on a TRANSFER, which is not in tradeevent.  In that case
-- the first row with seq >= seq_a is the next trade and the entry is the 3rd
-- trade after that, i.e. slightly later than 3 events after the anchor.  Same
-- convention as result_flow_eg_entry.  Stated, not silently equated.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
a AS (
    SELECT d.token_mint, d.seq_a, d.x_a, d.anchor_unix, date(b.launch_time) AS ld
    FROM dune.quantbino1695.result_flow_dd d
    JOIN coh c ON c.token_mint = d.token_mint
    JOIN dune.quantbino1695.result_flow_token_base b ON b.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20'
),
ev0 AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           to_unixtime(t.evt_block_time) AS ut,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
ev AS (
    SELECT mint, seq, ut, x,
           lead(x,  3) OVER (PARTITION BY mint ORDER BY seq) AS lx,
           lead(ut, 3) OVER (PARTITION BY mint ORDER BY seq) AS lu
    FROM ev0
),
en AS (
    SELECT a.token_mint, a.x_a, a.anchor_unix, a.ld,
           min_by(e.seq, e.seq) AS seq_en,
           min_by(e.lx,  e.seq) AS x_en,
           min_by(e.lu,  e.seq) AS ut_en
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq >= a.seq_a
    GROUP BY a.token_mint, a.x_a, a.anchor_unix, a.ld
),
j AS (
    SELECT en.*, e.seq, e.ut, e.x, e.lx, e.lu
    FROM en JOIN ev e ON e.mint = en.token_mint AND e.seq > en.seq_en
    WHERE en.x_en IS NOT NULL
)
SELECT token_mint, max(ld) AS ld, max(x_a) AS x_a, max(x_en) AS x_en,
       max(ut_en) AS ut_en, max(anchor_unix) AS anchor_unix,
       CAST(count(*) AS bigint) AS n_after,
       max_by(x, seq) AS final_x, max(ut) AS final_ut,
       min(if(ut - anchor_unix >= 10, seq)) AS q10,
       min_by(lx, if(ut - anchor_unix >= 10, seq)) AS x10,
       min_by(lu, if(ut - anchor_unix >= 10, seq)) AS u10,
       min(if(ut - anchor_unix >= 20, seq)) AS q20,
       min_by(lx, if(ut - anchor_unix >= 20, seq)) AS x20,
       min_by(lu, if(ut - anchor_unix >= 20, seq)) AS u20,
       min(if(ut - anchor_unix >= 30, seq)) AS q30,
       min_by(lx, if(ut - anchor_unix >= 30, seq)) AS x30,
       min_by(lu, if(ut - anchor_unix >= 30, seq)) AS u30,
       min(if(ut - anchor_unix >= 60, seq)) AS q60,
       min_by(lx, if(ut - anchor_unix >= 60, seq)) AS x60t,
       min_by(lu, if(ut - anchor_unix >= 60, seq)) AS u60t,
       min(if(x <= x_a * 0.90, seq)) AS s90,
       min_by(lx, if(x <= x_a * 0.90, seq)) AS xs90,
       min_by(lu, if(x <= x_a * 0.90, seq)) AS us90,
       min(if(x <= x_a * 0.85, seq)) AS s85,
       min_by(lx, if(x <= x_a * 0.85, seq)) AS xs85,
       min_by(lu, if(x <= x_a * 0.85, seq)) AS us85,
       min(if(x >= 60.0, seq)) AS g60,
       min_by(lx, if(x >= 60.0, seq)) AS xg60,
       min_by(lu, if(x >= 60.0, seq)) AS ug60,
       min(if(x >= x_a * 1.5, seq)) AS g15,
       min_by(lx, if(x >= x_a * 1.5, seq)) AS xg15,
       min_by(lu, if(x >= x_a * 1.5, seq)) AS ug15,
       min(if(x >= x_a * 2.0, seq)) AS g20,
       min_by(lx, if(x >= x_a * 2.0, seq)) AS xg20,
       min_by(lu, if(x >= x_a * 2.0, seq)) AS ug20
FROM j GROUP BY token_mint
