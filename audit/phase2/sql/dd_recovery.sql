-- 3 (stage B) -- what the reserve does AFTER the largest seller stops.
-- Also picks up `min_x` after the drawdown, which sql/drawdown_anatomy.sql
-- omitted (my omission; folded in here instead of paying for a rebuild).
-- All conditional aggregates, no window.
WITH st AS (SELECT * FROM dune.quantbino1695.result_flow_ddstop),
d AS (SELECT token_mint, anchor_kind, seq_drop FROM dune.quantbino1695.result_flow_dd),
a AS (
    SELECT st.*, d.seq_drop
    FROM st JOIN d ON d.token_mint = st.token_mint AND d.anchor_kind = st.anchor_kind
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
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT a.token_mint, a.anchor_kind, a.cls, a.x_a, a.x_stop, a.ut_stop,
           a.seq_stop, a.seq_drop, e.seq, e.ut, e.x
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_drop
)
SELECT token_mint, anchor_kind, max(cls) AS cls, max(x_a) AS x_a, max(x_stop) AS x_stop,
       min(x) AS min_x_after_drop,
       min_by(x, if(seq > seq_stop AND ut >= ut_stop + 10, seq)) AS x_p10s,
       min_by(x, if(seq > seq_stop AND ut >= ut_stop + 30, seq)) AS x_p30s,
       min_by(x, if(seq > seq_stop AND ut >= ut_stop + 60, seq)) AS x_p60s,
       max(if(seq > seq_stop, x)) AS max_x_after_stop,
       min(if(seq > seq_stop AND x >= x_a, ut)) - max(ut_stop) AS t_back_to_xa,
       min(if(seq > seq_stop AND x >= 60,  ut)) - max(ut_stop) AS t_to_60,
       CAST(count_if(seq > seq_stop) AS bigint) AS n_after_stop
FROM j
GROUP BY token_mint, anchor_kind
