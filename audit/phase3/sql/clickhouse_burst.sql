-- ClickHouse storage for the §2.3 burst rows (spec v1.3).
--
-- Column names, order and types follow `src/extract_schema.py`'s CANON exactly,
-- so `load_chunk()` output maps 1:1 with no translation layer.
--
-- Nullability is the one place this deviates from CANON, deliberately and on a
-- measurement.  CANON marks all 60 columns nullable because that is Arrow's
-- default, not because all 60 can be null; taken literally it would make the
-- sorting key Nullable too, which ClickHouse only accepts under
-- `allow_nullable_key`.  Measured across all 667,809 rows, exactly five columns
-- ever carry a NULL:
--
--     quote_mint       167,278  (25.05%)  -- absent before 2026-05-21
--     death_age_slot     4,938  ( 0.74%)  -- censored trajectories
--     death_age_incl        28  ( 0.00%)
--     death_age_excl        17  ( 0.00%)
--     accel                  1  ( 0.00%)  -- §3 f2, zero denominator
--
-- Those five are Nullable; the other 55 are not.  The load asserts that the
-- per-column NULL counts match the parquet exactly, so this is checked, not assumed.
--
-- Timestamps stay String because CANON stores them as strings (that is what the
-- Dune API returned); the launch-window assert parses them at query time rather
-- than changing the stored type.
--
-- The holdout is never loaded here: `src/load_clickhouse.py` refuses any path
-- under data/holdout/ (spec §6.1).

CREATE DATABASE IF NOT EXISTS flow;

DROP TABLE IF EXISTS flow.burst;

CREATE TABLE flow.burst
(
    `accel`                 Nullable(Float64),
    `age_min`               String,
    `block_time`            String,
    `burst_age_slot`        Int64,
    `censored_excl`         Bool,
    `censored_incl`         Bool,
    `curve_progress`        Float64,
    `death_age_excl`        Nullable(Int64),
    `death_age_incl`        Nullable(Int64),
    `death_age_slot`        Nullable(Float64),
    `depth_x`               Float64,
    `event_seq`             Int64,
    `fwd_net_flow_12slot`   Float64,
    `fwd_net_flow_37slot`   Float64,
    `fwd_net_flow_5slot`    Float64,
    `hazard_censored`       Bool,
    `ix_index`              Int64,
    `launch_window_guard`   Int64,
    `mayhem`                Bool,
    `mayhem_at_launch`      Bool,
    `minute_bucket`         String,
    `n_buyers_12slot`       Int64,
    `n_trades_25slot`       Int64,
    `net_flow_12slot`       Float64,
    `net_flow_25slot`       Float64,
    `net_flow_3slot`        Float64,
    `net_flow_5slot`        Float64,
    `nf3_excl_pre_1`        Float64,
    `nf3_excl_pre_2`        Float64,
    `nf3_traj_75_incl_pre`  Array(Float64),
    `nonzero_excl`          Int64,
    `nonzero_incl`          Int64,
    `oh`                    Float64,
    `oh_conc`               Float64,
    `oh_n_wallets`          Int64,
    `oh_ratio`              Float64,
    `qual_005`              Bool,
    `qual_020`              Bool,
    `quote_mint`            Nullable(String),
    `round_frac_25slot`     Float64,
    `size_cv_25slot`        Float64,
    `slot`                  Int64,
    `token_created_at`      String,
    `token_mint`            String,
    `traj_len`              Int64,
    `trigger_is_buy`        Bool,
    `trigger_sol`           Float64,
    `trigger_tokens`        Float64,
    `trigger_wallet`        String,
    `tx_index`              Int64,
    `v_latency_1slot`       Float64,
    `v_latency_2slot`       Float64,
    `v_latency_3slot`       Float64,
    `v_latency_7slot`       Float64,
    `v_latency_8slot`       Float64,
    `x0_lam`                Int64,
    `x_at_plus12`           Float64,
    `x_at_plus37`           Float64,
    `x_at_plus5`            Float64,
    `y0_units`              Int64,

    -- §4.3 fixes the trajectory at 75 slots; enforced on every insert.
    CONSTRAINT traj_len_75 CHECK length(`nf3_traj_75_incl_pre`) = 75
)
ENGINE = MergeTree
ORDER BY (`token_mint`, `slot`, `tx_index`, `ix_index`);
