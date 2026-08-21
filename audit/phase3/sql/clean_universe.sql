-- CLEAN UNIVERSE -- defined by the INVARIANT, not by the flag.
--
-- mayhem = an AI agent mints ~1e9 extra tokens and trades them randomly, burning
-- them within 24h (decisions.md 2026-08-21).  That breaks x*y = k, which is the
-- only thing the pricing model actually needs.  So the universe is defined by
--     max |x*y / k0 - 1| < 1e-6
-- with k0 = the token's FIRST event's vsol * vtok.  Measured separation is wide:
-- non-mayhem p50 2.5e-9 against mayhem p50 52% (docs/audit3_defect1_mayhem.md).
--
-- NO WINDOW FUNCTION.  `x*y / k0 - 1` is monotone in x*y, so
--     max |x*y/k0 - 1| = max( |max(x*y)/k0 - 1| , |min(x*y)/k0 - 1| )
-- and k0 = min_by(x*y, seq).  All three are plain aggregates in ONE GROUP BY --
-- a `first_value` window would need a sort over ~19M rows (the anchor for that
-- shape is result_flow_holder_anchor: two such sorts, 24.466 cr).
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (cost engineering; the invariant is exactly
-- as the research lead defined it).
--
-- The createevent flag is carried alongside so §1 can cross-tabulate invariant
-- against flag rather than assume they agree.
WITH ce AS (
    SELECT mint, bool_or(is_mayhem_mode) AS mayhem_flag, min(evt_block_time) AS t_create
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
tb AS (SELECT token_mint, launch_time FROM dune.quantbino1695.result_flow_token_base),
coh AS (
    SELECT tb.token_mint, tb.launch_time, coalesce(ce.mayhem_flag, false) AS mayhem_flag
    FROM tb LEFT JOIN ce ON ce.mint = tb.token_mint
),
ev AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           t.evt_block_time AS bt,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9        AS x,
           CAST(t.virtual_sol_reserves AS double) / 1e9
             * CAST(t.virtual_token_reserves AS double) / 1e6  AS xy
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
)
SELECT c.token_mint,
       c.mayhem_flag,
       CAST(count(e.seq) AS bigint)            AS n_ev,
       min_by(e.xy, e.seq)                     AS k0,
       min(e.xy)                               AS xy_min,
       max(e.xy)                               AS xy_max,
       max(e.x)                                AS max_x,
       min(e.bt)                               AS t_first,
       max(e.bt)                               AS t_last,
       to_unixtime(max(e.bt)) - to_unixtime(c.launch_time) AS lifetime_s
FROM coh c LEFT JOIN ev e ON e.mint = c.token_mint
GROUP BY c.token_mint, c.mayhem_flag, c.launch_time
