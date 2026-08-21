-- 1a -- structure probe.  information_schema is FORBIDDEN (2026-08-21 rule after
-- it cost 189.086 cr); this reads one row from one day partition instead.
SELECT * FROM tokens_solana.sol_transfers
WHERE block_date = DATE '2026-05-10'
LIMIT 1
