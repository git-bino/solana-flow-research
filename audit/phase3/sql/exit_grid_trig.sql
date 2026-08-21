-- Grid, pass B -- exit TRIGGERS (evaluated on events strictly after the entry)
-- and the TIME exits.
--
-- WHY TIME IS DIFFERENT.  `ut > anchor_unix + T` is MONOTONE in seq: once true it
-- stays true, so the events satisfying it are exactly the events after the
-- boundary and `min_by(x, if(cond, seq), 3)` element 3 IS the 3rd event after
-- the boundary -- the delayed exit, in one pass.
-- `x <= S*x_a` and `x >= G` are NOT monotone, so their delayed price needs the
-- trigger seq first; only the trigger is captured here and pass C prices it.
--
-- TIME LIMIT is measured from the ANCHOR (it is a rule parameter), while the
-- position exists only from the entry; combinations where the entry lands after
-- the boundary are identified downstream by comparing seq_entry.
WITH a AS (
    SELECT token_mint, anchor_kind, x_a, anchor_unix, seq_entry, x_entry, ut_entry
    FROM dune.quantbino1695.result_flow_eg_entry
    WHERE seq_entry IS NOT NULL
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
    SELECT a.token_mint, a.anchor_kind, a.x_a, a.anchor_unix, e.seq, e.ut, e.x
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_entry
)
SELECT token_mint, anchor_kind,
       min(if(x <= x_a * 0.95, seq)) AS s95, min(if(x <= x_a * 0.95, ut)) AS u95,
       min(if(x <= x_a * 0.90, seq)) AS s90, min(if(x <= x_a * 0.90, ut)) AS u90,
       min(if(x <= x_a * 0.85, seq)) AS s85, min(if(x <= x_a * 0.85, ut)) AS u85,
       min(if(x >= 60,          seq)) AS g60, min(if(x >= 60,          ut)) AS ug60,
       min(if(x >= 70,          seq)) AS g70, min(if(x >= 70,          ut)) AS ug70,
       min(if(x >= x_a * 1.5,   seq)) AS g15, min(if(x >= x_a * 1.5,   ut)) AS ug15,
       element_at(min_by(x, if(ut > anchor_unix + 10, seq), 3), 3) AS xt10,
       element_at(min_by(x, if(ut > anchor_unix + 16, seq), 3), 3) AS xt16,
       element_at(min_by(x, if(ut > anchor_unix + 20, seq), 3), 3) AS xt20,
       element_at(min_by(x, if(ut > anchor_unix + 30, seq), 3), 3) AS xt30,
       element_at(min_by(x, if(ut > anchor_unix + 45, seq), 3), 3) AS xt45,
       element_at(min_by(x, if(ut > anchor_unix + 60, seq), 3), 3) AS xt60,
       min(if(ut > anchor_unix + 10, seq)) AS qt10,
       min(if(ut > anchor_unix + 16, seq)) AS qt16,
       min(if(ut > anchor_unix + 20, seq)) AS qt20,
       min(if(ut > anchor_unix + 30, seq)) AS qt30,
       min(if(ut > anchor_unix + 45, seq)) AS qt45,
       min(if(ut > anchor_unix + 60, seq)) AS qt60,
       CAST(count(*) AS bigint) AS n_after_entry
FROM j GROUP BY token_mint, anchor_kind
