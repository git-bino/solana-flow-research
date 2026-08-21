-- 1 -- the DRAWDOWN moment, per (clean token, anchor).  Matview.
--
-- SCOPE: CLEAN universe only (`max|x*y/k0 - 1| < 1e-6`).  On mayhem tokens
-- P ∝ x^2 does not hold and the seller is an AI agent, so "who sold" has no
-- meaning there.
--
-- ANCHORS: H15 and H20 from result_flow_holder_anchor.  **H30 DOES NOT EXIST** --
-- that matview holds H3, H5, H10, H15, H20 and X60 only, and adding H30 needs
-- the running-holder-count pass that cost 24.466 cr, above this step's budget.
-- H30 is therefore NOT measured and not approximated.
--
-- DRAWDOWN (pre-registered): the first event after the anchor with
-- x <= 0.90 * x_a.  Its seq, time and reserve are stored, along with the first
-- event at or above 60 (so "reached 60 BEFORE the drawdown" is decidable), the
-- minimum reserve after the drawdown, and the maximum after the anchor.
--
-- No window function -- every column is a plain aggregate over the forward set.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
base AS (SELECT token_mint, launch_time FROM dune.quantbino1695.result_flow_token_base),
a AS (
    SELECT h.token_mint, h.anchor_kind, h.seq_a, h.t_a_s, h.x_a,
           to_unixtime(b.launch_time) + h.t_a_s AS anchor_unix
    FROM dune.quantbino1695.result_flow_holder_anchor h
    JOIN coh c ON c.token_mint = h.token_mint
    JOIN base b ON b.token_mint = h.token_mint
    WHERE h.anchor_kind IN ('H15', 'H20')
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
    JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT a.token_mint, a.anchor_kind, a.x_a, a.t_a_s, a.seq_a, a.anchor_unix,
           e.seq, e.ut, e.x,
           e.x <= a.x_a * 0.90 AS is_drop,
           e.x >= 60           AS is_60
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_a
)
SELECT token_mint, anchor_kind,
       max(x_a) AS x_a, max(t_a_s) AS t_a_s, max(seq_a) AS seq_a,
       max(anchor_unix) AS anchor_unix,
       CAST(count(*) AS bigint) AS n_after,
       max(x) AS max_x_after,
       min(if(is_drop, seq)) AS seq_drop,
       min_by(x, if(is_drop, seq)) AS x_drop,
       min(if(is_drop, ut)) - max(anchor_unix) AS t_drop_s,
       min(if(is_60, seq)) AS seq_60,
       min(if(is_60, ut)) - max(anchor_unix) AS t_60_s,
       max(ut) - max(anchor_unix) AS t_last_s,
       max_by(x, seq) AS final_x
FROM j
GROUP BY token_mint, anchor_kind
