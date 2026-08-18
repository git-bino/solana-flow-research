"""ClickHouse storage for the §2.3 burst rows — spec v1.3, §2.3 / §2.4.

  python -m src.load_clickhouse start     # launch the local server
  python -m src.load_clickhouse schema    # create flow.burst from sql/clickhouse_burst.sql
  python -m src.load_clickhouse load      # load data/extract/dev_chunk*.parquet
  python -m src.load_clickhouse verify    # post-load asserts (see `verify`)

v1.3 replaced the event-level design with burst rows computed inside Dune, so
this module no longer stores raw trades: one row per burst_start, 60 columns,
exactly `src/extract_schema.py`'s CANON.  Every parquet goes through
`load_chunk()`, so the per-chunk type drift (quote_mint, death_age_*) is
normalised on the way in and never reaches the table.

The holdout is not loaded here at all.  `iter_chunks` refuses any path under
data/holdout/ (spec §6.1): the seal is enforced in code, not by convention.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import clickhouse_connect
import pyarrow as pa
import pyarrow.compute as pc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.extract_schema import CANON, KEY, load_chunk  # noqa: E402

DDL = Path(__file__).resolve().parent.parent / "sql" / "clickhouse_burst.sql"
EXTRACT = config.DATA / "extract"
HOLDOUT = config.DATA / "holdout"
TABLE = "flow.burst"

#: The dev chunks, in launch-window order.  chunk 1 is the v3 rewrite: same rows
#: as v2, reordered to the canonical column order (docs/phase0_extract_run.md).
CHUNKS = ["dev_chunk01_v3.parquet"] + [f"dev_chunk{n:02d}.parquet" for n in range(2, 7)]

LAUNCH_FROM, LAUNCH_TO = "2026-05-10", "2026-07-03"


def client():
    return clickhouse_connect.get_client(host="127.0.0.1", port=config.CH_PORT)


def iter_chunks():
    for name in CHUNKS:
        path = EXTRACT / name
        if HOLDOUT in path.resolve().parents:
            raise RuntimeError(f"refusing to load a holdout file: {path}")
        if not path.exists():
            raise FileNotFoundError(path)
        yield path


# --- commands --------------------------------------------------------------

def cmd_start(_: argparse.Namespace) -> None:
    if subprocess.run(["pgrep", "-f", "clickhouse server"],
                      capture_output=True).returncode == 0:
        print("server already running")
        return
    config.CH_DATA.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [str(config.CH_BINARY), "server", "--config-file",
         str(config.CH_DATA / "config.xml")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        time.sleep(1)
        try:
            client().command("SELECT 1")
            print("server up")
            return
        except Exception:
            continue
    raise RuntimeError("server did not come up within 30s")


def cmd_schema(_: argparse.Namespace) -> None:
    ch = client()
    # Strip comment lines BEFORE splitting on ';'.  Splitting first breaks on any
    # semicolon inside a comment -- the same defect that cut a Dune query in half
    # on 2026-08-18, reproduced here by the word "null; taken literally".
    body = "\n".join(line for line in DDL.read_text().splitlines()
                     if not line.strip().startswith("--"))
    for statement in body.split(";"):
        if statement.strip():
            ch.command(statement)
    print(f"{TABLE} created from {DDL.name}")


def cmd_load(_: argparse.Namespace) -> None:
    ch = client()
    total = 0
    for path in iter_chunks():
        table = load_chunk(path)
        assert table.schema.equals(CANON), f"{path.name}: not canonical after cast"
        ch.insert_arrow(TABLE, table)
        total += table.num_rows
        print(f"  {path.name:<24} +{table.num_rows:>8,}  -> {total:>9,}")
    rows = ch.command(f"SELECT count() FROM {TABLE}")
    print(f"loaded {total:,}; table holds {rows:,}")


def cmd_verify(_: argparse.Namespace) -> None:
    """Post-load asserts.  Structural only — no outcome distributions (§6.7)."""
    ch = client()
    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
        if not ok:
            fails.append(name)

    # --- counts, against the parquet rather than against a remembered number
    per_chunk = {p.name: load_chunk(p).num_rows for p in iter_chunks()}
    expected = sum(per_chunk.values())
    rows = ch.command(f"SELECT count() FROM {TABLE}")
    check("row count == sum of chunk row counts", rows == expected,
          f"{rows:,} == {' + '.join(f'{n:,}' for n in per_chunk.values())}")

    distinct_keys = ch.command(
        f"SELECT uniqExact(({', '.join(KEY)})) FROM {TABLE}")
    check("burst key unique", distinct_keys == rows, f"{distinct_keys:,} of {rows:,}")

    bad_len = ch.command(
        f"SELECT countIf(length(nf3_traj_75_incl_pre) != 75) FROM {TABLE}")
    check("length(nf3_traj_75_incl_pre) == 75 for every row", bad_len == 0)

    bad_oh = ch.command(f"SELECT countIf(oh < 0) FROM {TABLE}")
    check("oh >= 0", bad_oh == 0)
    bad_conc = ch.command(
        f"SELECT countIf(oh_conc < 0 OR oh_conc > 1) FROM {TABLE}")
    check("0 <= oh_conc <= 1", bad_conc == 0)
    bad_ratio = ch.command(f"SELECT countIf(oh_ratio < 0) FROM {TABLE}")
    check("oh_ratio >= 0", bad_ratio == 0)

    # Both sides pinned to UTC.  This server runs in Asia/Ulaanbaatar, so a bare
    # parseDateTimeBestEffort() converts these UTC strings to local time and shifts
    # them +8h -- which reported 6,562 rows outside a window they are inside.  That
    # was a defect in the assert, not in the data (the raw strings run
    # 2026-05-10 00:00:12 UTC .. 2026-07-02 23:59:39 UTC).
    outside = ch.command(
        f"SELECT countIf(parseDateTimeBestEffort(token_created_at, 'UTC') "
        f"  <  toDateTime('{LAUNCH_FROM} 00:00:00', 'UTC') "
        f"OR parseDateTimeBestEffort(token_created_at, 'UTC') "
        f"  >= toDateTime('{LAUNCH_TO} 00:00:00', 'UTC')) FROM {TABLE}")
    check(f"token_created_at in [{LAUNCH_FROM}, {LAUNCH_TO}) UTC", outside == 0)

    # --- distinct tokens and NULL counts, both compared to the parquet
    tokens_ch = ch.command(f"SELECT uniqExact(token_mint) FROM {TABLE}")
    seen: set[str] = set()
    parquet_nulls = {c: 0 for c in CANON.names}
    for path in iter_chunks():
        t = load_chunk(path)
        seen |= set(t.column("token_mint").to_pylist())
        for c in CANON.names:
            parquet_nulls[c] += t.column(c).null_count
    check("distinct token_mint == parquet", tokens_ch == len(seen),
          f"{tokens_ch:,} == {len(seen):,}")

    nullable = [c for c, n in parquet_nulls.items() if n]
    ch_nulls = {}
    for c in CANON.names:
        ch_nulls[c] = (ch.command(f"SELECT countIf(isNull({c})) FROM {TABLE}")
                       if c in nullable else 0)
    mismatched = {c: (parquet_nulls[c], ch_nulls[c]) for c in CANON.names
                  if parquet_nulls[c] != ch_nulls[c]}
    check("per-column NULL counts == parquet", not mismatched,
          str(mismatched) if mismatched else f"60 columns, {len(nullable)} nullable")

    check("data/holdout/ empty", not any(HOLDOUT.iterdir()))

    # --- 1,000 random rows, every column compared value by value
    sampled, diffs = _compare_sample(ch, n=1000)
    check("1,000 sampled rows match the parquet in every column", not diffs,
          str(diffs)[:300] if diffs else f"{sampled:,} rows x 60 columns")

    print(f"\n{'ALL PASS' if not fails else 'FAILED: ' + '; '.join(fails)}")
    if fails:
        sys.exit(1)


def _compare_sample(ch, n: int) -> tuple[int, list[str]]:
    """Pull n random keys back out of ClickHouse and diff them against the parquet.

    Arrays are compared element by element, so a trajectory that lost or reordered
    a slot shows up rather than passing on a length check.
    """
    keys = ch.query(
        f"SELECT {', '.join(KEY)} FROM {TABLE} ORDER BY cityHash64({', '.join(KEY)}) "
        f"LIMIT {n}").result_rows
    wanted = {tuple(k) for k in keys}

    parquet_rows: dict[tuple, dict] = {}
    for path in iter_chunks():
        t = load_chunk(path)
        cols = {c: t.column(c).to_pylist() for c in CANON.names}
        for i in range(t.num_rows):
            key = tuple(cols[c][i] for c in KEY)
            if key in wanted:
                parquet_rows[key] = {c: cols[c][i] for c in CANON.names}

    diffs: list[str] = []
    if len(parquet_rows) != len(wanted):
        diffs.append(f"{len(wanted) - len(parquet_rows)} sampled keys absent from parquet")

    rows = ch.query(
        f"SELECT {', '.join(f'`{c}`' for c in CANON.names)} FROM {TABLE} "
        f"WHERE ({', '.join(KEY)}) IN {tuple(sorted(wanted))}").result_rows
    for row in rows:
        got = dict(zip(CANON.names, row))
        key = tuple(got[c] for c in KEY)
        want = parquet_rows.get(key)
        if want is None:
            diffs.append(f"{key}: not in parquet")
            continue
        for c in CANON.names:
            a, b = want[c], got[c]
            if isinstance(a, list):
                if len(a) != len(b) or any(x != y for x, y in zip(a, b)):
                    diffs.append(f"{key}.{c}: array differs")
            elif a != b and not (a is None and b is None):
                diffs.append(f"{key}.{c}: {a!r} != {b!r}")
        if len(diffs) > 20:
            break
    return len(rows), diffs


def cmd_sanity(_: argparse.Namespace) -> None:
    """Structural counts only.  Anything about §4.2/§4.3 outcomes belongs to Phase 3."""
    ch = client()
    print(f"rows           {ch.command(f'SELECT count() FROM {TABLE}'):,}")
    print(f"tokens         {ch.command(f'SELECT uniqExact(token_mint) FROM {TABLE}'):,}")
    mayhem = ch.command(f"SELECT countIf(mayhem) FROM {TABLE}")
    rows = ch.command(f"SELECT count() FROM {TABLE}")
    print(f"mayhem rows    {mayhem:,}  ({100 * mayhem / rows:.2f}%)")
    print("\nbursts by launch day:")
    for day, n, t in ch.query(
        f"SELECT toDate(parseDateTimeBestEffort(token_created_at, 'UTC')) AS d, "
        f"count() AS n, uniqExact(token_mint) AS t "
        f"FROM {TABLE} GROUP BY d ORDER BY d"
    ).result_rows:
        print(f"  {day}  bursts {n:>7,}  tokens {t:>7,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in [("start", cmd_start), ("schema", cmd_schema), ("load", cmd_load),
                     ("verify", cmd_verify), ("sanity", cmd_sanity)]:
        sub.add_parser(name).set_defaults(fn=fn)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
