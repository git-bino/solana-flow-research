-- Audit 3, defect 2 -- the reserve at a FIXED HORIZON after the anchor.
--
-- The frozen rule exits at `final_x` when the target is never hit.  `final_x` is
-- the token's LAST trade, which is not knowable at any point a trader could act
-- on -- it is realtime-unobservable.  A fixed horizon is.
--
-- Per token: the reserve on the last trade at or before anchor + H, for
-- H in {1h, 6h, 24h}.  No window function -- `max_by(x, if(...))` is a plain
-- aggregate.  A token whose last trade falls before the horizon leaves the
-- corresponding column equal to its final reserve; `t_final_s` in
-- result_flow_gapin says which tokens those are, so "died inside the horizon"
-- is identifiable downstream and is valued BOTH ways there.
--
-- WINDOW.  Anchors sit in [2026-05-10, 2026-05-20]; anchor + 24h therefore
-- cannot exceed 2026-05-21.
WITH base AS (
    SELECT token_mint, launch_time FROM dune.quantbino1695.result_flow_token_base
),
a AS (
    SELECT h.token_mint, h.seq_a,
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
           to_unixtime(t.evt_block_time) AS ut,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-05-21'
),
j AS (
    SELECT a.token_mint, e.seq, e.x,
           e.ut <= a.anchor_unix + 3600    AS in_h1,
           e.ut <= a.anchor_unix + 21600   AS in_h6,
           e.ut <= a.anchor_unix + 86400   AS in_h24
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_a
)
SELECT token_mint,
       max_by(x, if(in_h1,  seq)) AS x_h1,
       max_by(x, if(in_h6,  seq)) AS x_h6,
       max_by(x, if(in_h24, seq)) AS x_h24,
       CAST(count_if(in_h1) AS bigint)  AS n_h1,
       CAST(count_if(in_h6) AS bigint)  AS n_h6,
       CAST(count_if(in_h24) AS bigint) AS n_h24
FROM j GROUP BY token_mint
