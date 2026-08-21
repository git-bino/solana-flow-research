-- TIME-BASED EXIT -- one row per H20-anchored token in the CAUSAL universe.
--
-- UNIVERSE: createevent.is_mayhem_mode = false (launch-time observable),
-- carried as result_flow_clean.mayhem_flag.
--
-- THE NEW EXIT.  The old rule filled at the 3rd EVENT after the trigger, which
-- makes the priced population depend on how many events happen to follow
-- (Lx 0->8: CLOSED 97.55% -> 78.77%).  The new rule fills at the NEXT
-- OPPORTUNITY within W seconds of the trigger.
--
-- ⚠ Events are time-ordered, so "the earliest event inside the W-second window"
-- is ALWAYS the immediately next event -- if that one is beyond W, every later
-- one is too.  The fill ordinal is therefore 1 BY CONSTRUCTION for every W, and
-- W only decides CLOSED vs OPEN.  That is why this matview stores ONE candidate
-- fill (`x_n`, `ut_n`, `gap`) rather than one per W.
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР: the brief also admits a reading where the
-- exit happens at the END of the W window (last event inside it) rather than the
-- earliest.  The literal text says "хамгийн эртнийх дээр гарна", so the earliest
-- is what is implemented; the other reading is NOT measured.
--
-- OPEN SPLIT needs three more facts, all stored here:
--   `gap`      seconds from the trigger to the next trade -> LATE_FILL vs DEAD
--   `x_last`   the last observed reserve                  -> DEAD is priced there
--   `trig_ut`  how close the trigger is to the data edge  -> WINDOW_EDGE
--
-- NO FALLBACK is applied in this file: `x_n` and `x_last` are NULL when the
-- events do not exist, and stay NULL.
WITH coh AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_clean WHERE mayhem_flag = false
),
a AS (
    SELECT d.token_mint, d.seq_a, d.anchor_unix, date(b.launch_time) AS ld
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
    JOIN a ON a.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
ev AS (
    SELECT mint, seq, ut, x,
           lead(x,  1) OVER w AS n_x,
           lead(ut, 1) OVER w AS n_ut,
           lead(x,  3) OVER w AS l3
    FROM ev0
    WINDOW w AS (PARTITION BY mint ORDER BY seq)
),
en AS (
    SELECT a.token_mint, a.ld, a.anchor_unix,
           min_by(e.seq, e.seq) AS seq_en, min_by(e.l3, e.seq) AS x_en
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq >= a.seq_a
    GROUP BY a.token_mint, a.ld, a.anchor_unix
),
j AS (
    SELECT en.token_mint, en.ld, en.x_en, en.anchor_unix,
           e.seq, e.ut, e.x, e.n_x, e.n_ut
    FROM en JOIN ev e ON e.mint = en.token_mint AND e.seq > en.seq_en
    WHERE en.x_en IS NOT NULL AND en.x_en > 0
),
t AS (
    SELECT token_mint, max(ld) AS ld, max(x_en) AS x1,
           max_by(x, seq)  AS x_last,
           max(ut)         AS ut_last,
           CAST(count(*) AS bigint) AS n_after_entry,
           min(if(x >= 60.0, seq)) AS g_seq,
           min(if(ut - anchor_unix >= 60, seq)) AS t_seq,
           min_by(ut,   if(x >= 60.0, seq)) AS g_ut,
           min_by(n_x,  if(x >= 60.0, seq)) AS g_nx,
           min_by(n_ut, if(x >= 60.0, seq)) AS g_nut,
           min_by(ut,   if(ut - anchor_unix >= 60, seq)) AS q_ut,
           min_by(n_x,  if(ut - anchor_unix >= 60, seq)) AS q_nx,
           min_by(n_ut, if(ut - anchor_unix >= 60, seq)) AS q_nut
    FROM j GROUP BY token_mint
)
SELECT token_mint, ld, x1, x_last, ut_last, n_after_entry,
       CASE WHEN g_seq IS NOT NULL AND (t_seq IS NULL OR g_seq <= t_seq) THEN 'G'
            WHEN t_seq IS NOT NULL THEN 'T' ELSE 'NONE' END AS trig_kind,
       CASE WHEN g_seq IS NOT NULL AND (t_seq IS NULL OR g_seq <= t_seq) THEN g_ut
            WHEN t_seq IS NOT NULL THEN q_ut END AS trig_ut,
       CASE WHEN g_seq IS NOT NULL AND (t_seq IS NULL OR g_seq <= t_seq) THEN g_nx
            WHEN t_seq IS NOT NULL THEN q_nx END AS n_x,
       CASE WHEN g_seq IS NOT NULL AND (t_seq IS NULL OR g_seq <= t_seq) THEN g_nut
            WHEN t_seq IS NOT NULL THEN q_nut END AS n_ut
FROM t
