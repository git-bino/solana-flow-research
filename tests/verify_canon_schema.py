"""Prove the canonical cast changes no value and no NULL, on every chunk."""
import sys
from pathlib import Path

ROOT = Path("/Users/munkhjargal/Desktop/solana-flow-research")
sys.path.insert(0, str(ROOT))

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from src.extract_schema import CANON, KEY, load_chunk

FILES = [ROOT / "data/extract/dev_chunk01_v3.parquet"] + [
    ROOT / f"data/extract/dev_chunk{n:02d}.parquet" for n in range(2, 7)
]
FILES = [f for f in FILES if f.exists()]

fails, total_rows, per_chunk = [], 0, []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def values_equal(before: pa.ChunkedArray, after: pa.ChunkedArray) -> tuple[bool, int]:
    """Elementwise equality treating NULL==NULL as equal.  Returns (ok, n_diff)."""
    b, a = before.combine_chunks(), after.combine_chunks()
    if pa.types.is_list(b.type) or pa.types.is_large_list(b.type):
        # compare the flattened values and the offsets that delimit them
        if b.null_count != a.null_count:
            return False, abs(b.null_count - a.null_count)
        fb, fa = pc.list_flatten(b), pc.list_flatten(a)
        if len(fb) != len(fa):
            return False, abs(len(fb) - len(fa))
        d = pc.sum(pc.cast(pc.not_equal(fb, fa), pa.int64())).as_py() or 0
        lb = pc.sum(pc.cast(pc.not_equal(pc.list_value_length(b),
                                         pc.list_value_length(a)), pa.int64())).as_py() or 0
        return d == 0 and lb == 0, d + lb
    if pa.types.is_null(b.type):
        # all-NULL source: equal iff the target is all-NULL too
        return a.null_count == len(a), len(a) - a.null_count
    neq = pc.not_equal(b, a)                      # NULL on either side -> NULL
    d = pc.sum(pc.cast(neq, pa.int64())).as_py() or 0
    nb = pc.is_null(b)
    nm = pc.sum(pc.cast(pc.not_equal(nb, pc.is_null(a)), pa.int64())).as_py() or 0
    return d == 0 and nm == 0, d + nm


print("=== per-chunk: cast must change nothing ===")
for f in FILES:
    raw = pq.read_table(f)
    cast = load_chunk(f)
    name = f.name
    total_rows += cast.num_rows
    per_chunk.append((name, cast.num_rows))

    ok_schema = cast.schema.equals(CANON)
    diffs, null_diffs = [], []
    for col in CANON.names:
        eq, n = values_equal(raw.column(col), cast.column(col))
        if not eq:
            diffs.append((col, n))
        if raw.column(col).null_count != cast.column(col).null_count:
            null_diffs.append((col, raw.column(col).null_count, cast.column(col).null_count))

    print(f"\n  {name}  ({cast.num_rows:,} rows)")
    check("    schema == CANON after cast", ok_schema)
    check("    every value identical before/after cast", not diffs,
          f"{len(CANON.names)} columns compared" if not diffs else str(diffs))
    check("    NULL counts identical before/after cast", not null_diffs,
          str(null_diffs) if null_diffs else "")

print("\n=== across chunks ===")
schemas = [load_chunk(f).schema for f in FILES]
check("all chunks share one schema after cast", all(s.equals(schemas[0]) for s in schemas))
check("that schema is CANON", schemas[0].equals(CANON))

combined = pa.concat_tables([load_chunk(f) for f in FILES])
check("concat row count == sum of chunk row counts",
      combined.num_rows == sum(n for _, n in per_chunk),
      f"{combined.num_rows:,} == {' + '.join(f'{n:,}' for _, n in per_chunk)}")
total_rows = combined.num_rows

keys = combined.select(KEY)
n_unique = pa.Table.from_batches(keys.to_batches()).group_by(KEY).aggregate([]).num_rows
check("burst key unique across all chunks", n_unique == total_rows,
      f"{n_unique:,} distinct of {total_rows:,}")

print(f"\n  chunks loaded: {', '.join(n for n, _ in per_chunk)}")
print(f"  total rows: {total_rows:,}")
print(f"\n{'ALL PASS' if not fails else 'FAILED: ' + '; '.join(fails)}")
