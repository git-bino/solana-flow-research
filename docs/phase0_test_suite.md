# Phase 0 — §8.2-ийн 8-р шаардлагын test suite

**Огноо:** 2026-08-18 · `pytest -q` · **Dune хандалт шаардахгүй** · Dune query ажиллуулаагүй, extract ажиллуулаагүй, шийдвэр гаргаагүй

**Үр дүн: 94 тест — 91 PASS, 3 FAIL.** Гурван FAIL нь **олдвор**, тестийн алдаа биш; засаагүй, доор тайлагнав.

## Бүтэц

§8.2-ийн 8-р шаардлага нь §2.4-ийн burst-only архитектурын дараа хоёр хэлбэртэй болсон:

| Хэлбэр | Юуг батлана | Файл |
|---|---|---|
| Синтетик unit test | Python лавлагаа **ЗӨВ** гэдгийг | `test_leakage.py`, `test_cost_basis.py`, `test_slot_ordering.py`, `test_burst.py` |
| SQL ↔ Python parity | SQL нь Python-той **ИЖИЛ** гэдгийг | `test_parity.py` |

Хоёулаа хэрэгтэй: parity дангаараа хоёр тал ижил алдаа хийж байвал өнгөрөөнө; синтетик тест дангаараа SQL-ийн тухай юу ч хэлэхгүй. **Энэ хосын үлдэгдэл эрсдэл нь хоёр талын хуваалцсан тодорхойлолтын алдаа** — доорх 3 FAIL яг тэр төрлийн зүйлийг илрүүлсэн (parity нь хуваалцаагүй байсан тул илэрсэн).

## Дэд бүтэц

| Файл | Юу |
|---|---|
| `tests/synthetic.py` | Параметржүүлсэн event үүсгэгч: токен тоо, event тоо, slot нягт, **хоосон slot-ын хувь**, mayhem, sell/round-ийн хувь, wallet тоо, seed. Curve state нь `src.curve`-ийн бүхэл тоон функцээр үүсдэг тул `vsol` нь бодит арилжааны гаргах утга. Мөн гурван **perturbation**: `scale_sol_x100`, `flip_side`, `insert_events` — зөвхөн t-ээс ХОЙШИХ мөрүүдийг гажуудуулна. |
| `src/features_reference.py` | f1–f9 ба §4.2-ийн forward label-уудын Python лавлагаа. **Бүтэн жагсаалт + индекс** авдаг, урьдчилж таслагдсан prefix биш — эс бөгөөс leakage бүтцээрээ боломжгүй болж, тест хоосон болно. |
| `data/cache/` | Parity-ийн хоёр файл (15,017 түүхий event; 88 SQL burst мөр). `.gitignore`-д онцгойлж оруулсан — аудитад хэрэгтэй, 4.6 MB. |

## Тест бүрийн жагсаалт

### 1. Temporal leakage — `tests/test_leakage.py` (§3 хатуу дүрэм, §6.1)

| Тест | Юуг батлана | Тоо |
|---|---|---|
| `test_feature_is_blind_to_the_future[feature × perturbation]` | f1–f9 бүрийн t дэх утга нь t-ээс хойших event гажуудахад **өөрчлөгдөхгүй**. Feature тус бүрд тусад нь параметржүүлсэн тул унавал алийг нь мэдэгдэнэ | 9 feature × 3 perturbation = **27** |
| `test_oh_family_is_blind_to_the_future[perturbation]` | OH, OH_ratio, OH_conc, n_wallets t-ийн төлөвөөс л хамаарна (§1.2) | 3 |
| `test_burst_trigger_is_blind_to_the_future[perturbation]` | t хүртэлх burst олонлог өөрчлөгдөхгүй (§4.1) | 3 |
| `test_forward_label_reacts_to_the_future[label]` | **Эсрэг тест:** §4.2-ийн label-ууд ирээдүй өөрчлөгдөхөд **ЗААВАЛ хөдлөнө** | 5 |
| `test_trajectory_and_death_age_react_to_the_future` | §4.3-ийн траектор ба death_age мөн адил хөдлөнө | 1 |
| `test_perturbation_only_touches_the_future` | **Харнесс дээрх хамгаалалт:** perturbation нь өнгөрсөнд хүрээгүйг батална — эс бөгөөс дээрх бүх assertion хоосон болно | 1 |

