"""ClickHouse storage for the v2 burst rows — `flow.burst_v2`, 80 columns.

  python -m src.load_clickhouse_v2 schema   # create flow.burst_v2
  python -m src.load_clickhouse_v2 load     # load data/extract_v2/dev_chunk*.parquet
  python -m src.load_clickhouse_v2 verify   # post-load asserts

`flow.burst` (v1, 60 columns, 667,809 rows) is NOT touched: the audit trail
needs it readable, so v2 lands beside it in its own table.

Nullable is declared from the measured NULL counts, not from Arrow's default.
`CANON_V2` marks all 80 columns nullable because that is Arrow's default; taken
literally the sorting key would be Nullable too, which ClickHouse allows only
under `allow_nullable_key`.  Chunk 1 has NULLs in exactly four columns
(quote_mint, death_age_slot, death_age_incl, death_age_excl) and the post-load
assert compares every column's NULL count against the parquet, so this is
checked rather than assumed -- the same reasoning the v1 loader recorded.

Every timestamp comparison pins 'UTC'.  The server runs Asia/Ulaanbaatar, and a
bare `parseDateTimeBestEffort` shifted the v1 launch-window assert by +8h and
failed 6,562 good rows (docs/phase0_clickhouse_load.md).

The holdout is not loadable here: `iter_chunks` refuses any path under
data/holdout/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import clickhouse_connect
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.extract_schema import CANON_V2, KEY_V2, load_chunk_v2  # noqa: E402

EXTRACT = config.DATA / "extract_v2"
HOLDOUT = config.DATA / "holdout"
TABLE = "flow.burst_v2"
DDL_PATH = config.REPO / "sql" / "clickhouse_burst_v2.sql"

#: Columns that actually carry NULLs, measured on chunk 1 and re-asserted on load.
NULLABLE = {"quote_mint", "death_age_slot", "death_age_incl", "death_age_excl"}

_TYPE = {
    pa.large_string(): "String",
    pa.int64(): "Int64",
    pa.float64(): "Float64",
    pa.bool_(): "Bool",
    pa.list_(pa.float64()): "Array(Float64)",
}


def client():
    return clickhouse_connect.get_client(host="127.0.0.1", port=8123)


def iter_chunks():
    for p in sorted(EXTRACT.glob("dev_chunk*.parquet")):
        if HOLDOUT in p.resolve().parents:
            raise RuntimeError(f"refusing to load a holdout file: {p}")
        yield p


def ddl() -> str:
    lines = []
    for f in CANON_V2:
        t = _TYPE[f.type]
        if f.name in NULLABLE:
            t = f"Nullable({t})"
        lines.append(f"    `{f.name}` {t}")
    cols = ",\n".join(lines)
    key = ", ".join(f"`{c}`" for c in KEY_V2)
    return (
        "CREATE DATABASE IF NOT EXISTS flow;\n\n"
        f"DROP TABLE IF EXISTS {TABLE};\n\n"
        f"CREATE TABLE {TABLE}\n(\n{cols},\n\n"
        "    CONSTRAINT traj_len_75 CHECK length(`nf3_traj_75_incl_pre`) = 75\n"
        f")\nENGINE = MergeTree\nORDER BY ({key});\n"
    )


def cmd_schema(_: argparse.Namespace) -> None:
    text = ddl()
    DDL_PATH.write_text(text)
    ch = client()
    # Comments are stripped before splitting on ';' -- a semicolon inside a DDL
    # comment split the v1 statement mid-sentence and produced a SYNTAX_ERROR.
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    for stmt in (s.strip() for s in body.split(";")):
        if stmt:
            ch.command(stmt)
    print(f"{TABLE} created, {len(CANON_V2.names)} columns, "
          f"{len(NULLABLE)} nullable -> {DDL_PATH}")


def cmd_load(_: argparse.Namespace) -> None:
    ch = client()
    total = 0
    for p in iter_chunks():
        t = load_chunk_v2(p)
        # Drop the Arrow null flag on the 76 columns declared NOT NULL, so the
        # insert matches the table rather than relying on ClickHouse coercion.
        ch.insert_arrow(TABLE, t)
        total += t.num_rows
        print(f"  {p.name:26} + {t.num_rows:>9,}  ->  {total:>9,}")
    print(f"total {total:,}")


def cmd_verify(_: argparse.Namespace) -> None:
    ch = client()
    files = list(iter_chunks())
    tables = [load_chunk_v2(p) for p in files]
    expect_rows = sum(t.num_rows for t in tables)
    results: list[tuple[str, bool, str]] = []

    def add(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    n = ch.query(f"SELECT count() FROM {TABLE}").result_rows[0][0]
    add("мөрийн тоо = parquet", n == expect_rows, f"{n:,} vs {expect_rows:,}")

    key = ", ".join(f"`{c}`" for c in KEY_V2)
    uniq = ch.query(f"SELECT uniqExact(({key})) FROM {TABLE}").result_rows[0][0]
    add("түлхүүр unique", uniq == n, f"{uniq:,} / {n:,}")

    bad = ch.query(
        f"SELECT countIf(length(nf3_traj_75_incl_pre) != 75) FROM {TABLE}"
    ).result_rows[0][0]
    add("length(nf3_traj_75_incl_pre) = 75", bad == 0, f"зөрчил {bad}")

    for col in ("oh_a", "oh_b"):
        bad = ch.query(f"SELECT countIf({col} < 0) FROM {TABLE}").result_rows[0][0]
        add(f"{col} >= 0", bad == 0, f"зөрчил {bad}")
    for col in ("oh_conc_a", "oh_conc_b"):
        bad = ch.query(
            f"SELECT countIf({col} < 0 OR {col} > 1) FROM {TABLE}"
        ).result_rows[0][0]
        add(f"0 <= {col} <= 1", bad == 0, f"зөрчил {bad}")

    mismatch = []
    for name in CANON_V2.names:
        want = sum(t[name].null_count for t in tables)
        got = ch.query(f"SELECT countIf(`{name}` IS NULL) FROM {TABLE}"
                       ).result_rows[0][0] if name in NULLABLE else 0
        if got != want:
            mismatch.append(f"{name}: {got} vs {want}")
    add("NULL тоо = parquet", not mismatch, "; ".join(mismatch) or "80 багана таарав")

    n_bad, detail = _compare_sample(ch, tables, 1000)
    add("санамсаргүй 1,000 мөр × 80 багана", n_bad == 0, detail)

    add("data/holdout/ хоосон", not any(HOLDOUT.iterdir()) if HOLDOUT.exists() else True)

    width = max(len(r[0]) for r in results)
    fails = 0
    for name, ok, detail in results:
        fails += not ok
        print(f"{name:<{width}}  {'PASS' if ok else 'FAIL'}  {detail}")
    print(f"\n{len(results) - fails} / {len(results)} PASS")
    if fails:
        raise SystemExit(1)


def _compare_sample(ch, tables, k: int) -> tuple[int, str]:
    """Element-by-element comparison of a deterministic sample of rows.

    Arrays are compared element by element rather than by length, so a dropped
    slot or a reordered trajectory is caught here.
    """
    key = ", ".join(f"`{c}`" for c in KEY_V2)
    cols = ", ".join(f"`{c}`" for c in CANON_V2.names)
    rows = ch.query(
        f"SELECT {cols} FROM {TABLE} ORDER BY cityHash64(({key})) LIMIT {k}"
    ).result_rows
    want = {}
    for t in tables:
        d = t.to_pydict()
        for i in range(t.num_rows):
            want[tuple(d[c][i] for c in KEY_V2)] = [d[c][i] for c in CANON_V2.names]
    pos = [CANON_V2.names.index(c) for c in KEY_V2]
    bad = 0
    first = ""
    for r in rows:
        k_ = tuple(r[p] for p in pos)
        w = want.get(k_)
        if w is None:
            bad += 1
            continue
        for name, a, b in zip(CANON_V2.names, r, w):
            if isinstance(b, list):
                same = list(a) == list(b)
            elif a is None or b is None:
                same = a is b or (a is None and b is None)
            elif isinstance(b, float):
                same = a == b
            else:
                same = a == b
            if not same:
                bad += 1
                first = first or f"{name} @ {k_[0][:8]}…: {a!r} vs {b!r}"
                break
    return bad, f"{len(rows)} мөр, зөрчил {bad}" + (f" ({first})" if first else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("schema", cmd_schema), ("load", cmd_load), ("verify", cmd_verify)):
        sub.add_parser(name).set_defaults(fn=fn)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
