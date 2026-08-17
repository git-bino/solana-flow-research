"""ClickHouse storage — spec §2.3, §2.4.

  python -m src.load_clickhouse start     # launch the local server
  python -m src.load_clickhouse schema    # create database + tables
  python -m src.load_clickhouse load      # load data/dev/*.parquet
  python -m src.load_clickhouse sanity    # §2.4 sanity counts

Tables follow §2.3 exactly and then add columns the spec's checks require but its
schema block does not name:

  ix_index                     intra-transaction ordering (see decisions.md);
                               (slot, tx_index) alone cannot order two trades
                               that share a transaction, which bundles routinely do
  sol_lamports / token_units   the exact integer amounts.  §2.3 asks for DOUBLE
                               `sol_amount`, which is kept, but reconstruction runs
                               on integers so it carries no rounding at all
  vsol_post / vtoken_post      on-chain virtual reserves after the trade: the
                               ground truth that validation checks 1, 2 and 5
                               compare the reconstruction against
  fee_lamports                 fee as reported by the source, when it reports one
                               (§0.3 evidence)
  split                        'dev' — the holdout never enters this database

The holdout is not loaded here at all.  `load` refuses any file under
data/holdout/ (spec §6.1): the seal is enforced in code, not by convention.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import clickhouse_connect

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

CH_CONFIG = config.CH_DATA / "config.xml"

CONFIG_XML = """<clickhouse>
    <logger><level>warning</level>
        <log>{path}/logs/server.log</log>
        <errorlog>{path}/logs/error.log</errorlog></logger>
    <http_port>{http}</http_port>
    <tcp_port>9000</tcp_port>
    <listen_host>127.0.0.1</listen_host>
    <path>{path}/store/</path>
    <tmp_path>{path}/tmp/</tmp_path>
    <user_files_path>{path}/user_files/</user_files_path>
    <mark_cache_size>536870912</mark_cache_size>
    <users>
        <default><password></password>
            <networks><ip>127.0.0.1</ip></networks>
            <profile>default</profile><quota>default</quota>
            <access_management>1</access_management></default>
    </users>
    <profiles><default><max_memory_usage>8000000000</max_memory_usage></default></profiles>
    <quotas><default><interval><duration>3600</duration></interval></default></quotas>
