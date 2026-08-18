"""Canonical Arrow schema for the §2.3 burst-row extract, and a loader that casts to it.

Why this exists
---------------
Each chunk parquet was written from the JSON rows Dune returned, so its column
types were *inferred from that chunk's content* rather than declared.  Inference
drifts wherever a column happens to be all-NULL or all-non-NULL in one chunk:

  quote_mint          chunk 1's launch window ends before 2026-05-21, when the
                      column first appears, so all 133,877 values are NULL and
                      parquet stored the column as arrow `null`.  Chunks 2+ have
                      values and stored `large_string`.
  death_age_incl      NULL on censored rows.  Chunks with at least one censored
  death_age_excl      row inferred `double`; chunk 4 (incl) and chunk 5 (excl)
                      had none and inferred `int64`.

Nothing was lost or altered — Dune's own result schema is identical across
chunks — but the files cannot be concatenated until the types agree.  This
module declares the schema explicitly and casts on read.  **The parquet files
are never rewritten**: they are committed evidence of what was extracted.

Type choices
------------
Every column below is nullable, which is Arrow's default and matches the
extract: only NOT-NULL-by-construction columns would want otherwise, and
declaring that would buy nothing here.

`death_age_incl` / `death_age_excl` are **nullable int64**, chosen from a
measurement rather than a preference: across chunks 1 (v3) and 2-5, 1,375,502
non-null values were checked and **0** were fractional.  They are ages in slots,
so int64 is the honest type and NULL keeps its meaning (the row is censored --
the trajectory never died inside the 75-slot window).

`death_age_slot` is left `float64`, the type every chunk already has, per the
declared rule that the other 57 columns keep their existing type.  Worth
recording that it is integer-valued too (550,535 non-null values, 0 fractional)
and would be nullable int64 under the same reasoning applied to the two columns
above; changing it is a research decision, not one this module makes.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

#: The authoritative column names, order and types for every extract chunk.
#: Order matches what the Dune API returns (keys sorted), which is the order
#: every chunk parquet was written in.
CANON = pa.schema([
    ("accel", pa.float64()),
    ("age_min", pa.large_string()),
    ("block_time", pa.large_string()),
    ("burst_age_slot", pa.int64()),
    ("censored_excl", pa.bool_()),
    ("censored_incl", pa.bool_()),
    ("curve_progress", pa.float64()),
    ("death_age_excl", pa.int64()),          # measured integral, nullable
    ("death_age_incl", pa.int64()),          # measured integral, nullable
    ("death_age_slot", pa.float64()),
    ("depth_x", pa.float64()),
    ("event_seq", pa.int64()),
    ("fwd_net_flow_12slot", pa.float64()),
    ("fwd_net_flow_37slot", pa.float64()),
    ("fwd_net_flow_5slot", pa.float64()),
    ("hazard_censored", pa.bool_()),
    ("ix_index", pa.int64()),
    ("launch_window_guard", pa.int64()),
    ("mayhem", pa.bool_()),
    ("mayhem_at_launch", pa.bool_()),
    ("minute_bucket", pa.large_string()),
    ("n_buyers_12slot", pa.int64()),
    ("n_trades_25slot", pa.int64()),
    ("net_flow_12slot", pa.float64()),
    ("net_flow_25slot", pa.float64()),
    ("net_flow_3slot", pa.float64()),
    ("net_flow_5slot", pa.float64()),
    ("nf3_excl_pre_1", pa.float64()),
    ("nf3_excl_pre_2", pa.float64()),
    ("nf3_traj_75_incl_pre", pa.list_(pa.float64())),
    ("nonzero_excl", pa.int64()),
    ("nonzero_incl", pa.int64()),
    ("oh", pa.float64()),
    ("oh_conc", pa.float64()),
    ("oh_n_wallets", pa.int64()),
    ("oh_ratio", pa.float64()),
    ("qual_005", pa.bool_()),
    ("qual_020", pa.bool_()),
    ("quote_mint", pa.large_string()),       # arrow `null` in chunk 1
    ("round_frac_25slot", pa.float64()),
    ("size_cv_25slot", pa.float64()),
    ("slot", pa.int64()),
    ("token_created_at", pa.large_string()),
    ("token_mint", pa.large_string()),
    ("traj_len", pa.int64()),
    ("trigger_is_buy", pa.bool_()),
    ("trigger_sol", pa.float64()),
    ("trigger_tokens", pa.float64()),
    ("trigger_wallet", pa.large_string()),
    ("tx_index", pa.int64()),
    ("v_latency_1slot", pa.float64()),
    ("v_latency_2slot", pa.float64()),
    ("v_latency_3slot", pa.float64()),
    ("v_latency_7slot", pa.float64()),
    ("v_latency_8slot", pa.float64()),
    ("x0_lam", pa.int64()),
    ("x_at_plus12", pa.float64()),
    ("x_at_plus37", pa.float64()),
    ("x_at_plus5", pa.float64()),
    ("y0_units", pa.int64()),
])

#: The burst key, unique within and across chunks (spec §2.3).
KEY = ["token_mint", "slot", "tx_index", "ix_index"]


def load_chunk(path: str | Path) -> pa.Table:
    """Read one extract parquet and cast it to `CANON`.

    The cast is Arrow's default *safe* cast, so a value that cannot be
    represented in the target type raises rather than being silently truncated
    -- a float64 death age of 3.5 would fail here instead of becoming 3.
    """
    table = pq.read_table(path)
    missing = set(CANON.names) - set(table.column_names)
    extra = set(table.column_names) - set(CANON.names)
    if missing or extra:
        raise ValueError(f"{path}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return table.select(CANON.names).cast(CANON)
