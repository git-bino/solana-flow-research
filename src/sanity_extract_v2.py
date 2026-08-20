"""Structural sanity for one v2 extract chunk.  No outcome distributions.

  python -m src.sanity_extract_v2 <chunk_number>

Every check here is structural: schema, keys, windows, NULL counts, and the
burst-set reconciliation against v1.  Nothing quantiles, deciles, correlates or
hazards any outcome column -- `fwd_net_flow*`, `oh_ratio*`, `death_age*` and
`x_at_plus*` are touched only by the bound asserts the brief lists.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow.compute as pc  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from src import config  # noqa: E402
from src.extract_schema import CANON_V2, KEY_V2  # noqa: E402
from src.run_extract_v2 import CHUNKS, OUT  # noqa: E402

X0_SOL = 30_000_000_000


def v1_keys(launch_from: str, launch_to: str) -> set:
    """v1 burst keys for the same launch window, from ClickHouse.

    v1 packs the instruction pair as `outer*64 + inner`; v2 exports the raw
    pair, so the comparison packs v2 rather than unpacking v1.
    """
    from src.load_clickhouse import client
    rows = client().query(
        "SELECT token_mint, slot, tx_index, ix_index FROM flow.burst "
        "WHERE parseDateTimeBestEffort(token_created_at, 'UTC') >= "
        "      parseDateTimeBestEffort(%(a)s, 'UTC') "
        "  AND parseDateTimeBestEffort(token_created_at, 'UTC') <  "
        "      parseDateTimeBestEffort(%(b)s, 'UTC')",
        parameters={"a": f"{launch_from} 00:00:00", "b": f"{launch_to} 00:00:00"},
    ).result_rows
    return {tuple(r) for r in rows}


def check(n: int) -> list[tuple[str, bool, str]]:
    lf, lt = CHUNKS[n]
    path = OUT / f"dev_chunk{n:02d}.parquet"
    t = pq.read_table(path)
    out: list[tuple[str, bool, str]] = []

    def add(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    add("schema нэр + дараалал", list(t.schema.names) == list(CANON_V2.names),
        f"{len(t.schema.names)} багана")
    add("schema arrow тип", [t.schema.field(i).type for i in range(len(t.schema))]
        == [CANON_V2.field(i).type for i in range(len(CANON_V2))])

    add("traj_len = 75", pc.all(pc.equal(t["traj_len"], 75)).as_py(),
        f"зөрчил {pc.sum(pc.cast(pc.not_equal(t['traj_len'], 75), 'int64')).as_py()}")
    for col in ("oh_a", "oh_b"):
        bad = pc.sum(pc.cast(pc.less(t[col], 0), "int64")).as_py()
        add(f"{col} >= 0", bad == 0, f"зөрчил {bad}")
    for col in ("oh_conc_a", "oh_conc_b"):
        bad = pc.sum(pc.cast(
            pc.or_(pc.less(t[col], 0), pc.greater(t[col], 1)), "int64")).as_py()
        add(f"0 <= {col} <= 1", bad == 0, f"зөрчил {bad}")

    keys = list(zip(*[t[c].to_pylist() for c in KEY_V2]))
    add("түлхүүр давхардал 0", len(keys) == len(set(keys)),
        f"{len(keys):,} мөр, {len(set(keys)):,} ялгаатай")

    created = t["token_created_at"].to_pylist()
    add("launch_time цонхонд",
        min(created)[:10] >= lf and max(created) < f"{lt} 00:00:00.000 UTC",
        f"[{min(created)}, {max(created)}]")

    prev = set()
    for m in range(1, n):
        p = OUT / f"dev_chunk{m:02d}.parquet"
        if p.exists():
            prev |= set(pq.read_table(p, columns=["token_mint"])["token_mint"].to_pylist())
    mints = set(t["token_mint"].to_pylist())
    add("өмнөх хэсгүүдтэй огтлолцол 0", len(prev & mints) == 0,
        f"{len(prev & mints)} давхацсан, өмнөх {len(prev):,} токен")

    add("x0 = 30e9 бүх токен", pc.all(pc.equal(t["x0_lam"], X0_SOL)).as_py(),
        f"ялгаатай x0 {len(set(t['x0_lam'].to_pylist()))}")

    nulls = {c: t[c].null_count for c in t.schema.names if t[c].null_count}
    add("NULL багана", True, ", ".join(f"{k}={v:,}" for k, v in sorted(nulls.items())) or "алга")

    per_day = Counter(c[:10] for c in created)
    lo, hi = min(per_day.values()), max(per_day.values())
    add("launch өдөр бүр burst-тэй", lo > 0,
        f"{len(per_day)} өдөр, min {lo:,} max {hi:,}, max/min {hi/lo:.2f}")

    got = {(m, s, x, o * 64 + i) for m, s, x, o, i in keys}
    want = v1_keys(lf, lt)
    add("v1-тэй burst олонлог ЯГ таарав", got == want,
        f"v2 {len(got):,} · v1 {len(want):,} · зөвхөн v2 {len(got - want):,} · "
        f"зөвхөн v1 {len(want - got):,}")
    return out


def main() -> None:
    n = int(sys.argv[1])
    rows = check(n)
    width = max(len(r[0]) for r in rows)
    fails = 0
    for name, ok, detail in rows:
        fails += not ok
        print(f"{name:<{width}}  {'PASS' if ok else 'FAIL'}  {detail}")
    print(f"\n{len(rows) - fails} / {len(rows)} PASS")
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
