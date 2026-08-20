-- 0 -- PRECONDITION: `P ∝ x²` holds only where x·y = k is constant, i.e. on
-- tokens whose virtual params were never rewritten by a mayhem event.  The
-- token-level matviews carry no mayhem flag, so the prevalence is counted here
-- before the economics are computed on top of that assumption.
SELECT CAST(count(*) AS double) AS n_cohort,
       CAST(count_if(m.mint IS NOT NULL) AS double) AS n_mayhem
FROM dune.quantbino1695.result_flow_token_base b
LEFT JOIN (
    SELECT DISTINCT mint
    FROM pumpdotfun_solana.pump_evt_updatemayhemvirtualparamsevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-08-15'
) m ON m.mint = b.token_mint