</clickhouse>
"""

EVENT_DDL = f"""
CREATE TABLE IF NOT EXISTS {config.CH_DATABASE}.event
(
    token_mint    LowCardinality(String),
    slot          UInt64,
    block_time    DateTime64(3, 'UTC'),
    tx_index      UInt32,
    ix_index      UInt32,
    tx_id         String,
    wallet        String,
    side          Enum8('buy' = 1, 'sell' = 2),
    sol_amount    Float64,      -- SOL, as §2.3 specifies
    token_amount  Float64,      -- tokens, as §2.3 specifies
    sol_lamports  UInt64,       -- exact, drives reconstruction
    token_units   UInt64,       -- exact
    x_pre         Float64,      -- reconstructed, SOL
    x_post        Float64,      -- reconstructed, SOL
    x_pre_lamports   UInt64,
    x_post_lamports  UInt64,
    y_pre_units      UInt64,
    y_post_units     UInt64,
    vsol_post     UInt64,       -- on-chain virtual SOL reserve after trade
    vtoken_post   UInt64,       -- on-chain virtual token reserve after trade
    fee_lamports  UInt64,
    split         LowCardinality(String) DEFAULT 'dev'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(block_time)
ORDER BY (token_mint, slot, tx_index, ix_index)
"""

TOKEN_DDL = f"""
CREATE TABLE IF NOT EXISTS {config.CH_DATABASE}.token
(
    token_mint    LowCardinality(String),
    created_at    DateTime64(3, 'UTC'),
    creator       String,
    create_slot   UInt64,
    migrated      UInt8,        -- label only, never a filter (§2.2)
    migrated_at   Nullable(DateTime64(3, 'UTC')),
    in_sample     UInt8,
    split         LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (token_mint)
"""


def client(database: str | None = config.CH_DATABASE):
    return clickhouse_connect.get_client(
        host=config.CH_HOST, port=config.CH_PORT, database=database or "default"
    )


def wait_ready(timeout: int = 60) -> None:
    import logging

    logging.getLogger("clickhouse_connect").setLevel(logging.CRITICAL)  # readiness poll noise
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client(database=None).command("SELECT 1")
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("ClickHouse did not become ready")


def cmd_start(args: argparse.Namespace) -> None:
    if not config.CH_BINARY.exists():
        raise SystemExit(f"ClickHouse binary not found at {config.CH_BINARY}")
    for sub in ("logs", "store", "tmp", "user_files"):
        (config.CH_DATA / sub).mkdir(parents=True, exist_ok=True)
    CH_CONFIG.write_text(CONFIG_XML.format(path=config.CH_DATA, http=config.CH_PORT))
    try:
        client(database=None).command("SELECT 1")
        print("ClickHouse already running")
        return
    except Exception:
        pass
    log = (config.CH_DATA / "logs" / "stdout.log").open("a")
    subprocess.Popen(
        [str(config.CH_BINARY), "server", f"--config-file={CH_CONFIG}"],
        stdout=log, stderr=log, start_new_session=True,
    )
    wait_ready()
    version = client(database=None).command("SELECT version()")
    print(f"ClickHouse {version} ready on {config.CH_HOST}:{config.CH_PORT}")


def cmd_schema(args: argparse.Namespace) -> None:
    ch = client(database=None)
    ch.command(f"CREATE DATABASE IF NOT EXISTS {config.CH_DATABASE}")
    ch.command(EVENT_DDL)
    ch.command(TOKEN_DDL)
    for table in ("event", "token"):
        cols = ch.query(
            "SELECT name, type FROM system.columns WHERE database=%(d)s AND table=%(t)s "
            "ORDER BY position", parameters={"d": config.CH_DATABASE, "t": table}
        ).result_rows
        print(f"{config.CH_DATABASE}.{table}: {len(cols)} columns")
    order = ch.query(
        "SELECT sorting_key FROM system.tables WHERE database=%(d)s AND name='event'",
        parameters={"d": config.CH_DATABASE},
    ).result_rows[0][0]
    assert order.replace(" ", "") == "token_mint,slot,tx_index,ix_index", order
    print(f"event ORDER BY ({order})  [§2.4]")


def _parquet_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.parquet"))


def cmd_load(args: argparse.Namespace) -> None:
    import pandas as pd

    source = Path(args.path) if args.path else config.DEV
    resolved = source.resolve()
    if config.HOLDOUT.resolve() in [resolved, *resolved.parents]:
        raise SystemExit(
            "refusing to load from data/holdout/: the holdout stays sealed until "
            "Phase 7 (spec §6.1)"
        )
    ch = client()
    for path in _parquet_files(resolved):
        table = "token" if path.stem.startswith("token") else "event"
        frame = pd.read_parquet(path)
        if "split" in frame.columns and (frame["split"] != "dev").any():
            raise SystemExit(f"{path.name} contains non-dev rows; refusing to load")
        ch.insert_df(table, frame)
        print(f"loaded {len(frame):,} rows from {path.name} -> {table}")
    cmd_sanity(args)


def cmd_sanity(args: argparse.Namespace) -> None:
    """§2.4 sanity: token count, events per day, reserve continuity."""
    ch = client()
    tokens, events = ch.query(
        f"SELECT uniqExact(token_mint), count() FROM {config.CH_DATABASE}.event"
    ).result_rows[0]
    print(f"\ntokens with >=1 event: {tokens:,}   events: {events:,}")
    print("\nevents per day:")
    for day, n, tok in ch.query(
        f"SELECT toDate(block_time) d, count() n, uniqExact(token_mint) t "
        f"FROM {config.CH_DATABASE}.event GROUP BY d ORDER BY d"
    ).result_rows:
        print(f"  {day}  {n:>12,}  tokens={tok:>8,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start")
    sub.add_parser("schema")
    load = sub.add_parser("load")
    load.add_argument("--path", help="directory of parquet files (default data/dev)")
    sub.add_parser("sanity")
    args = parser.parse_args()
    if not hasattr(args, "path"):
        args.path = None
    {"start": cmd_start, "schema": cmd_schema, "load": cmd_load, "sanity": cmd_sanity}[args.cmd](args)


if __name__ == "__main__":
    main()
