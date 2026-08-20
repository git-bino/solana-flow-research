-- 2 + 3 -- the path after each anchor, and the FIRST-PASSAGE slots.
--
-- §2 and §3 need the same forward scan, so they are computed in ONE pass and
-- stored in a matview.  Nothing is exported; the §2/§3/§4 tables are aggregated
-- off this matview afterwards for ~0.1 cr each.
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (cost engineering only; both sections keep
-- exactly the definitions the task gave).
--
-- ORDERING.  "Which came first" is decided on SLOT, as the task requires,
-- because `x` is not monotone in slot.  The slot of the first target hit and the
-- slot of the first stop hit are BOTH stored, so the comparison -- including the
-- SAME-SLOT case, which is counted separately and never broken by a tiebreak --
-- is made in the aggregation step, not hidden here.
--
-- FORWARD SET.  Strictly `seq > seq_a`: the anchor event itself cannot be its
-- own first passage.  `seq` is the same composite key the anchor was found with.
--
-- CENSORING.  A target or stop that is never reached leaves its slot NULL.  NULL
-- is never replaced by zero or by a finite number; the aggregation counts those
-- rows as censored at the event-window edge (2026-08-15).
--
-- RELATIVE MOVES are on `x` against `x_a`, the reserve at the anchor:
--   targets  +20% (x >= 1.20 x_a), +36% (>= 1.36 x_a), +100% (>= 2.00 x_a)
--   stops    -20% (x <= 0.80 x_a), -30% (<= 0.70 x_a), -50% (<= 0.50 x_a)

WITH base AS (
    SELECT token_mint, launch_time
    FROM dune.quantbino1695.result_flow_token_base
),
a AS (
    SELECT h.token_mint, h.anchor_kind, h.n_target, h.seq_a, h.sl_a,
           h.t_a_s, h.x_a, h.nh_a,
           to_unixtime(b.launch_time) + h.t_a_s AS anchor_unix
    FROM dune.quantbino1695.result_flow_holder_anchor h
    JOIN base b ON b.token_mint = h.token_mint
    WHERE h.anchor_kind IN ({{KINDS}})
),
ev AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           CAST(t.evt_block_slot AS bigint) AS sl,
           to_unixtime(t.evt_block_time) AS ut,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT a.token_mint, a.anchor_kind, a.n_target, a.x_a, a.t_a_s, a.nh_a,
           a.anchor_unix, e.seq, e.sl, e.ut, e.x
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_a
)
SELECT token_mint, anchor_kind, n_target,
       max(x_a)   AS x_a,
       max(t_a_s) AS t_a_s,
       max(nh_a)  AS nh_a,
       CAST(count(*) AS bigint) AS n_after,

       -- §2 path
       max(x) AS max_x_after,
       min(x) AS min_x_after,
       min_by(ut, ROW(-x, seq)) - max(anchor_unix) AS t_max_after_s,
       max_by(x, seq)  AS final_x,
       max(ut) - max(anchor_unix) AS t_final_s,

       -- §3 first passage: SLOT of first hit (NULL = never reached)
       min(if(x >= x_a * 1.20, sl)) AS sl_g20,
       min(if(x >= x_a * 1.36, sl)) AS sl_g36,
       min(if(x >= x_a * 2.00, sl)) AS sl_g100,
       min(if(x <= x_a * 0.80, sl)) AS sl_l20,
       min(if(x <= x_a * 0.70, sl)) AS sl_l30,
       min(if(x <= x_a * 0.50, sl)) AS sl_l50,
       min(if(x >= 60,  sl)) AS sl_60,
       min(if(x >= 115, sl)) AS sl_115,

       -- times to first hit, seconds from the anchor
       min(if(x >= x_a * 1.20, ut)) - max(anchor_unix) AS t_g20_s,
       min(if(x >= x_a * 1.36, ut)) - max(anchor_unix) AS t_g36_s,
       min(if(x >= x_a * 2.00, ut)) - max(anchor_unix) AS t_g100_s,
       min(if(x <= x_a * 0.80, ut)) - max(anchor_unix) AS t_l20_s,
       min(if(x <= x_a * 0.70, ut)) - max(anchor_unix) AS t_l30_s,
       min(if(x <= x_a * 0.50, ut)) - max(anchor_unix) AS t_l50_s,
       min(if(x >= 60,  ut)) - max(anchor_unix) AS t_60_s,
       min(if(x >= 115, ut)) - max(anchor_unix) AS t_115_s
FROM j
GROUP BY token_mint, anchor_kind, n_target
