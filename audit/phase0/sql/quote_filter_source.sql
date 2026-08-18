-- Phase 0 — can createevent's declared initial reserves serve as the quote filter?
--
-- Pre-registered rule (decisions.md): the filter is applied on the createevent
-- declared initial reserve, not on trade-side quote_mint.  This file tests
-- whether that is possible and what it costs in coverage.
--
-- Aggregates only, no rows exported.  Four queries, each inside the per-query
-- credit guard.
--
-- createevent carries BOTH `virtual_sol_reserves` and `virtual_quote_reserves`;
-- on a SOL curve the sample row shows them equal (both 30000000000).  If the
-- pair separates SOL from non-SOL curves cleanly, it is a declared,
-- trade-independent classifier available from the launch event alone.

-- ─────────────────────────────────────────────────────────────────────────────
-- A — createevent field availability and NULL share, 2026-05-10 .. 2026-05-30
-- ─────────────────────────────────────────────────────────────────────────────
SELECT count(*)                                        AS creates,
       count_if(quote_mint IS NULL)                    AS quote_mint_null,
       count_if(virtual_sol_reserves IS NULL)          AS vsol_null,
       count_if(virtual_quote_reserves IS NULL)        AS vquote_null,
       count_if(virtual_token_reserves IS NULL)        AS vtok_null,
       count_if(real_token_reserves IS NULL)           AS real_tok_null,
       count_if(token_total_supply IS NULL)            AS supply_null,
       count_if(is_mayhem_mode IS NULL)                AS mayhem_null,
       count_if(is_cashback_enabled IS NULL)           AS cashback_null,
       count_if(creator IS NULL)                       AS creator_null,
       count_if(bonding_curve IS NULL)                 AS bonding_curve_null,
       count_if(token_program IS NULL)                 AS token_program_null,
       count_if(bondingCurve IS NOT NULL)              AS v1_camelcase,
       count(DISTINCT CAST(virtual_sol_reserves AS varchar))   AS distinct_vsol,
       count(DISTINCT CAST(virtual_quote_reserves AS varchar)) AS distinct_vquote,
       count(DISTINCT CAST(virtual_token_reserves AS varchar)) AS distinct_vtok,
       count_if(CAST(virtual_sol_reserves AS varchar)
                <> CAST(virtual_quote_reserves AS varchar))    AS vsol_ne_vquote
FROM pumpdotfun_solana.pump_evt_createevent
WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-05-30'
;

-- ─────────────────────────────────────────────────────────────────────────────
-- B + D — discrimination against trade-side truth, and token-level stability,
-- 2026-05-21 .. 2026-05-30 (the period where trade quote_mint is named)
-- ─────────────────────────────────────────────────────────────────────────────
WITH tok_quote AS (
    SELECT mint,
           min(quote_mint) AS q_min,
           max(quote_mint) AS q_max,
           count_if(quote_mint IS NOT NULL) AS n_named,
           count(*) AS n_trades
    FROM pumpdotfun_solana.pump_evt_tradeevent
    WHERE evt_block_date >= DATE '2026-05-21' AND evt_block_date <= DATE '2026-05-30'
    GROUP BY mint
),
cre AS (
    SELECT mint,
           max(CAST(virtual_sol_reserves   AS varchar)) AS x0_sol,
           max(CAST(virtual_quote_reserves AS varchar)) AS x0_quote,
           max(CAST(virtual_token_reserves AS varchar)) AS y0
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-21' AND evt_block_date <= DATE '2026-05-30'
    GROUP BY mint
)
SELECT CASE WHEN t.q_max = '11111111111111111111111111111111' THEN 'SOL'
            WHEN t.q_max = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' THEN 'USDC'
            WHEN t.q_max IS NULL THEN 'trade_quote_NULL'
            ELSE 'OTHER' END                       AS trade_truth,
       c.x0_sol, c.x0_quote, c.y0,
       count(*)                                    AS tokens,
       sum(t.n_trades)                             AS trades,
       count_if(t.q_min <> t.q_max)                AS tokens_quote_inconsistent
FROM cre c JOIN tok_quote t ON t.mint = c.mint
GROUP BY 1, 2, 3, 4
ORDER BY tokens DESC
LIMIT 40
;

-- ─────────────────────────────────────────────────────────────────────────────
-- C — the tokens created on the transition day with NULL quote and x0 != 30 SOL
-- ─────────────────────────────────────────────────────────────────────────────
WITH odd AS (
    SELECT mint, min(evt_block_time) AS launch_time,
           max(CAST(virtual_sol_reserves   AS varchar)) AS x0_sol,
           max(CAST(virtual_quote_reserves AS varchar)) AS x0_quote
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date = DATE '2026-05-21'
      AND quote_mint IS NULL
      AND CAST(virtual_sol_reserves AS decimal(38,0)) <> CAST(30000000000 AS decimal(38,0))
    GROUP BY mint
),
later AS (
    SELECT t.mint, max(t.quote_mint) AS q_later, count(*) AS n_trades
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN odd o ON o.mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-21' AND t.evt_block_date <= DATE '2026-06-01'
    GROUP BY t.mint
)
SELECT o.x0_sol, o.x0_quote,
       coalesce(l.q_later, '(no later trade / still NULL)') AS quote_seen_later,
       count(*)                     AS tokens,
       min(o.launch_time)           AS launch_min,
       max(o.launch_time)           AS launch_max,
       count_if(o.launch_time <  TIMESTAMP '2026-05-21 17:15:43') AS launched_before_switch,
       count_if(o.launch_time >= TIMESTAMP '2026-05-21 17:15:43') AS launched_after_switch,
       sum(coalesce(l.n_trades, 0)) AS trades
FROM odd o LEFT JOIN later l ON l.mint = o.mint
GROUP BY 1, 2, 3
ORDER BY tokens DESC
LIMIT 40
;

-- ─────────────────────────────────────────────────────────────────────────────
-- E — chunk 1's launch window classified by the declared initial reserve
-- ─────────────────────────────────────────────────────────────────────────────
SELECT CAST(virtual_sol_reserves   AS varchar) AS x0_sol,
       CAST(virtual_quote_reserves AS varchar) AS x0_quote,
       CAST(virtual_token_reserves AS varchar) AS y0,
       count(DISTINCT mint)                    AS tokens,
       count_if(quote_mint IS NULL)            AS rows_quote_null,
       min(evt_block_time)                     AS first_launch,
       max(evt_block_time)                     AS last_launch
FROM pumpdotfun_solana.pump_evt_createevent
WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
GROUP BY 1, 2, 3
ORDER BY tokens DESC
LIMIT 40
;
