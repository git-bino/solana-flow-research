-- 1 (part) -- FINAL holder count and wallets-ever, transfer-aware.
--
-- No window function: the end-of-life ledger is a plain GROUP BY (mint, wallet)
-- over trade legs plus transfer legs, then a count of the positives.
--
-- WHAT THIS IS NOT.  It is NOT the lifetime MAXIMUM holder count.  That needs a
-- running count -- a window partitioned by (mint, wallet) for the balance and a
-- second partitioned by mint for the running sum -- which is exactly the shape
-- that cost 24.466 cr in result_flow_holder_anchor, more than this step's whole
-- 20-credit budget.  The maximum is therefore NOT measured here; threshold
-- attainment from the existing anchors is used instead and the substitution is
-- stated in docs/holder_growth.md.
--
-- WINDOW.  [2026-05-10, 2026-05-20], which holds 97.74% of cohort trade events
-- and is the span the transfer matviews were joined over previously.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
tr AS (
    SELECT t.mint, t.user AS w,
           if(t.is_buy, CAST(t.token_amount AS double),
                       -CAST(t.token_amount AS double)) AS du,
           t.user AS buyer_if_buy, t.is_buy
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-05-20'
),
xf_raw AS (
    SELECT token_mint_address AS mint, from_owner, to_owner, CAST(amount AS double) AS amount
    FROM ({{XF_UNION}}) u
    WHERE block_date >= DATE '2026-05-10' AND block_date <= DATE '2026-05-20'
),
legs AS (
    SELECT mint, w, du FROM tr
    UNION ALL SELECT x.mint, x.to_owner,   x.amount FROM xf_raw x
    UNION ALL SELECT x.mint, x.from_owner, -x.amount FROM xf_raw x
),
led AS (SELECT mint, w, sum(du) AS u FROM legs GROUP BY mint, w),
wal AS (
    SELECT mint, count(DISTINCT w) AS n_wallets_ever,
           count(DISTINCT if(is_bought, w)) AS n_buyers_ever
    FROM (SELECT mint, w, true AS is_bought FROM tr WHERE is_buy
          UNION ALL SELECT mint, w, false FROM tr WHERE NOT is_buy)
    GROUP BY mint
)
SELECT l.mint AS token_mint,
       CAST(count_if(l.u > 0) AS bigint) AS n_holders_final,
       CAST(max(w.n_wallets_ever) AS bigint) AS n_wallets_ever,
       CAST(max(w.n_buyers_ever) AS bigint) AS n_buyers_ever
FROM led l JOIN wal w ON w.mint = l.mint
GROUP BY l.mint
