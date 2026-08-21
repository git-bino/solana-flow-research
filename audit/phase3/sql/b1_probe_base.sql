-- 0 -- one row of result_flow_token_base, to read the column names and types
-- for t_60 (needed to rebuild win_rate without lookahead).
-- information_schema is FORBIDDEN; this reads one row instead.
SELECT * FROM dune.quantbino1695.result_flow_token_base LIMIT 1
