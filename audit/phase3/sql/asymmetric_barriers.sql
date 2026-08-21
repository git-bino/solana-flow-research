-- 2 + 4 -- asymmetric barriers with OVERSHOOT, H3 anchor.
--
-- WHY A NEW PASS.  The existing `result_flow_hpath_*` matviews carry only the
-- +20/+36/-20/-30 crossings and store the SLOT of each, not the reserve at that
-- slot.  §2 needs four new upside levels and §4 needs the reserve AT the
-- crossing, so a forward pass was unavoidable -- and once it runs, capturing the
-- overshoot costs no extra scan.  §4 is therefore ANSWERED, not skipped.
--
-- OVERSHOOT.  For each barrier this stores three things: the first slot at which
-- it was touched, the reserve ON THAT EVENT (`min_by(x, if(cond, seq))` -- the x
-- of the earliest event satisfying the condition), and the time.  The realised
-- exit therefore uses the actual crossing reserve, which sits ABOVE the level on
-- the upside and BELOW it on the downside; both directions are kept, so the
-- overshoot is not a one-sided favour.
--
-- LEVELS are relative multiples of each token's OWN `x_a`, as the task states
-- them (the SOL figures in the brief -- 60/70/80 -- are what those multiples
-- come to at the median anchor, x_a p50 = 34.1, not absolute targets).
--   stops    0.80  0.70  0.50   (x -20%, -30%, -50%)
--   targets  1.50  1.76  2.05  2.35   (x +50%, +76%, +105%, +135%)
--
-- FORWARD SET is strictly `seq > seq_a`, the same composite key the anchor was
-- found with.  A barrier never touched leaves its slot NULL and is censored --
-- never replaced by a threshold value.
WITH base AS (
    SELECT token_mint, launch_time
    FROM dune.quantbino1695.result_flow_token_base
),
a AS (
    SELECT h.token_mint, h.seq_a, h.t_a_s, h.x_a,
           to_unixtime(b.launch_time) + h.t_a_s AS anchor_unix
    FROM dune.quantbino1695.result_flow_holder_anchor h
    JOIN base b ON b.token_mint = h.token_mint
    WHERE h.anchor_kind = 'H3'
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
    SELECT a.token_mint, a.x_a, a.t_a_s, a.anchor_unix,
           e.seq, e.sl, e.ut, e.x
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_a
)
SELECT token_mint,
       max(x_a) AS x_a, max(t_a_s) AS t_a_s,
       CAST(count(*) AS bigint) AS n_after,
       max(x) AS max_x_after,
       max_by(x, seq) AS final_x,
       max(ut) - max(anchor_unix) AS t_final_s,
       min(if(x <= x_a * 0.8, sl))                       AS sl_d20,
       min_by(x,  if(x <= x_a * 0.8, seq))                AS x_d20,
       min(if(x <= x_a * 0.8, ut)) - max(anchor_unix)     AS t_d20,
       min(if(x <= x_a * 0.7, sl))                       AS sl_d30,
       min_by(x,  if(x <= x_a * 0.7, seq))                AS x_d30,
       min(if(x <= x_a * 0.7, ut)) - max(anchor_unix)     AS t_d30,
       min(if(x <= x_a * 0.5, sl))                       AS sl_d50,
       min_by(x,  if(x <= x_a * 0.5, seq))                AS x_d50,
       min(if(x <= x_a * 0.5, ut)) - max(anchor_unix)     AS t_d50,
       min(if(x >= x_a * 1.5, sl))                       AS sl_u50,
       min_by(x,  if(x >= x_a * 1.5, seq))                AS x_u50,
       min(if(x >= x_a * 1.5, ut)) - max(anchor_unix)     AS t_u50,
       min(if(x >= x_a * 1.76, sl))                       AS sl_u76,
       min_by(x,  if(x >= x_a * 1.76, seq))                AS x_u76,
       min(if(x >= x_a * 1.76, ut)) - max(anchor_unix)     AS t_u76,
       min(if(x >= x_a * 2.05, sl))                       AS sl_u05,
       min_by(x,  if(x >= x_a * 2.05, seq))                AS x_u05,
       min(if(x >= x_a * 2.05, ut)) - max(anchor_unix)     AS t_u05,
       min(if(x >= x_a * 2.35, sl))                       AS sl_u35,
       min_by(x,  if(x >= x_a * 2.35, seq))                AS x_u35,
       min(if(x >= x_a * 2.35, ut)) - max(anchor_unix)     AS t_u35
FROM j
GROUP BY token_mint
