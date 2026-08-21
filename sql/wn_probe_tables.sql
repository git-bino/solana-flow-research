-- 0 -- targeted existence probe.  No LIKE, no data partitions touched.
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name IN ('transfers','account_activity','system_program_call_transfer',
                     'native_transfers','sol_transfers','transfers_solana')
   OR table_schema IN ('system_program_solana','solana_utils')
ORDER BY table_schema, table_name
