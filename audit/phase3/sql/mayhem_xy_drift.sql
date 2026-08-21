-- Audit 3, defect 1 (part 3) -- how far x*y drifts from the constant the pricing
-- model assumes, split by launch-time mayhem.
--
-- WHAT IS MEASURED.  `P = x^2 / k` needs k = x*y to be CONSTANT.  This measures
-- the per-EVENT relative deviation from the launch constant
--     k0 = 30 SOL * 1,073,000,000 tokens = 3.219e10
-- i.e. |x*y / k0 - 1|.  Phase 0 measured |Δ(x*y)/(x*y)| between CONSECUTIVE
-- pairs, which needs a lag window over ~19M rows (the anchor for that shape is
-- result_flow_holder_anchor at 24.466 cr).  The two are related but NOT the same
-- statistic and the numbers are not directly comparable; stated rather than
-- implied.  ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (cost: deviation-from-k0 is a plain
-- aggregate, consecutive-pair drift is a sort).
--
-- WINDOW.  [2026-05-10, 2026-05-20] holds 19,308,576 of the cohort's 19,755,310
-- events = 97.74%, so the 98-day scan buys almost nothing here.
--
-- The tradeevent-side flag `mayhem_mode` is cross-checked against the
-- createevent launch flag in the same pass.
WITH ce AS (
    SELECT mint, bool_or(is_mayhem_mode) AS mayhem_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
tb AS (SELECT token_mint FROM dune.quantbino1695.result_flow_token_base),
coh AS (
    SELECT tb.token_mint, coalesce(ce.mayhem_launch, false) AS mh
    FROM tb LEFT JOIN ce ON ce.mint = tb.token_mint
),
ev AS (
    SELECT c.mh,
           coalesce(t.mayhem_mode, false) AS mh_evt,
           abs(CAST(t.virtual_sol_reserves AS double) / 1e9
               * CAST(t.virtual_token_reserves AS double) / 1e6
               / 32190000000.0 - 1.0) AS dev
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-05-20'
)
SELECT mh AS mayhem_launch,
       CAST(count(*) AS double) AS n_events,
       CAST(count_if(mh_evt) AS double) AS n_events_mayhem_flag,
       CAST(count_if(mh_evt) AS double)/count(*) AS share_event_flag,
       approx_percentile(dev, 0.50) AS p50,
       approx_percentile(dev, 0.90) AS p90,
       approx_percentile(dev, 0.99) AS p99,
       max(dev) AS dmax,
       CAST(count_if(dev > 1e-9) AS double)/count(*)  AS share_gt_1e9,
       CAST(count_if(dev > 0.01) AS double)/count(*)  AS share_gt_1pct,
       CAST(count_if(dev > 0.10) AS double)/count(*)  AS share_gt_10pct
FROM ev GROUP BY mh