### 2. Cost basis — `tests/test_cost_basis.py` (§1.2, §7 Phase 2)

| Тест | Юуг батлана |
|---|---|
| `test_sell_leaves_cost_basis_untouched_and_reduces_holding` | §1.2: "Sell гарвал tokens_received-ээс хасаж, cost basis-ийг хэвээр үлдээнэ" |
| `test_repeat_buys_average_by_weight` | Жинлэсэн дундаж (FIFO биш, сүүлийн үнэ биш) |
| `test_cost_basis_after_sell_then_rebuy_uses_all_buys` | Бүрэн зараад дахин авсан wallet **бүх** buy-гаараа дундажлана |
| `test_fully_sold_wallet_is_excluded_from_oh` | `held = 0` wallet OH-д оролцохгүй |
| `test_wallet_that_only_sold_has_no_cost_basis_and_is_skipped` | `buy_units = 0` → cb тодорхойгүй → OH-д орохгүй |
| `test_oh_is_never_negative_and_conc_is_a_share` | §7 Phase 2: OH ≥ 0, 0 ≤ OH_conc ≤ 1 — 120 event дээр event тутам |
| `test_oh_zero_gives_conc_zero` | OH = 0 → OH_conc = 0 (SQL-ийн FIX 2-той нийцнэ) |
| `test_holdings_never_exceed_what_was_bought` | Σ tokens_held ≤ нийт худалдаж авсан |

### 3. Slot ordering ба цонхны хил — `tests/test_slot_ordering.py` (§2.4, §4.3)

| Тест | Юуг батлана |
|---|---|
| `test_events_are_ordered_by_slot_then_tx_index_then_ix_index` | §2.4 + decisions.md-ийн бүтэн эрэмбэ |
| `test_shuffling_the_input_does_not_change_the_result` | Оролтыг холивол үр дүн өөрчлөгдөхгүй |
| `test_three_slot_window_is_half_open_below` | nf3 нь **(a−3, a]**, `[a−3, a)` биш — slot тутам яг нэг event тавьж гараар шалгасан |
| `test_five_slot_flow_window_is_half_open_below` | f1-ийн цонх мөн (s−5, s] |
| `test_rolling_nf3_survives_empty_slots` | **Regression:** хоосон slot цонхыг тэг болгохгүй (2026-08-18-ны засвар) |
| `test_excl_pre_variant_drops_pre_burst_slots` | §4.3-ийн хоёр хувилбарын ялгаа яг burst slot дээр |
| `test_multiple_events_in_one_slot_all_contribute_to_slot_flow` | Slot-ын урсгал нь **нийлбэр**, сүүлийн event биш (мөн тэр засварын regression) |
| `test_state_advances_in_key_order_within_a_slot` | Нэг slot доторх хоёр арилжаа (tx_index, ix_index)-ээр хэрэгжинэ |

### 4. Burst detection — `tests/test_burst.py` (§4.1)

| Тест | Юуг батлана |
|---|---|
| `test_absolute_branch_binds_on_a_shallow_curve` | x=30 дээр босго = max(3, 3.0) = 3 SOL; 1 lamport дутвал гарахгүй |
| `test_depth_branch_binds_on_a_deeper_curve` | x=80 дээр босго = max(3, 8.0) = 8 SOL — 0.10x салаа |
| `test_flow_is_summed_over_the_five_slot_window` | Цонхны нийлбэр; хамгийн эхний хангасан event л burst нээнэ |
| `test_window_is_half_open_so_an_old_trade_drops_out` | 5 slot буцсан арилжаа цонхонд ОРОХГҮЙ |
| `test_sells_offset_buys_in_the_window` | net_flow = buy − sell; **дараалал нь учиртай** — дараа ирсэн sell аль хэдийн гарсан trigger-ийг буцаахгүй |
| `test_second_qualifying_event_inside_25_slots_does_not_open_a_burst` | 25 slot-ын чимээгүй дүрэм |
| `test_qualifying_event_past_25_slots_opens_a_new_burst` | 26 slot зайтай бол шинэ burst |
| `test_quiet_rule_counts_from_the_last_qualifying_event_not_the_burst` | Сессиэлэлтийн ойролцооллыг ил баримтжуулна |
| `test_burst_uses_x_from_the_row_not_a_constant` | x(t) нь мөрөөс уншигдана (§2.3) |

