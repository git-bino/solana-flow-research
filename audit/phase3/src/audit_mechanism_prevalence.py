"""Prevalence of the three mechanisms the external audit raised (decisions.md, 2026-08-19).

  python -m src.audit_mechanism_prevalence

MEASUREMENT ONLY.  Nothing here is fixed, no Dune query is issued, and no
Phase 3b work is done.  The mechanisms are established; what is unknown is how
often they bite, and that is what this measures.

Source: `data/cache/parity_raw_events_200tokens.json` — 15,017 raw events for the
200 hash-ordered tokens the SQL↔Python parity check ran on.  That is the only
raw event data held locally; everything else was aggregated inside Dune.

Sample caveat, stated once and not repeated: these 200 tokens were selected by
hash prefix for parity, not drawn to represent the universe.  This module
reports counts on that sample and makes no claim about how they extrapolate.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.oh_reference import (  # noqa: E402
    LAMPORTS, THOUSAND, TOKEN_UNITS, Event, _burst_keys, load_events,
)

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
RAW = CACHE / "parity_raw_events_200tokens.json"
FWD_TAU = 12


def q(values, *ps):
    """Percentiles of `values`, or None for an empty input."""
    if len(values) == 0:
        return [None] * len(ps)
    a = np.asarray(values, dtype=np.float64)
    return [float(np.percentile(a, p)) for p in ps]


def by_token(events: list[Event]) -> dict[str, list[Event]]:
    out: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        out[e.mint].append(e)
    for token in out.values():
        token.sort(key=lambda e: e.key)
    return dict(out)


# --- 1. multiple events in one transaction ----------------------------------

def measure_1(events: list[Event], tokens: dict[str, list[Event]], bursts: dict) -> dict:
    """Transactions are keyed (slot, tx_index) — a transaction can touch several tokens.

    Only legs on the 200 sampled tokens are visible, so a transaction that also
    traded an unsampled token is counted short.  Both groupings are reported: the
    transaction as a whole, and the part of it on one token, which is the part
    `fwd_net_flow` can see.
    """
    tx: dict[tuple[int, int], list[Event]] = defaultdict(list)
    for e in events:
        tx[(e.slot, e.tx_index)].append(e)

    sizes = np.array([len(v) for v in tx.values()])
    buckets = {"1": sizes == 1, "2": sizes == 2,
               "3-5": (sizes >= 3) & (sizes <= 5), "6+": sizes >= 6}
    dist = {k: {"transactions": int(m.sum()),
                "share_of_transactions": float(m.mean()),
                "events": int(sizes[m].sum()),
                "share_of_events": float(sizes[m].sum() / sizes.sum())}
            for k, m in buckets.items()}

    multi_mint = sum(1 for v in tx.values() if len({e.mint for e in v}) > 1)

    # (b) bursts followed by another leg inside their own transaction
    later_any, later_same_token = 0, 0
    ratios, signs, all_from_same_tx = [], [], 0
    for (mint, slot, txi, ixi) in bursts:
        token = tokens[mint]
        i = next(j for j, e in enumerate(token) if e.key == (slot, txi, ixi))
        group = tx[(slot, txi)]
        # ix_index is the intra-transaction position, so it orders legs across
        # tokens as well as within one.
        after_any = [e for e in group if e.ix_index > ixi]
        after_same = [e for e in token[i + 1:]
                      if e.slot == slot and e.tx_index == txi]
        later_any += bool(after_any)
        if not after_same:
            continue
        later_same_token += 1

        s = token[i].slot
        fwd = sum(e.signed_lam for e in token[i + 1:] if e.slot <= s + FWD_TAU)
        same_tx_part = sum(e.signed_lam for e in after_same)
        signs.append(same_tx_part > 0)
        if fwd != 0:
            ratios.append(same_tx_part / fwd)
            if same_tx_part == fwd:
                all_from_same_tx += 1

    r_med, r_p90, r_max = q(ratios, 50, 90, 100)
    return {
        "transactions": len(tx), "events": int(sizes.sum()),
        "size_distribution": dist,
        "transactions_spanning_multiple_tokens": multi_mint,
        "bursts": len(bursts),
        "bursts_with_a_later_leg_same_tx_any_token": later_any,
        "bursts_with_a_later_leg_same_tx_same_token": later_same_token,
        "ratio_n": len(ratios), "ratio_median": r_med, "ratio_p90": r_p90,
        "ratio_max": r_max, "bursts_ratio_exactly_1": all_from_same_tx,
        "same_tx_leg_flow_positive_share": (float(np.mean(signs)) if signs else None),
        "same_tx_leg_n_signed": len(signs),
    }


# --- shared ledger ----------------------------------------------------------

@dataclass
class Dual:
    """Two cost-basis conventions on one inventory.

    `all_*` is the spec's §1.2 basis: every historical buy, never reset.
    `seg_*` is the alternative the audit raises: only buys since the wallet was
    last flat.  Reset fires when the balance reaches or crosses zero — crossing
    is included because the ledger can go negative (measurement 2), and leaving a
    negative balance carrying an old basis would mix two unrelated positions.
    THIS IS CLAUDE CODE'S DECISION; the spec does not define the alternative.
    """
    all_lam: int = 0
    all_units: int = 0
    seg_lam: int = 0
    seg_units: int = 0
    held: int = 0
    went_negative: bool = False
    min_held: int = 0
    reached_zero: bool = False
    rebought_after_zero: bool = False

    def apply(self, ev: Event) -> None:
        if ev.is_buy:
            if self.reached_zero:
                self.rebought_after_zero = True
            self.all_lam += ev.lam
            self.all_units += ev.units
            self.seg_lam += ev.lam
            self.seg_units += ev.units
            self.held += ev.units
        else:
            self.held -= ev.units
            if self.held < 0:
                self.went_negative = True
                self.min_held = min(self.min_held, self.held)
            if self.held <= 0:
                self.reached_zero = True
                self.seg_lam = 0
                self.seg_units = 0

    def cb_all(self) -> Decimal | None:
        if self.all_units == 0:
            return None
        return Decimal(self.all_lam) / (Decimal(self.all_units) * THOUSAND)

    def cb_seg(self) -> Decimal | None:
        if self.seg_units == 0:
            return None
        return Decimal(self.seg_lam) / (Decimal(self.seg_units) * THOUSAND)


def spot_price(vsol: int, x0: int, y0: int) -> Decimal:
    return (Decimal(vsol) * Decimal(vsol)) / (Decimal(x0) * Decimal(y0) * THOUSAND)


def oh_at(states: dict[str, Dual], price: Decimal, seg: bool) -> Decimal:
    total = Decimal(0)
    for st in states.values():
        if st.held <= 0:
            continue
        cb = st.cb_seg() if seg else st.cb_all()
        if cb is None or cb >= price:
            continue
        total += (Decimal(st.held) / TOKEN_UNITS) * (price - cb)
    return total


# --- 2, 3: one replay serves both -------------------------------------------

def measure_2_and_3(tokens: dict[str, list[Event]], bursts: dict) -> tuple[dict, dict]:
    burst_by_token: dict[str, set] = defaultdict(set)
    for (mint, slot, txi, ixi) in bursts:
        burst_by_token[mint].add((slot, txi, ixi))

    pairs_total = neg_pairs = zero_rebuy_pairs = 0
    tokens_with_neg: set[str] = set()
    shortfalls: list[float] = []
    neg_in_oh_filter = 0           # negative wallets meeting a burst
    neg_held_positive = neg_held_nonpositive = neg_contributing = 0
    rebuy_eligible = 0             # zero-then-rebuy wallets holding >0 at a burst
    rebuy_contributing = 0         # ...and with cost basis below the spot price
    cb_rel_diffs: list[float] = []
    oh_rel_diffs: list[float] = []
    oh_double, oh_half, oh_compared = 0, 0, 0

    for mint, evs in tokens.items():
        states: dict[str, Dual] = defaultdict(Dual)
        want = burst_by_token.get(mint, set())
        for ev in evs:
            states[ev.wallet].apply(ev)
            if ev.key not in want:
                continue
            price = spot_price(ev.vsol, ev.x0_lam, ev.y0_units)
            oh_all = oh_at(states, price, seg=False)
            oh_seg = oh_at(states, price, seg=True)
            oh_compared += 1
            if oh_all > 0:
                rel = float((oh_seg - oh_all) / oh_all)
                oh_rel_diffs.append(rel)
                if oh_seg >= 2 * oh_all:
                    oh_double += 1
                if 2 * oh_seg <= oh_all:
                    oh_half += 1
            for st in states.values():
                if st.went_negative:
                    neg_in_oh_filter += 1
                    # 2(d): does the `held_units > 0` filter actually drop them?
                    if st.held > 0:
                        neg_held_positive += 1
                        if (cb := st.cb_all()) is not None and cb < price:
                            neg_contributing += 1
                    else:
                        neg_held_nonpositive += 1
                if not (st.reached_zero and st.rebought_after_zero):
                    continue
                if st.held <= 0:
                    continue
                rebuy_eligible += 1
                a, sg = st.cb_all(), st.cb_seg()
                if a is not None and a < price:
                    rebuy_contributing += 1
                if a is not None and sg is not None and a > 0:
                    cb_rel_diffs.append(float((sg - a) / a))

        pairs_total += len(states)
        for st in states.values():
            if st.went_negative:
                neg_pairs += 1
                tokens_with_neg.add(mint)
                shortfalls.append(-st.min_held / 1e6)
            if st.reached_zero and st.rebought_after_zero:
                zero_rebuy_pairs += 1

    s_med, s_max = q(shortfalls, 50, 100)
    c_med, c_p90, c_max = q(np.abs(cb_rel_diffs), 50, 90, 100)
    o_med, o_p90, o_max = q(np.abs(oh_rel_diffs), 50, 90, 100)
    m2 = {
        "wallet_token_pairs": pairs_total,
        "pairs_going_negative": neg_pairs,
        "pairs_going_negative_share": neg_pairs / pairs_total,
        "tokens_with_a_negative_pair": len(tokens_with_neg),
        "tokens_total": len(tokens),
        "shortfall_tokens_median": s_med, "shortfall_tokens_max": s_max,
        "negative_wallet_burst_encounters": neg_in_oh_filter,
        "of_those_held_positive_so_kept_in_oh": neg_held_positive,
        "of_those_contributing_to_oh": neg_contributing,
        "of_those_held_nonpositive_so_dropped": neg_held_nonpositive,
    }
    m3 = {
        "wallet_token_pairs": pairs_total,
        "pairs_zero_then_rebuy": zero_rebuy_pairs,
        "pairs_zero_then_rebuy_share": zero_rebuy_pairs / pairs_total,
        "burst_encounters_eligible": rebuy_eligible,
        "burst_encounters_contributing_to_oh": rebuy_contributing,
        "cb_rel_diff_n": len(cb_rel_diffs),
        "cb_rel_diff_median": c_med, "cb_rel_diff_p90": c_p90, "cb_rel_diff_max": c_max,
        "oh_compared": oh_compared, "oh_rel_diff_n": len(oh_rel_diffs),
        "oh_rel_diff_median": o_med, "oh_rel_diff_p90": o_p90, "oh_rel_diff_max": o_max,
        "oh_at_least_doubled": oh_double, "oh_at_most_halved": oh_half,
    }
    return m2, m3


# --- 4. ix_index packing ----------------------------------------------------

def measure_4(events: list[Event], raw: list[dict]) -> dict:
    """The cache stores the PACKED index only, so outer/inner cannot be separated.

    What is still measurable locally is the consequence that matters: whether the
    packed key collides, i.e. whether two events of one token share
    (slot, tx_index, ix_index).
    """
    have_raw = any(k in raw[0] for k in ("outer", "inner", "evt_outer_instruction_index",
                                         "evt_inner_instruction_index"))
    ixi = np.array([e.ix_index for e in events])
    seen: set[tuple] = set()
    collisions = 0
    for e in events:
        k = (e.mint, e.slot, e.tx_index, e.ix_index)
        if k in seen:
            collisions += 1
        seen.add(k)
    p50, p90, p99 = q(ixi, 50, 90, 99)
    return {
        "raw_outer_inner_in_cache": have_raw,
        "raw_fields": sorted(raw[0].keys()),
        "ix_index_max": int(ixi.max()), "ix_index_min": int(ixi.min()),
        "ix_index_p50": p50, "ix_index_p90": p90, "ix_index_p99": p99,
        "ix_index_multiple_of_64_share": float((ixi % 64 == 0).mean()),
        "implied_inner_max_if_packing_holds": int((ixi % 64).max()),
        "implied_outer_max_if_packing_holds": int((ixi // 64).max()),
        "packed_key_collisions": collisions,
        "events": len(events),
    }


def main() -> None:
    events = load_events(RAW)
    raw = json.loads(RAW.read_text())
    tokens = by_token(events)
    bursts = {}
    for mint, evs in tokens.items():
        for i in _burst_keys(evs):
            e = evs[i]
            bursts[(mint, e.slot, e.tx_index, e.ix_index)] = i

    print(f"events {len(events):,} · tokens {len(tokens)} · bursts {len(bursts)}\n")
    m1 = measure_1(events, tokens, bursts)
    m2, m3 = measure_2_and_3(tokens, bursts)
    m4 = measure_4(events, raw)
    for name, block in [("1 same-transaction legs", m1), ("2 negative inventory", m2),
                        ("3 full exit then rebuy", m3), ("4 ix_index packing", m4)]:
        print(f"=== {name} ===")
        print(json.dumps(block, indent=2, default=str))
        print()


if __name__ == "__main__":
    main()
