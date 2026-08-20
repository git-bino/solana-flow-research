"""Asymmetric barriers on the H3 anchor -- parity check and report.

  python -m src.asymmetric_barriers parity    # vs cost_model, local, 0 credit
  python -m src.asymmetric_barriers report    # §1-§4 tables from stored rows

`sql/asym_passage.sql` evaluates `cost_model.net_pnl` (V = 0, pf = 0) with
`dy = k*q/(x1*(x1+q))` in place of `k/x1 - k/(x1+q)`.  The two are the same
expression; the second cancels two ~1e9 quantities, which is why `cost_model`
runs at Decimal(60) and this does not.  That claim is MEASURED here, over the
(x_a, r, q) ranges the asymmetric barriers actually reach -- r now runs to 2.35
on the upside and 0.50 on the downside, wider than the earlier +20/-20 grid.
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
QS = (0.5, 1.0)


def sql_ret(x_a: float, r: float, q: float) -> float:
    dy = K * q / (x_a * (x_a + q))
    x2 = r * x_a + q
    out = dy * x2 * x2 / (K + dy * x2)
    return (out * (1 - F) - q / (1 - F)) / q


def parity() -> None:
    xs = [25.0, 27.81, 30.0, 34.09, 41.49, 50.0, 60.0, 80.0, 120.0]
    rs = [0.02, 0.10, 0.50, 0.70, 0.80, 1.00, 1.50, 1.76, 2.05, 2.35,
          3.34, 6.36, 20.0, 152.5]
    worst, at, n = 0.0, None, 0
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
                    worst, at = d, (x, r, q, a, b)
    print(f"parity: {n} цэг (x_a × r × q), r нь 0.02…152.5 хүртэл")
    print(f"  ХАМГИЙН ИХ харьцангуй зөрүү: {worst:.3e}")
    print(f"  тэр цэгт: x_a={at[0]} r={at[1]} q={at[2]}  "
          f"SQL {at[3]:.15f}  cost_model {at[4]:.15f}")
    Path("results/asym_parity.json").write_text(json.dumps(
        {"n_points": n, "max_rel_diff": worst,
         "worst_at": {"x_a": at[0], "r": at[1], "q": at[2],
                      "sql": at[3], "cost_model": at[4]}}, indent=2))


LABS = {"1_lt1s": "< 1 с", "2_1to3s": "1–3 с",
        "3_3to10s": "3–10 с", "4_gt10s": "> 10 с"}
ORDER = [f"{t} / {s}" for t in ("+50%", "+76%", "+105%", "+135%", "зорилтгүй")
         for s in ("−20%", "−30%", "−50%")]


def _c(rows, lab, g3=None, c3=None, tb=None):
    for x in rows:
        if x["lab"] == lab and x["g3"] == g3 and x["c3"] == c3 and x["tb"] == tb:
            return x
    return None


def report() -> None:
    rows = load()["asym_passage"]["rows"]
    p = lambda x, f: 100 * float(x[f]) / float(x["n"])
    g = lambda x, f, d=2: "—" if x[f] is None else f"{float(x[f]):.{d}f}"

    print("=== §2  Асимметр first passage, H3 (n = 153,027) ===")
    print(f"{'хос':<20}{'win%':>7}{'loss%':>7}{'same%':>7}{'cens%':>7}"
          f"{'t_win p50':>10}{'p90':>9}{'t_loss p50':>11}{'p90':>9}"
          f"{'E[thr] q1':>11}{'E[ovr] q1':>11}{'>0':>7}")
    for lab in ORDER:
        x = _c(rows, lab)
        if x is None:
            continue
        print(f"{lab:<20}{p(x,'w'):>7.2f}{p(x,'l'):>7.2f}{p(x,'s'):>7.2f}{p(x,'c'):>7.2f}"
              f"{g(x,'tw50',1):>10}{g(x,'tw90',1):>9}{g(x,'tl50',1):>11}{g(x,'tl90',1):>9}"
              f"{100*float(x['th10']):>10.2f}%{100*float(x['ov10']):>10.2f}%"
              f"{100*float(x['pos10']):>6.2f}%")

    print("\n=== §4  Overshoot: бодит гарах / босго (median) ===")
    print(f"{'хос':<20}{'win талд':>10}{'loss талд':>11}"
          f"{'E[thr] q1':>11}{'E[ovr] q1':>11}{'зөрүү':>9}")
    for lab in ORDER:
        x = _c(rows, lab)
        if x is None:
            continue
        d = 100 * (float(x["ov10"]) - float(x["th10"]))
        print(f"{lab:<20}{g(x,'ovr_win_p50',4):>10}{g(x,'ovr_loss_p50',4):>11}"
              f"{100*float(x['th10']):>10.2f}%{100*float(x['ov10']):>10.2f}%{d:>+8.2f}")

    print("\n=== §3  Гүйцэтгэх боломжтой нүднүүд (E[ovr], q = 1) ===")
    print(f"{'хос':<20}{'терцил':<6}" + "".join(f"{LABS[t]:>22}" for t in
          ("3_3to10s", "4_gt10s")))
    for lab in ORDER:
        for key, tag in (("g3", "g1"), ("c3", "c1")):
            cells = []
            for tb in ("3_3to10s", "4_gt10s"):
                x = _c(rows, lab, tb=tb, **{key: 1})
                cells.append("—" if x is None else
                             f"n={int(x['n']):,} w={p(x,'w'):.1f} "
                             f"{100*float(x['ov10']):+.2f}%")
            print(f"{lab:<20}{tag:<6}" + "".join(f"{c:>22}" for c in cells))


if __name__ == "__main__":
    {"parity": parity, "report": report}[sys.argv[1]]()