### 5. SQL ↔ Python parity — `tests/test_parity.py` (кэш дата, Dune-гүй)

| Тест | Юуг батлана | Үр дүн |
|---|---|---|
| `test_cache_files_are_present_and_non_trivial` | Кэш байгаа, 88 мөр | PASS |
| `test_burst_sets_agree` | Хоёр тал ижил burst олонлог олно (88/88) | PASS |
| `test_oh_family_matches_to_12_places[oh/oh_ratio/oh_conc]` | §1.2-ийн гурван хэмжигдэхүүн 12 аравтаар таарна | PASS ×3 |
| `test_trajectory_matches_element_by_element[incl_pre/excl_pre]` | §4.3-ийн 88 × 75 = 6,600 элемент, хувилбар тус бүрд, 9 аравтаар | PASS ×2 |
| `test_death_age_matches[incl/excl]` | death_age 88/88 | PASS ×2 |
| `test_trailing_window_features_match_sql[f3/f8/f9]` | f3/f8/f9-ийн trailing цонх нь causal мөн үү | **FAIL ×3 — доорх олдвор** |
| `test_sql_trailing_window_defect_is_characterised` | Согогийн механизмыг 88/88 дээр яг тогтоосон | PASS |

## ⚠ Гурван унасан тест — олдвор

`sql/extract_schema_probe.sql`-ийн f3/f8/f9 нь Python лавлагаатай таарахгүй. **Шалтгааныг таамаглаагүй, хэмжсэн** — `test_sql_trailing_window_defect_is_characterised` нь SQL-ийн зан төлөвийг 88/88 мөр дээр яг дахин үүсгэдэг:

**Согог 1 — slot доторх lookahead (f3, f8, f9).**
`RANGE BETWEEN w PRECEDING AND CURRENT ROW` нь `ORDER BY slot`-той хамт тухайн slot-ыг хуваалцаж буй **бүх мөрийг peer** гэж үзэж frame-д оруулдаг — үүнд `(tx_index, ix_index)`-ээр **дараа гүйцэтгэгдэх** арилжаанууд ч багтана. Энэ бол §6.1-ийн хориглосон ирээдүй рүү харах явдал, яг тэр шалтгаанаар f1-ийн урсгалуудыг prefix sum-ийн зөрүүгээр барьсан юм.

Хэмжилт (88 мөр):

| Дүрэм | f3 таарсан | f8 таарсан |
|---|---|---|
| Causal (s−w, s] | 21/88 (23.9%) | 26/88 (29.5%) |
| Causal [s−w, s] | 21/88 (23.9%) | 28/88 (31.8%) |
| **Peer-тэй [s−w, s]** | 67/88 (76.1%) | **88/88 (100%)** |

**Согог 2 — NULL нь худалдан авагч болж тоологдож байна (зөвхөн f3).**
`array_agg(if(is_buy, wallet))` нь sell мөр бүрт NULL гаргана, `array_distinct` нэгийг үлдээнэ, `cardinality` түүнийг тоолно. Цонхонд ядаж нэг sell байвал `n_buyers` **яг 1-ээр хэтэрнэ**.

| Дүрэм | f3 таарсан |
|---|---|
| Peer-тэй, NULL тоолохгүй | 67/88 (76.1%) |
| **Peer-тэй + NULL тоолсон** | **88/88 (100%)** |

Хоёулаа хэрэгтэй — аль нэг нь дангаараа 76% / 24% дээр үлдэнэ.

**Засаагүй.** Энэ даалгаврын заавар нь унасан тестийг тайлагнах, засахгүй байх байсан.

