"""A -- the path of `x` after it reaches 60: LOCAL FEASIBILITY CHECK.

    python -m src.path_after_60

This module does NOT answer A.  It measures, locally and at zero credit, exactly
which inputs A needs and which of them exist on this machine, so that the gap is
a counted fact rather than an assertion.  The task's own stop rule applies:

    "Хэрэв A-д шаардлагатай `x`-ийн зам локал дээр БАЙХГҮЙ бол ЗОГС, юу дутуу
     байгааг бич, надаас асуу -- Dune-аас шинэ дата ТАТАХГҮЙ."

It touches nothing but `flow.*` in the local ClickHouse.  No Dune client is
imported here; `dune.quantbino1695.result_flow_token_base` is a REMOTE view and
is not readable from this process.

WHAT A NEEDS
------------
Every one of A.1 .. A.6 is a statement about x(t) for a token over its whole
lifetime, anchored at `t_60`:

    A.1  total time with x >= 60, and `t_below_60`   -> continuous x(t), unbounded
    A.2  t_below_60 - t_60                           -> continuous x(t), unbounded
    A.3  min_x_after                                 -> continuous x(t), unbounded
    A.4  t_max_x - t_60                              -> continuous x(t) + max_x
    A.5  final_x                                     -> x at end of lifetime
    A.6  first crossing of 70/80/100/115 after t_60  -> continuous x(t), unbounded

and all six need the anchor `t_60` itself.

WHAT EXISTS LOCALLY
-------------------
`flow.burst_v2` holds BURST WINDOWS, not lifetimes.  Each row carries a 75-slot
forward trajectory (`nf3_traj_75_incl_pre`) plus the reserve at the trigger, from
which x(a) is reconstructible as `x_end_slot + cumf[a]` for a = 1..75 -- roughly
30 seconds, and only from a burst trigger.  Between bursts there is no path at
all.  `flow.event` and `flow.token`, which would have carried per-trade
`vsol_post` and therefore the full path, are EMPTY (0 rows) -- the v2 extract
loaded only `burst_v2`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.load_clickhouse_v2 import client

#: Given by the research lead from the Dune matview, quoted here only as the
#: denominator for coverage.  NOT read from Dune by this module.
N_TOKENS_REACHED_60 = 31_075
N_TOKENS_REACHED_115 = 9_930
SLOT_SECONDS = 0.4

#: A.1 .. A.6 and the inputs each one needs.
REQUIREMENTS = [
    ("A.1", "x >= 60 дээгүүр байх нийт хугацаа; t_below_60",
     ["t_60", "тасралтгүй x(t), хязгааргүй давхрага"]),
    ("A.2", "t_below_60 - t_60 тархалт",
     ["t_60", "тасралтгүй x(t), хязгааргүй давхрага"]),
    ("A.3", "min_x_after, min_x_after / 60",
     ["t_60", "тасралтгүй x(t), хязгааргүй давхрага"]),
    ("A.4", "t_max_x - t_60",
     ["t_60", "тасралтгүй x(t)", "max_x ба түүний мөч"]),
    ("A.5", "final_x, final_x / 60, final_x >= 60 хувь",
     ["t_60", "амьдралын төгсгөл дэх x"]),
    ("A.6", "70/80/100/115 руу t_60-ээс хойш хүрэх хувь ба хугацаа",
     ["t_60", "тасралтгүй x(t), хязгааргүй давхрага"]),
]


def main() -> None:
    c = client()
    q = lambda s: c.query(s).result_rows

    out: dict = {"stopped": True, "reason": "x(t) path not available locally"}

    print("=" * 66)
    print("A -- ЛОКАЛ БОЛОМЖИЙН ШАЛГАЛТ (Dune-д хандаагүй)")
    print("=" * 66)

    # ---- 1. which tables hold a path at all
    print("\n1. ЛОКАЛ ХҮСНЭГТҮҮД")
    tabs = {}
    for t in ("event", "token", "burst", "burst_v2"):
        n = q(f"SELECT count() FROM flow.{t}")[0][0]
        tabs[t] = n
        note = ""
        if t == "event":
            note = "  <- бүтэн x(t)-г агуулах ЦОРЫН ГАНЦ хүснэгт (vsol_post)"
        if t == "token":
            note = "  <- created_at/migrated-ийг агуулах хүснэгт"
        print(f"   flow.{t:<9} {n:>10,} мөр{note}")
    out["tables"] = tabs

    print(f"\n   flow.event      = {tabs['event']:,} мөр  -> бүтэн зам БАЙХГҮЙ")
    print(f"   flow.token      = {tabs['token']:,} мөр  -> t_60/max_x/final_x БАЙХГҮЙ")

    # ---- 2. what burst_v2 does cover
    print("\n2. `flow.burst_v2` ЮУ АГУУЛДАГ")
    n_b, n_tok = q("SELECT count(), uniqExact(token_mint) FROM flow.burst_v2 "
                   "WHERE NOT mayhem")[0]
    traj = q("SELECT DISTINCT traj_len FROM flow.burst_v2 WHERE NOT mayhem")
    horizon = traj[0][0] * SLOT_SECONDS
    print(f"   mayhem бус burst {n_b:,}, ялгаатай токен {n_tok:,}")
    print(f"   траекторийн урт {traj[0][0]} slot = {horizon:.1f} секунд "
          f"(burst-ийн trigger-ээс хойш)")
    print("   зам нь `x_end_slot + cumf[a]`-аар л сэргээгдэнэ, a = 1..75")
    print("   burst ХООРОНД зам огт БАЙХГҮЙ")
    out["burst_v2"] = {"n_bursts": n_b, "n_tokens": n_tok,
                       "traj_slots": traj[0][0], "horizon_seconds": horizon}

    # ---- 3. coverage of the x >= 60 region by bursts
    print("\n3. `x >= 60` МУЖИЙН BURST ХАМРАЛТ")
    cov = {}
    for th in (40, 50, 60, 80, 115):
        nb, nt = q("SELECT count(), uniqExact(token_mint) FROM flow.burst_v2 "
                   f"WHERE NOT mayhem AND depth_x >= {th}")[0]
        cov[th] = {"n_bursts": nb, "n_tokens": nt}
        print(f"   depth_x >= {th:>3}: burst {nb:>7,}  токен {nt:>6,}")
    hit60 = cov[60]["n_tokens"]
    share = 100.0 * hit60 / N_TOKENS_REACHED_60
    print(f"\n   60-д хүрсэн {N_TOKENS_REACHED_60:,} токений зөвхөн "
          f"{hit60:,} = {share:.2f}%-д нь `depth_x >= 60` burst байна")
    print(f"   (үлдсэн {N_TOKENS_REACHED_60 - hit60:,} токен 60-ыг burst-ийн "
          f"гадна давсан -> тэдний зам локал дээр огт байхгүй)")
    out["coverage"] = cov
    out["share_of_60_tokens_with_burst"] = share

    dmax = q("SELECT max(depth_x) FROM flow.burst_v2 WHERE NOT mayhem")[0][0]
    print(f"   `depth_x`-ийн локал дээд утга {dmax:.3f} "
          f"(migration босго 115 дээр таслагдсан)")
    out["depth_x_max"] = float(dmax)

    # ---- 4. even inside a burst, does the 30 s window answer A?
    print("\n4. BURST ДОТОРХ 30 СЕКУНД A-Д ХҮРЭЛЦЭХ ҮҮ")
    r = q("SELECT count(), countIf(x_at_plus5 < 60), countIf(x_at_plus12 < 60), "
          "       countIf(x_at_plus37 < 60) FROM flow.burst_v2 "
          "WHERE NOT mayhem AND depth_x >= 60")[0]
    print(f"   depth_x >= 60 burst {r[0]:,}")
    for lab, k, sl in (("+5 slot  (2.0 с)", r[1], 5), ("+12 slot (4.8 с)", r[2], 12),
                       ("+37 slot (14.8 с)", r[3], 37)):
        print(f"     {lab}: x < 60 болсон {k:>6,} = {100*k/r[0]:5.2f}%")
    print(f"   30 секундын эцэст ч {100*(r[0]-r[3])/r[0]:.2f}% нь 60-аас дээгүүр "
          f"хэвээр -> `t_below_60` нь цонхны ГАДНА, хэмжигдэхгүй")
    out["inside_burst"] = {"n": r[0], "below60_at_plus5": r[1],
                           "below60_at_plus12": r[2], "below60_at_plus37": r[3]}

    # ---- 5. the requirement table
    print("\n5. A.1-A.6 ШААРДЛАГА vs ЛОКАЛ БАЙДАЛ")
    for tag, what, needs in REQUIREMENTS:
        print(f"   {tag}  {what}")
        for n in needs:
            print(f"          хэрэгтэй: {n:<46} -> ДУТУУ")
    out["requirements"] = [{"id": t, "what": w, "needs": n} for t, w, n in REQUIREMENTS]

    print("\n" + "=" * 66)
    print("ДҮГНЭЛТ: A-Г ЛОКАЛ ДЭЭР ХЭМЖИХ БОЛОМЖГҮЙ. ЗОГСОВ.")
    print("Dune-аас шинэ дата ТАТААГҮЙ. Удирдагчийн шийдвэр хүлээж байна.")
    print("=" * 66)

    p = Path("results/path_after_60_feasibility.json")
    p.write_text(json.dumps(out, indent=2))
    print(f"\n-> {p}")


if __name__ == "__main__":
    main()
