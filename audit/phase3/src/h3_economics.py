"""H3 economics on the corrected price arithmetic.

  python -m src.h3_economics parity     # local parity vs cost_model, 0 credit
  python -m src.h3_economics report     # print §1 and §2 from the stored rows

WHY A PARITY CHECK.  `sql/h3_economics.sql` evaluates the SAME closed form as
`src.cost_model.net_pnl` (V = 0, pf = 0), with one algebraic rewrite:

    dy = k/x1 - k/(x1+q)        ->      dy = k*q / (x1*(x1+q))

Identical by algebra, but the left form cancels two ~1e9 quantities, which is
exactly why `cost_model` runs at Decimal(60).  The right form has no
cancellation, so double precision is enough -- but "is enough" is a claim, and
this module measures it instead of asserting it, over the (x_a, r, q) ranges the
data actually contains.  If the measured relative difference were not tiny, the
SQL numbers would have to be thrown out.

NOT AN APPROXIMATION: no series expansion, no small-q limit, no linearisation.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import cost_model  # noqa: E402
from src.holder_anchor import load  # noqa: E402

K = 32_190_000_000.0
F = 0.0125
QS = (0.5, 1.0, 2.0)


def sql_ret(x_a: float, r: float, q: float) -> float:
    """The expression as written in sql/h3_economics.sql, in float64."""
    dy = K * q / (x_a * (x_a + q))
    x2 = r * x_a + q
    out = dy * x2 * x2 / (K + dy * x2)
    return (out * (1 - F) - q / (1 - F)) / q


def parity() -> None:
    """Compare against cost_model.net_pnl at Decimal(60)."""
    worst = 0.0
    worst_at = None
    n = 0
    xs = [25.0, 27.81, 30.0, 34.09, 41.49, 50.0, 60.0, 80.0, 120.0]
    rs = [0.05, 0.1, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0, 1.2, 1.36, 2.0, 5.0, 20.0]
    for x in xs:
        for r in rs:
            for q in QS:
                a = sql_ret(x, r, q)
                b = float(cost_model.net_pnl(Decimal(str(x)), Decimal(str(q)),
                                             V=0, W=Decimal(str((r - 1) * x)))
                           / Decimal(str(q)))
                d = abs(a - b) / max(abs(b), 1e-12)
                n += 1
                if d > worst:
                    worst, worst_at = d, (x, r, q, a, b)
    print(f"parity: {n} цэг (x_a × r × q), cost_model.net_pnl @ Decimal(60)-тэй харьцуулав")
    print(f"  ХАМГИЙН ИХ харьцангуй зөрүү: {worst:.3e}")
    x, r, q, a, b = worst_at
    print(f"  тэр цэгт: x_a={x} r={r} q={q}  SQL {a:.15f}  cost_model {b:.15f}")

    # the zero-fee round trip must be exactly flat (cost_model's own invariant)
    z = [abs(((K * q / (x * (x + q))) * (x + q) ** 2
              / (K + (K * q / (x * (x + q))) * (x + q)) - q) / q)
         for x in xs for q in QS]
    print(f"  шимтгэлгүй тэг-хөдөлгөөнт эргэлт (r=1, f=0) хазайлт: max {max(z):.3e}")
    Path("results/h3_parity.json").write_text(json.dumps(
        {"n_points": n, "max_rel_diff": worst,
         "worst_at": {"x_a": x, "r": r, "q": q, "sql": a, "cost_model": b},
         "zero_fee_flat_max_dev": max(z)}, indent=2))


def _cell(rows, g3=None, c3=None, tb=None):
    for x in rows:
        if x["g3"] == g3 and x["c3"] == c3 and x["tb"] == tb:
            return x
    return None


def report() -> None:
    rows = load()["h3_econ"]["rows"]
    pct = lambda x, f: 100 * float(x[f]) / float(x["n"])
    labs = {"1_lt1s": "< 1 с", "2_1to3s": "1–3 с",
            "3_3to10s": "3–10 с", "4_gt10s": "> 10 с"}

    for tag, gl, sl in (("20", "+20% → үнэ +44%", "−20% → үнэ −36%"),
                        ("36", "+36% → үнэ +85%", "−30% → үнэ −51%")):
        print(f"\n=== §1  {gl} / {sl} ===")
        print(f"{'бүлэг':<10}{'n':>9}{'түүхий':>10}{'шимтгэл':>10}"
              f"{'q=0.5':>10}{'q=1':>10}{'q=2':>10}"
              f"{'>0 q=0.5':>10}{'>0 q=1':>9}{'>0 q=2':>9}")
        cells = [("бүгд", _cell(rows))]
        cells += [(f"gini t{i}", _cell(rows, g3=i)) for i in (1, 2, 3)]
        cells += [(f"cre  t{i}", _cell(rows, c3=i)) for i in (1, 2, 3)]
        for nm, x in cells:
            if x is None:
                continue
            print(f"{nm:<10}{int(x['n']):>9,}"
                  f"{100*float(x[f'raw{tag}']):>9.2f}%{100*float(x[f'fee{tag}']):>9.2f}%"
                  + "".join(f"{100*float(x[f's{tag}_{q}']):>9.2f}%"
                            for q in ("05", "10", "20"))
                  + "".join(f"{100*float(x[f'p{tag}_{q}']):>9.2f}%"
                            for q in ("05", "10", "20")))

    print("\n=== §2  t_N бүлэг × терцил, q = 1, +20/−20 ===")
    print(f"{'бүлэг':<12}{'терцил':<8}{'n':>8}{'win%':>8}{'loss%':>8}{'same%':>7}"
          f"{'cens%':>8}{'win/loss':>10}{'E[ret] q=1':>12}{'>0':>8}{'x_a p50':>9}")
    for tb in ("1_lt1s", "2_1to3s", "3_3to10s", "4_gt10s"):
        for lab, key in (("gini", "g3"), ("creator", "c3")):
            for i in (1, 2, 3):
                x = _cell(rows, tb=tb, **{key: i})
                if x is None:
                    continue
                w, l = pct(x, "w20"), pct(x, "l20")
                print(f"{labs[tb]:<12}{lab[0]+str(i):<8}{int(x['n']):>8,}"
                      f"{w:>8.2f}{l:>8.2f}{pct(x,'s20'):>7.2f}{pct(x,'x20'):>8.2f}"
                      f"{w/l if l else float('nan'):>10.2f}"
                      f"{100*float(x['s20_10']):>11.2f}%{100*float(x['p20_10']):>7.2f}%"
                      f"{float(x['x_a_p50']):>9.2f}")
        x = _cell(rows, tb=tb)
        w, l = pct(x, "w20"), pct(x, "l20")
        print(f"{labs[tb]:<12}{'бүгд':<8}{int(x['n']):>8,}{w:>8.2f}{l:>8.2f}"
              f"{pct(x,'s20'):>7.2f}{pct(x,'x20'):>8.2f}{w/l if l else float('nan'):>10.2f}"
              f"{100*float(x['s20_10']):>11.2f}%{100*float(x['p20_10']):>7.2f}%"
              f"{float(x['x_a_p50']):>9.2f}")


if __name__ == "__main__":
    {"parity": parity, "report": report}[sys.argv[1]]()