**Хамрах хүрээ:** f1 (net_flow_3/5/12/25slot), OH-ийн бүлэг, траектор, death_age, forward label-ууд бүгд **энэ согогоос ангид** — тэдгээр нь prefix sum-ийн зөрүү эсвэл slot-ын нягт тор дээр баригдсан. Зөвхөн f3, f8, f9 өртсөн.

## `pytest -q`-ийн бүтэн гаралт

```
........................................................................ [ 76%]
..........FFF.........                                                   [100%]
=========================== short test summary info ============================
FAILED tests/test_parity.py::test_trailing_window_features_match_sql[f3-n_buyers-n_buyers_12slot]
FAILED tests/test_parity.py::test_trailing_window_features_match_sql[f8-size_cv-size_cv_25slot]
FAILED tests/test_parity.py::test_trailing_window_features_match_sql[f9-round_frac-round_frac_25slot]
3 failed, 91 passed in 0.81s
```

### Тест бүрийн жагсаалт (94)

```
  PASSED tests/test_burst.py::test_absolute_branch_binds_on_a_shallow_curve
  PASSED tests/test_burst.py::test_depth_branch_binds_on_a_deeper_curve
  PASSED tests/test_burst.py::test_flow_is_summed_over_the_five_slot_window
  PASSED tests/test_burst.py::test_window_is_half_open_so_an_old_trade_drops_out
  PASSED tests/test_burst.py::test_sells_offset_buys_in_the_window
  PASSED tests/test_burst.py::test_second_qualifying_event_inside_25_slots_does_not_open_a_burst
  PASSED tests/test_burst.py::test_qualifying_event_past_25_slots_opens_a_new_burst
  PASSED tests/test_burst.py::test_quiet_rule_counts_from_the_last_qualifying_event_not_the_burst
  PASSED tests/test_burst.py::test_burst_uses_x_from_the_row_not_a_constant
  PASSED tests/test_cost_basis.py::test_sell_leaves_cost_basis_untouched_and_reduces_holding
  PASSED tests/test_cost_basis.py::test_repeat_buys_average_by_weight
  PASSED tests/test_cost_basis.py::test_cost_basis_after_sell_then_rebuy_uses_all_buys
  PASSED tests/test_cost_basis.py::test_fully_sold_wallet_is_excluded_from_oh
  PASSED tests/test_cost_basis.py::test_wallet_that_only_sold_has_no_cost_basis_and_is_skipped
  PASSED tests/test_cost_basis.py::test_oh_is_never_negative_and_conc_is_a_share
  PASSED tests/test_cost_basis.py::test_oh_zero_gives_conc_zero
  PASSED tests/test_cost_basis.py::test_holdings_never_exceed_what_was_bought
  PASSED tests/test_curve.py::test_initial_state_satisfies_invariant
  PASSED tests/test_curve.py::test_spot_price_forms_agree_on_exact_invariant_state
  PASSED tests/test_curve.py::test_migration_threshold_is_curve_progress_one
  PASSED tests/test_curve.py::test_tokens_out_matches_closed_form
  PASSED tests/test_curve.py::test_sell_is_inverse_of_buy_up_to_one_lamport
  PASSED tests/test_curve.py::test_round_trip_costs_are_monotone_in_depth_and_size
  PASSED tests/test_curve.py::test_slippage_and_latency_reference_values
  PASSED tests/test_curve.py::test_net_convention_passes_amount_through
  PASSED tests/test_curve.py::test_gross_convention_removes_fee_on_the_correct_side
  PASSED tests/test_curve.py::test_convention_choice_shifts_reconstruction_by_about_one_percent
  PASSED tests/test_curve.py::test_out_of_order_event_raises
  PASSED tests/test_curve.py::test_intra_transaction_order_is_resolved_by_ix_index
  PASSED tests/test_curve.py::test_replay_never_silently_sorts
  PASSED tests/test_curve.py::test_state_violation_is_recordable_and_leaves_state_untouched
  PASSED tests/test_curve.py::test_x_post_chains_into_next_x_pre
  PASSED tests/test_curve.py::test_integer_replay_is_exact_over_1e5_events
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-accel]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-curve_progress]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-depth_x]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-n_buyers_12slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-net_flow_12slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-net_flow_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-net_flow_5slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-round_frac_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[flip_side-size_cv_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-accel]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-curve_progress]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-depth_x]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-n_buyers_12slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-net_flow_12slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-net_flow_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-net_flow_5slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-round_frac_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[insert_events-size_cv_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-accel]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-curve_progress]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-depth_x]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-n_buyers_12slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-net_flow_12slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-net_flow_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-net_flow_5slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-round_frac_25slot]
  PASSED tests/test_leakage.py::test_feature_is_blind_to_the_future[scale_sol_x100-size_cv_25slot]
  PASSED tests/test_leakage.py::test_oh_family_is_blind_to_the_future[flip_side]
  PASSED tests/test_leakage.py::test_oh_family_is_blind_to_the_future[insert_events]
  PASSED tests/test_leakage.py::test_oh_family_is_blind_to_the_future[scale_sol_x100]
  PASSED tests/test_leakage.py::test_burst_trigger_is_blind_to_the_future[flip_side]
  PASSED tests/test_leakage.py::test_burst_trigger_is_blind_to_the_future[insert_events]
  PASSED tests/test_leakage.py::test_burst_trigger_is_blind_to_the_future[scale_sol_x100]
  PASSED tests/test_leakage.py::test_forward_label_reacts_to_the_future[fwd_net_flow_12slot]
  PASSED tests/test_leakage.py::test_forward_label_reacts_to_the_future[fwd_net_flow_37slot]
  PASSED tests/test_leakage.py::test_forward_label_reacts_to_the_future[fwd_net_flow_5slot]
  PASSED tests/test_leakage.py::test_forward_label_reacts_to_the_future[fwd_price_ret_12slot]
  PASSED tests/test_leakage.py::test_forward_label_reacts_to_the_future[x_at_plus12]
  PASSED tests/test_leakage.py::test_trajectory_and_death_age_react_to_the_future
  PASSED tests/test_leakage.py::test_perturbation_only_touches_the_future
  PASSED tests/test_parity.py::test_cache_files_are_present_and_non_trivial
  PASSED tests/test_parity.py::test_burst_sets_agree
  PASSED tests/test_parity.py::test_oh_family_matches_to_12_places[oh]
  PASSED tests/test_parity.py::test_oh_family_matches_to_12_places[oh_ratio]
  PASSED tests/test_parity.py::test_oh_family_matches_to_12_places[oh_conc]
  PASSED tests/test_parity.py::test_trajectory_matches_element_by_element[incl_pre]
  PASSED tests/test_parity.py::test_trajectory_matches_element_by_element[excl_pre]
  PASSED tests/test_parity.py::test_death_age_matches[incl]
  PASSED tests/test_parity.py::test_death_age_matches[excl]
  PASSED tests/test_parity.py::test_sql_trailing_window_defect_is_characterised
  PASSED tests/test_slot_ordering.py::test_events_are_ordered_by_slot_then_tx_index_then_ix_index
  PASSED tests/test_slot_ordering.py::test_shuffling_the_input_does_not_change_the_result
  PASSED tests/test_slot_ordering.py::test_three_slot_window_is_half_open_below
  PASSED tests/test_slot_ordering.py::test_five_slot_flow_window_is_half_open_below
  PASSED tests/test_slot_ordering.py::test_rolling_nf3_survives_empty_slots
  PASSED tests/test_slot_ordering.py::test_excl_pre_variant_drops_pre_burst_slots
  PASSED tests/test_slot_ordering.py::test_multiple_events_in_one_slot_all_contribute_to_slot_flow
  PASSED tests/test_slot_ordering.py::test_state_advances_in_key_order_within_a_slot
  FAILED tests/test_parity.py::test_trailing_window_features_match_sql[f3-n_buyers-n_buyers_12slot]
  FAILED tests/test_parity.py::test_trailing_window_features_match_sql[f8-size_cv-size_cv_25slot]
  FAILED tests/test_parity.py::test_trailing_window_features_match_sql[f9-round_frac-round_frac_25slot]
```
