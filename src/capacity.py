"""Operational capacity of the frozen rule — frequency, concurrency, capital, impact.

  python -m src.capacity

Source: `flow.burst_v2`, chunk 1, the 5,402 rows the frozen rule trades.  No new
rule is tested here; `src.causal_rule` is applied exactly as frozen.

Concurrency is computed in SLOT space, where the rule already lives: a position
opens at `burst_slot + L` and closes at `burst_slot + a_exit`.  Wall-clock is
needed only for the frequency section, and the slot duration used there is
measured from the data rather than assumed to be 400 ms.

SCOPE LIMIT, and it turned out to be narrower than expected.  Chunk 1 is a nine
day launch cohort observed over a 98-day event window, so the naive reading is
that a live operator seeing every live token would trade ~11x more.  That reading
is wrong: 98.06% of the rule's trades happen on the token's own launch day, and
98.98% fall on the cohort's ten launch dates.  For those dates the cohort is
COMPLETE -- every SOL-curve token launched then is in it -- so frequency and
concurrency on launch days are representative rather than a lower bound.  What is
missing is the cross-cohort tail: the ~1.94% of trades that happen after launch
day, which a live operator would also collect from earlier cohorts.  Spreading a
figure over the 98 calendar days instead of the 10 active launch dates divides it
by about ten and is reported both ways below.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.causal_rule import DEFAULTS, apply  # noqa: E402

Q = float(DEFAULTS["q"])
L = DEFAULTS["L"]
CAPS = (1, 2, 5, 10, None)
PRIOR = 19_627


def load():
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT nf3_traj_75_incl_pre, nf3_excl_pre_1, nf3_excl_pre_2, "
        "       x_end_slot, depth_x, token_mint, slot, "
        "       parseDateTimeBestEffort(block_time, 'UTC') AS bt, "
        "       parseDateTimeBestEffort(token_created_at, 'UTC') AS ct "
        "FROM flow.burst_v2 WHERE NOT mayhem"
    ).result_columns
    return cols


def seconds_per_slot(slots: np.ndarray, times: np.ndarray) -> float:
    """Measured, not assumed: least-squares slope of block_time on slot."""
    s = slots.astype(np.float64)
    t = times.astype(np.float64)
    return float(np.polyfit(s, t, 1)[0])


def concurrency(entry: np.ndarray, exit_: np.ndarray) -> np.ndarray:
    """Open positions at each entry instant, for uncapped trading."""
    order = np.argsort(entry, kind="stable")
    e, x = entry[order], exit_[order]
    out = np.empty(len(e), dtype=np.int64)
    for i in range(len(e)):
        out[i] = int(np.sum((e[:i + 1] <= e[i]) & (x[:i + 1] > e[i])))
    inv = np.empty(len(e), dtype=np.int64)
    inv[order] = out
    return inv


def cap_trades(entry, exit_, pnl, M):
    """First-come-first-served admission under a cap of `M` open positions."""
    if M is None:
        return np.ones(len(entry), dtype=bool)
    order = np.argsort(entry, kind="stable")
    taken = np.zeros(len(entry), dtype=bool)
    open_until: list[int] = []
    for i in order:
        open_until = [u for u in open_until if u > entry[i]]
        if len(open_until) < M:
            taken[i] = True
            open_until.append(exit_[i])
    return taken


def main() -> None:
    cols = load()
    traj, e1, e2, xend, depth, mint, slot, bt, ct = cols
    n_all = len(traj)

    rows = []
    for i in range(n_all):
        o = apply(list(traj[i]), e1[i], e2[i], xend[i], depth[i])
        if o.traded:
            rows.append((i, o.exit_age_rule, float(o.pnl)))
    idx = np.array([r[0] for r in rows])
    a_exit = np.array([r[1] for r in rows])
    pnl = np.array([r[2] for r in rows])
    print(f"арилжсан {len(idx):,} / {n_all:,}")

    slot_a = np.asarray(slot, dtype=np.int64)
    ts = np.array([t.timestamp() for t in bt], dtype=np.float64)
    sps = seconds_per_slot(slot_a, ts)
    print(f"хэмжсэн slot-ийн үргэлжлэл: {sps:.6f} с/slot")

    entry_slot = slot_a[idx] + L
    exit_slot = slot_a[idx] + a_exit
    entry_ts = ts[idx] + L * sps

    # ------------------------------------------------------------------ 1
    import datetime as dt
    U = dt.timezone.utc
    days = [dt.datetime.fromtimestamp(t, U).strftime("%Y-%m-%d") for t in entry_ts]
    hours = [dt.datetime.fromtimestamp(t, U).strftime("%Y-%m-%d %H") for t in entry_ts]
    mins = [dt.datetime.fromtimestamp(t, U).strftime("%Y-%m-%d %H:%M") for t in entry_ts]
    dc, hc, mc = Counter(days), Counter(hours), Counter(mins)
    span_days = (max(days), min(days))
    d0 = dt.date.fromisoformat(min(days))
    d1 = dt.date.fromisoformat(max(days))
    all_days = [(d0 + dt.timedelta(days=k)).isoformat()
                for k in range((d1 - d0).days + 1)]
    per_day = np.array([dc.get(d, 0) for d in all_days])
    freq = {
        "span": [min(days), max(days)], "n_calendar_days": len(all_days),
        "days_with_trades": int((per_day > 0).sum()),
        "days_without_trades": int((per_day == 0).sum()),
        "per_day": {"median": float(np.median(per_day)),
                    "p10": float(np.percentile(per_day, 10)),
                    "p90": float(np.percentile(per_day, 90)),
                    "min": int(per_day.min()), "max": int(per_day.max())},
        "per_hour": {"median": float(np.median(list(hc.values()))),
                     "p90": float(np.percentile(list(hc.values()), 90)),
                     "max": int(max(hc.values())),
                     "n_hours_with_trades": len(hc)},
        "per_minute": {"median": float(np.median(list(mc.values()))),
                       "p90": float(np.percentile(list(mc.values()), 90)),
                       "max": int(max(mc.values())),
                       "n_minutes_with_trades": len(mc)},
    }
    print(f"\n1. өдөр: {freq['n_calendar_days']} хуанлийн өдөр, "
          f"арилжаатай {freq['days_with_trades']}, арилжаагүй "
          f"{freq['days_without_trades']}")
    print(f"   өдөр тутам median {freq['per_day']['median']:.1f}  "
          f"p10 {freq['per_day']['p10']:.1f}  p90 {freq['per_day']['p90']:.1f}  "
          f"min {freq['per_day']['min']}  max {freq['per_day']['max']}")
    print(f"   цаг тутам median {freq['per_hour']['median']:.1f}  "
          f"p90 {freq['per_hour']['p90']:.1f}  max {freq['per_hour']['max']}")
    print(f"   минут тутам median {freq['per_minute']['median']:.1f}  "
          f"p90 {freq['per_minute']['p90']:.1f}  max {freq['per_minute']['max']}")

    # trade age since launch, which bounds how much a live cohort would add
    ct_ts = np.array([t.timestamp() for t in ct], dtype=np.float64)
    age_days = (entry_ts - ct_ts[idx]) / 86400.0
    freq["trade_age_days"] = {q: float(np.percentile(age_days, p)) for q, p in
                              (("p50", 50), ("p90", 90), ("p99", 99), ("max", 100))}
    print(f"   launch-аас хойших нас (өдөр): median "
          f"{freq['trade_age_days']['p50']:.2f}  p90 {freq['trade_age_days']['p90']:.2f}  "
          f"p99 {freq['trade_age_days']['p99']:.2f}  max {freq['trade_age_days']['max']:.2f}")

    # ------------------------------------------------------------------ 2
    conc = concurrency(entry_slot, exit_slot)
    print(f"\n2. зэрэг нээлттэй позиц: median {np.median(conc):.1f}  "
          f"p90 {np.percentile(conc, 90):.1f}  p99 {np.percentile(conc, 99):.1f}  "
          f"max {conc.max()}")
    caps = []
    for M in CAPS:
        taken = cap_trades(entry_slot, exit_slot, pnl, M)
        v = pnl[taken]
        caps.append({"M": M, "n": int(taken.sum()),
                     "share_kept": float(taken.mean()),
                     "total_pnl": float(v.sum()),
                     "expectancy": float(v.mean()) if len(v) else float("nan"),
                     "median": float(np.median(v)) if len(v) else float("nan"),
                     "share_positive": float((v > 0).mean()) if len(v) else float("nan")})
        c = caps[-1]
        print(f"   M={str(M):>4}: n {c['n']:>5,} ({100*c['share_kept']:5.2f}%)  "
              f"нийт P&L {c['total_pnl']:+10.2f}  expectancy {c['expectancy']:+.6f}  "
              f">0 {100*c['share_positive']:.2f}%")

    # ------------------------------------------------------------------ 3
    n_days = freq["n_calendar_days"]
    capital = []
    for c in caps:
        M = c["M"]
        peak = (M if M is not None else int(conc.max())) * Q
        cap_row = {"M": M, "peak_capital_sol": peak,
                   "trades_per_day": c["n"] / n_days,
                   "turnover_per_day_sol": c["n"] / n_days * Q,
                   "pnl_per_day_sol": c["total_pnl"] / n_days,
                   "return_on_peak_capital_per_day":
                       (c["total_pnl"] / n_days) / peak if peak else float("nan")}
        capital.append(cap_row)
        print(f"   M={str(M):>4}: дээд хөрөнгө {peak:>7.1f} SOL  "
              f"өдрийн арилжаа {cap_row['trades_per_day']:6.2f}  "
              f"эргэлт {cap_row['turnover_per_day_sol']:8.2f}  "
              f"P&L {cap_row['pnl_per_day_sol']:+8.3f}  "
              f"өгөөж {100*cap_row['return_on_peak_capital_per_day']:+7.3f}%/өдөр")

    # ------------------------------------------------------------------ 4
    mints = np.asarray(mint)[idx]
    per_tok = Counter(mints)
    counts = np.array(list(per_tok.values()))
    repeat_rows = int(sum(v for v in counts if v > 1))
    same_open = 0
    by_tok: dict = {}
    for i in range(len(idx)):
        by_tok.setdefault(mints[i], []).append(i)
    overlapping_tokens = 0
    for t, ii in by_tok.items():
        if len(ii) < 2:
            continue
        e = sorted((entry_slot[j], exit_slot[j]) for j in ii)
        hit = False
        for a in range(len(e) - 1):
            if e[a + 1][0] < e[a][1]:
                same_open += 1
                hit = True
        overlapping_tokens += hit
    impact = {"n_tokens": len(per_tok),
              "trades_per_token": {"median": float(np.median(counts)),
                                   "p90": float(np.percentile(counts, 90)),
                                   "max": int(counts.max())},
              "tokens_with_repeat": int((counts > 1).sum()),
              "share_tokens_with_repeat": float((counts > 1).mean()),
              "rows_on_repeat_tokens": repeat_rows,
              "share_rows_on_repeat_tokens": repeat_rows / len(idx),
              "overlapping_pairs_same_token": same_open,
              "tokens_with_overlap": overlapping_tokens}
    print(f"\n4. токен {impact['n_tokens']:,}  арилжаа/токен median "
          f"{impact['trades_per_token']['median']:.1f}  p90 "
          f"{impact['trades_per_token']['p90']:.1f}  max {impact['trades_per_token']['max']}")
    print(f"   давтан арилжаатай токен {impact['tokens_with_repeat']:,} "
          f"({100*impact['share_tokens_with_repeat']:.2f}%), тэдгээр дээрх мөр "
          f"{repeat_rows:,} ({100*impact['share_rows_on_repeat_tokens']:.2f}%)")
    print(f"   ижил токен дээр ЗЭРЭГ нээлттэй хос: {same_open:,}  "
          f"(токен {overlapping_tokens:,})")

    out = {"n_traded": len(idx), "n_seen": n_all, "seconds_per_slot": sps,
           "q": Q, "L": L, "frequency": freq,
           "concurrency": {"median": float(np.median(conc)),
                           "p90": float(np.percentile(conc, 90)),
                           "p99": float(np.percentile(conc, 99)),
                           "max": int(conc.max())},
           "caps": caps, "capital": capital, "impact": impact,
           "scope": {"cohort_launch_days": 9, "event_window_days": 98,
                     "naive_scale": 98 / 9},
           "counts": {"this_step": 0, "prior": PRIOR, "cumulative": PRIOR}}
    p = config.RESULTS / "capacity.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"\n-> {p}")


if __name__ == "__main__":
    main()
