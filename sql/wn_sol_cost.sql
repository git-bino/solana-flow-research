-- 1a -- ONE DAY partition, full scan, so the credit price of this table is
-- measured rather than guessed (2026-08-21 rule).  Also sizes the join: how
-- many of the rows land on a wallet that is an H20 anchor wallet.
WITH s AS (
    SELECT to_owner, from_owner FROM tokens_solana.sol_transfers
    WHERE block_date = DATE '2026-05-10'
),
aw AS (SELECT DISTINCT wallet FROM dune.quantbino1695.result_flow_ddsell
       WHERE anchor_kind = 'H20' AND u_anchor > 0)
SELECT CAST(count(*) AS double)                          AS n_rows,
       CAST(count(DISTINCT s.to_owner) AS double)        AS n_to,
       CAST(count(DISTINCT s.from_owner) AS double)      AS n_from,
       CAST(count_if(aw.wallet IS NOT NULL) AS double)   AS n_hit_anchor
FROM s LEFT JOIN aw ON aw.wallet = s.to_owner
