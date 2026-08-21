-- 0 -- does a SOL (native, system-program) transfer table exist on Dune?
-- information_schema only: no data partitions are touched, so this is metadata
-- cost, not scan cost.
SELECT table_schema, table_name, count(*) AS n_cols,
       array_join(array_agg(column_name ORDER BY ordinal_position), ',') AS cols
FROM information_schema.columns
WHERE (table_schema LIKE '%solana%' OR table_schema = 'solana')
  AND (table_name LIKE '%transfer%' OR table_name LIKE '%account_activity%'
       OR table_name LIKE '%balance%')
GROUP BY table_schema, table_name
ORDER BY table_schema, table_name
