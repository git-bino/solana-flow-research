# Аудитын олдвор бүрд regression тест

**Огноо:** 2026-08-19 · `tests/synthetic.py` (өргөтгөсөн) · `tests/test_audit_findings.py`
**Dune-д хандаагүй** (үлдэгдэл 26.84) · extract хийгээгүй · SQL засварлаагүй ·
`src/oh_reference.py` **хөндөөгүй** · Phase 3b рүү ороогүй

## Яагаад генератораас эхэлсэн

Гадаад аудитын олдсон дөрвөн ангиллын согогийг өмнөх **157 тестийн аль нь ч бариагүй**.
Шалтгаан нь тестүүд биш: `tests/synthetic.py` тэдгээр нөхцөлийг **үүсгэдэггүй** байсан тул
ямар ч тест тэднийг харах боломжгүй байв. Генераторын хамрах хүрээ нь тестийн хүчийг
тодорхойлно.

## Генераторын өргөтгөл

Одоо байгаа урсгалуудыг **битийн түвшинд хөдөлгөөгүй**: `n_tx_per_slot is None` ба
`n_events_per_tx == 1` үед `make_token` нь хуучин замаараа явна. 157 тест өөрчлөлтгүй
давсан.

| Нэмэлт | Юу боломжтой болсон |
|---|---|
| `SyntheticConfig.n_events_per_tx` | нэг транзакц доторх олон leg (зэрэгцээ) |
| `SyntheticConfig.n_tx_per_slot` | нэг slot доторх олон транзакц (эрэмбэтэй) |
| `RawEvent` | `vtok` (токен талын нөөц) ба **түүхий `(outer, inner)`** — `Event`-д байхгүй |
| `Transfer` | SPL шилжүүлэг, **TradeEvent үүсгэхгүй** |
| `same_slot_stream` | 1 ба 2-ыг хослуулсан урсгал |
| `mayhem_reparameterised` | `vsol` үсэрч `vtok` арилжаатай нийцсэн хэвээр |
| `transfer_then_sell` | A авна → B рүү шилжүүлнэ → B зарна (сөрөг inventory) |
| `exit_then_rebuy` | `held → 0 → buy` |
| `packing_collision_pair` / `packing_null_inner` | `inner ≥ 64`, `inner = NULL` |
| `trigger_with_same_slot_neighbours` | trigger-ийн ижил slot-д өмнө/дараа арилжаа |

`Event` нь `vtok`-г ч, түүхий индексийг ч авч явдаггүй бөгөөд `src/oh_reference.py`-г
өөрчлөхийг зөвшөөрөөгүй тул баян баримтууд `RawEvent`-д амьдарч, `.to_event()`-ээр
доош проекцлогдоно. **ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР.**

## Тестүүд

Хоёр төрлийг зориудаар өөрөөр тэмдэглэсэн:

- **`xfail(strict=True)`** — зан төлөв буруу, ЗӨВ хүлээлтийг бичсэн. Заваагүй.
- **`..._documents_current_incorrect_behavior`** — зан төлөв мөн буруу, гэвч тест нь
  **өнөөдрийн** байдлыг батална, ингэснээр өөрчлөгдвөл харагдана.

| # | Тест | Аудитын олдвор | Юуг батлав | Үр дүн |
|---|---|---|---|---|
| A1 | `test_forward_flow_excludes_trades_in_the_triggers_own_slot` | Label-ийн хил | `fwd_net_flow(12)` нь trigger-ийн ижил slot-ын дараагийн арилжааг тоолохгүй | **XFAIL** (strict) |
| A2 | `test_trailing_features_exclude_trades_after_the_trigger_in_its_slot` | Label-ийн хил | `net_flow_5slot` = 1.5 SOL, дараагийн 3 арилжааг тоолохгүй | **PASS** |
| A3 | `test_trailing_features_include_trades_before_the_trigger_in_its_slot` | Label-ийн хил | `n_buyers_12slot` = 2, өмнөх арилжааг ТООЛНО | **PASS** |
| A4 | `test_generator_can_put_several_transactions_in_one_slot` | Генераторын хамрах хүрээ | 3 tx × 2 leg = 6 event, нэг slot-д | **PASS** |
| B1 | `test_transfer_leaves_sender_inventory_untouched_…` | SPL transfer | A-ийн `held_units` = 100,000,000 (бодит нь 40,000,000) | **PASS** (буруу зан төлөв) |
| B2 | `test_transfer_recipient_goes_negative_…` | SPL transfer | B-ийн `held_units` = **−60,000,000** | **PASS** (буруу зан төлөв) |
| B3 | `test_overhead_credits_the_sender_for_transferred_tokens_…` | SPL transfer | OH нь A-г 100 токеноор үнэлнэ → **яг 2.5×** хэтрэлт; B нь `held > 0` шүүлтээр хасагдана | **PASS** (буруу зан төлөв) |
| C1 | `test_cost_basis_after_full_exit_keeps_the_old_buys_…` | Cost basis reset | одоогийн **5.5**, reset хийвэл **10**, зөрүү **4.5** | **PASS** (буруу зан төлөв) |
| C2 | `test_buy_fee_is_not_part_of_the_cost_basis` | Cost basis | basis нь **яг 1**, шимтгэлтэй бол 1.0126582… байх байсан | **PASS** |
| D1 | `test_packing_collides_for_inner_at_least_64` | `ix_index` packing | (0,64) ба (1,0) хоёр **64** болж мөргөлдөнө | **PASS** |
| D2 | `test_raw_outer_inner_pair_still_orders_the_colliding_events` | `ix_index` packing | түүхий хосоор эрэмбэлбэл ялгагдана | **PASS** |
| D3 | `test_null_inner_is_coalesced_to_zero` | `ix_index` packing | (3, NULL) → **192**, (3,0)-оос ялгагдахгүй | **PASS** |
| E1 | `test_launch_k_and_instantaneous_k_disagree_after_mayhem_…` | launch k | `P_launch/P_inst = k_now/k₀` = **1.5** | **PASS** (буруу зан төлөв) |
| E2 | `test_overhead_differs_between_the_two_price_conventions_…` | launch k | `OH_launch > OH_inst > 0` | **PASS** (буруу зан төлөв) |
| F1 | `test_every_generator_parameter_is_exercised_by_some_test` | Мета | параметр бүр дор хаяж нэг тестэд ашиглагдана | **XFAIL** (strict) |
| F2 | `test_measured_generator_parameter_coverage_is_pinned` | Мета | хэмжсэн цоорхойг тогтоов | **PASS** |
| F3 | `test_generator_builds_every_audited_condition` | Мета | таван нөхцөл тус бүр нэг дуудлагаар баригдана | **PASS** |

**15 passed, 2 xfailed.**

### Хүлээлтийн эх сурвалж

Тест бүрийн docstring-д бичигдсэн. Кодын гаралтаас уншаагүй. Гол гараар бодсон тоонууд:

- **A2:** нэг slot-д 0.5 SOL-ын 5 buy — 2 өмнө, trigger, 3 дараа. Trailing цонх зөвхөн
  эхний гурвыг харна → `3 × 0.5 = 1.5 SOL`.
- **A3:** өмнөх хоёр нь `W_B`, trigger нь `W_A` → ялгаатай buyer **2**. Дараагийн гурав
  нь `W_C`, тоологдвол 3 болох байсан.
- **B3:** OH = `held/1e6 × (P − cb)`; 100 vs 40 токен → харьцаа **яг 2.5**.
- **C1:** `cb = (1e9 + 1e10)/((1e6+1e6)×1000) = 5.5`; reset-тэй `1e10/(1e6×1000) = 10`.
- **C2:** `1e9/(1e6×1000) = 1`; 1.25%-ийн шимтгэл орсон бол `1/(1−0.0125) = 1.0126582…`.
- **D1:** `0×64 + 64 = 64` ба `1×64 + 0 = 64`.
- **E1:** алгебраар — `P_launch/P_inst = (x²/k₀)/(x/y) = x·y/k₀ = k_now/k₀`; fixture нь
  SOL талыг 1.5 дахин үсрүүлж токен талыг хөдөлгөөгүй тул харьцаа = **1.5**.

## Хоёр XFAIL

**A1 — label-ийн хил.** `fwd_net_flow` нь trigger-ийн **мөрийг** хил болгодог тул ижил
slot-д хожим гүйцэтгэгдсэн арилжааг тоолно. Цонх нь `(s, s+τ]` учир тэднийг хасах ёстой.
Fixture дээр 1001..1012 slot-д юу ч байхгүй тул зөв хариу **0 SOL**, одоогийн код
**1.5 SOL** гаргана. (Энэ нь 2026-08-18-ны FIX 6-ийн шууд эсрэг чиглэл — тэр үед хилийг
мөрийн түвшинд болгосон; 2026-08-19-ний decisions.md slot-ийн түвшинд заажээ.)

**F1 — генераторын хамрах хүрээ.** 11 параметрийн **6 нь ямар ч тестэд хувьсдаггүй**:
`mayhem_share`, `n_tokens`, `n_wallets`, `round_share`, `sell_share`, `slot_density`.
Багц дахь бүх урсгал тэднийг анхны утган дээр нь үлдээдэг тул тэдгээрийн удирддаг зан
төлөв **шалгагдаагүй**. Энэ бол аудитын сургамжийн нэг алхам гүнзгий хувилбар:
генератор үүсгэж чадахгүй нөхцөлийг тест харж чадахгүй; тестийн хөдөлгөдөггүй параметр
нь мөн ялгаагүй.

> Эхний хувилбарт би параметр → файлын **гараар бичсэн** зураглал үүсгэж баталсан.
> Тэр зураглал **буруу** байсан (`test_parity.py` нь `n_tokens`-ыг ашигладаг гэж бичсэн
> боловч parity нь кэшлэгдсэн бодит дата дээр ажилладаг, генератор ашигладаггүй) бөгөөд
> тест унасан. Таамгийг хэмжилтээр сольсон: `_parameters_varied_by_tests()` нь
> `param=` түлхүүр-аргументын хэлбэрийг хайдаг ба өөрийнхөө мөрийн литералуудыг
> тооцохгүй — эс тэгвээс мета-тест өөрийгөө зөвтгөх байсан. **ЭНЭ БОЛ CLAUDE CODE-ИЙН
> ШИЙДВЭР.**

## УНАСАН ТЕСТ — засаагүй, тайлагнаж байна

```
FAILED tests/test_cost_model.py::test_path_with_flow_reversals_still_only_depends_on_the_net
```

Энэ бол өчигдрийн Phase 1-ийн тест бөгөөд тэр үед давсан. Оношилгоо (таамаглал биш,
хэмжсэн):

| | |
|---|---|
| Шалтгаан | `tests/test_curve.py:45` нь import үедээ **глобал** `getcontext().prec = 40` тавина |
| Decimal-ийн контекст | thread-local глобал — модуль хооронд **алддаг** |
| Хүлцэл | миний бичсэн `1e-40` |
| Бодит зөрүү, `prec=60` | **4.000e-59** ✓ |
| Бодит зөрүү, `prec=40` | **2.000e-39** ✗ |
| Дараалалаас хамаарал | `test_curve` дараа нь орвол **51 passed**; `test_cost_model` дараа нь орвол **1 failed** |

Өөрөөр хэлбэл тест нь Phase 1-д **санамсаргүйгээр** давсан бөгөөд `test_audit_findings.py`
нэмэгдсэний дараа цуглуулгын дараалал өөрчлөгдөж илэрсэн. Согог нь `cost_model`-д биш —
загвар prec=60 дээр 1e-59 нарийвчлалтай. **Заваагүй** (даалгаврын дүрэм: унасныг
тайлагна, засахыг бүү оролд).

## `pytest -q` — бүтэн гаралт

```
x.............x.....................................F................... [ 41%]
........................................................................ [ 82%]
..............................                                           [100%]
=================================== FAILURES ===================================
_________ test_path_with_flow_reversals_still_only_depends_on_the_net __________

    def test_path_with_flow_reversals_still_only_depends_on_the_net():
        mixed = [Decimal(5), Decimal(-4), Decimal(3), Decimal(-1)]      # net 3
>       assert abs(net_pnl_path(50, 1, ZERO, mixed)
                   - net_pnl(50, 1, V=0, W=Decimal(3))) < Decimal("1e-40")
E       AssertionError: assert Decimal('2E-39') < Decimal('1E-40')
E        +  where Decimal('2E-39') = abs((Decimal('0.093159744502129148923758968675261039493') - Decimal('0.093159744502129148923758968675261039491')))
E        +    where Decimal('0.093159744502129148923758968675261039493') = net_pnl_path(50, 1, Decimal('0'), [Decimal('5'), Decimal('-4'), Decimal('3'), Decimal('-1')])
E        +    and   Decimal('0.093159744502129148923758968675261039491') = net_pnl(50, 1, V=0, W=Decimal('3'))
E        +      where Decimal('3') = Decimal(3)
E        +  and   Decimal('1E-40') = Decimal('1e-40')

tests/test_cost_model.py:99: AssertionError
=========================== short test summary info ============================
FAILED tests/test_cost_model.py::test_path_with_flow_reversals_still_only_depends_on_the_net
1 failed, 171 passed, 2 xfailed in 1.00s
```

**171 passed · 2 xfailed · 1 failed.** Өмнөх 157 + шинэ 17 = 174.

## Хийгээгүй зүйлс

`src/oh_reference.py` **хөндөөгүй** · SQL-ийн extract query **засварлаагүй** ·
xfail-ийн аль нь ч заваагүй · Dune query **үгүй** (үлдэгдэл 26.84 хэвээр) ·
Phase 3b **үгүй** · `data/holdout/` хөндөөгүй.

---

# Тестийн дэд бүтэц ба параметрийн хамрах хүрээ

**Огноо:** 2026-08-19 (нэмэлт) · Dune-д хандаагүй (үлдэгдэл 26.84) ·
`src/oh_reference.py`, SQL extract query, A1/B/C/E-ийн тестүүд **хөндөгдөөгүй**

## 1. Decimal-ийн глобал контекст

**Согог:** `tests/test_curve.py:45` нь import үедээ `getcontext().prec = 40` тавьдаг.
Decimal-ийн контекст нь thread-local **глобал** тул модуль хооронд алддаг ба
`test_cost_model`-ийн үр дүн цуглуулгын дараалалаас хамаарч байв.

**Засвар:** тэр мөрийг `localcontext()`-т суурилсан autouse fixture-ээр сольсон —
prec = 40 нь зөвхөн тэр модулийн тестүүдэд үйлчилж, гарахдаа өмнөх контекстыг сэргээнэ.
Ямар ч тест модуль одоо глобал контекст өөрчилдөггүй.

**`src/`-д үлдсэн, ЗАСААГҮЙ (src-ийн өөрчлөлт тул асуух ёстой):**

| файл | мөр |
|---|---|
| `src/cost_model.py:44` | `getcontext().prec = 60` |
| `src/features_reference.py:27` | `getcontext().prec = 60` |
| `src/oh_reference.py:34` | `getcontext().prec = 60` |

Гурвуулаа **60** тул одоогоор зөрчилдөхгүй, гэвч аль нэг нь өөр утга авбал дахин
дараалалаас хамаарах болно. Тестүүд одоо өөрсдийн prec-ээ хаалттай тавьдаг тул
**энэ эрсдэлээс хамгаалагдсан**: глобал контекстыг санаатайгаар `prec = 9` болгож
ажиллуулахад `tests/test_cost_model.py`-ийн **35 тест бүгд давсан**.

### Санамсаргүй дараалал × 5

run 1: 198 passed, 1 xfailed in 1.27s
        order: slot_ordering, generator_parameters, curve, cost_basis, reconstruct_label, parity, leakage, label_boundary, burst, cost_model, audit_findings
run 2: 198 passed, 1 xfailed in 1.11s
        order: generator_parameters, curve, audit_findings, leakage, cost_basis, slot_ordering, burst, cost_model, label_boundary, reconstruct_label, parity
run 3: 198 passed, 1 xfailed in 1.11s
        order: cost_basis, audit_findings, burst, curve, label_boundary, slot_ordering, reconstruct_label, cost_model, generator_parameters, parity, leakage
run 4: 198 passed, 1 xfailed in 0.99s
        order: generator_parameters, leakage, curve, audit_findings, cost_basis, reconstruct_label, slot_ordering, cost_model, parity, burst, label_boundary
run 5: 198 passed, 1 xfailed in 0.98s
        order: burst, audit_findings, cost_model, slot_ordering, cost_basis, generator_parameters, curve, reconstruct_label, parity, label_boundary, leakage

Тав нь бүгд **ижил** — `198 passed, 1 xfailed`.

## 2. Phase 1-ийн тестүүдийн нарийвчлал

Тэдгээр нь prec-ээ заагаагүй тул хамгийн сүүлд import хийгдсэн модулийн үлдээсэн
глобал утга дээр ажиллаж, **санамсаргүйгээр** давж байсан. Одоо тест бүр
`@pytest.mark.prec(N)` тэмдэгтэй бөгөөд autouse fixture нь `localcontext`-оор тавина.

**N-ийг хэмжсэн** (`COST_MODEL_PREC_OVERRIDE` sweep, prec ∈ {8…80}). "Тогтвортой
хязгаар" гэдэг нь **N-ээс дээш бүх** prec дээр давдаг хамгийн бага утга — энгийн
"хамгийн бага давсан" биш, учир нь давалт **монотон биш**:

| Тест | prec ≥ | Доор нь унадаг |
|---|---|---|
| `test_breakeven_w_increases_with_depth` | **8** | — |
| `test_breakeven_w_increases_with_order_size` | **8** | — |
| `test_fees_alone_cost_about_two_fee_rates_of_q` | **8** | — |
| `test_legacy_overstates_the_required_flow_on_every_reference_cell` | **8** | — |
| `test_positive_flow_is_profitable_and_monotone_without_fees` | **8** | — |
| `test_breakeven_w_substituted_back_gives_zero_pnl_everywhere` | **12** | 8, 10 |
| `test_legacy_formula_fails_the_counterexample` | **16** | 8–14 |
| `test_latency_flow_alone_is_not_a_loss` | **18** | 8–16 |
| `test_round_trip_with_no_flow_and_no_fees_is_exactly_zero` | **18** | 8–16 |
| `test_small_q_limit_is_the_pure_fee_price_move` | **22** | 8–20 |
| `test_flow_path_does_not_matter_only_the_net` | **40** | 10–38 |
| `test_path_with_flow_reversals_still_only_depends_on_the_net` | **42** | 8–40 |

**Модулийн хэмжээнд: prec ≥ 42.**

Монотон бус байдлын жишээ: `test_path_with_flow_reversals` нь prec = 35 дээр
**давдаг** ч 40 дээр **унадаг** — 35 дээр хоёр утга санамсаргүйгээр ижил орон
хүртэл бөөрөнхийлөгддөг. Тиймээс "хамгийн бага давсан" гэдэг хэмжигдэхүүн
төөрөгдүүлнэ. **ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР** — тогтвортой хязгаарыг сонгосон.

Хоёр хамгийн шаардлагатай тест нь `1e-40` хүлцэлтэй хоёр — өчигдөр унасан нь тэдний
нэг. Ямар ч тест бодитой prec дээр давахгүй байсан тохиолдол **гараагүй** тул
зогсох шаардлага үүсээгүй.

## 3. F1-ийн 6 параметр — `tests/test_generator_parameters.py`

| Параметр | Тест | Хүлээлтийн эх сурвалж | Үр дүн |
|---|---|---|---|
| `sell_share` | cost basis тогтмол, inventory буурна | **§1.2**: "Sell гарвал … cost basis-ийг хэвээр үлдээнэ" | **PASS** |
| `slot_density` | trailing цонхны хил нягтралаас хамаарахгүй | §3, §6.1 цонх `(s−w, s]`; 300 event, бүх trigger дээр тодорхойлолтоос дахин гаргасан | **PASS** |
| `round_share` | f9 = **яг 0** (share=0) ба **яг 1** (share=1); 0.5 дээр [0.40, 0.60] | §3 f9; Binomial(400, 0.5), sd = 10, ±4sd | **PASS** ×3 |
| `mayhem_share` | flagged тоо = `round(n·share)`; mayhem дээр `P_launch/P_inst = 1.5`, цэвэр дээр `= 1` | §1.1 `P = x²/k`, `k` createevent-ээс; алгебр `P_launch/P_inst = x·y/k₀` | **PASS** ×5 |
| `n_wallets` | `n = 3` дээр `oh_conc = 1` **яг**; n өсөхөд буурна | §1.2 OH_conc = дээд-3-ын хувь | **PASS** ×5 |
| `n_tokens` | токен хоорондын ledger тусгаарлагдсан | §1.2 (wallet, token) тус бүрд | **PASS** |

**16 тест, бүгд PASS.**

### Хоёр параметр ИДЭВХГҮЙ байсан — олдвор

- **`mayhem_share`** нь `SyntheticConfig`-д зарлагдсан боловч `make_token` **уншдаггүй**
  байсан: түүнийг өөрчлөхөд юу ч өөрчлөгддөггүй.
- **`n_wallets`** нь зөвхөн wallet-ийн санг хэмжихэд ашиглагдаж, хэмжигдэх үр дүнд
  нөлөөлдөггүй байв.

Хоёуланд нь бүтээгч нэмсэн (`make_mixed_mayhem_stream`, `make_wallet_ladder`).
**ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР** — өөр сонголт нь хоёр параметрийг үүрд
шалгагдахааргүй үлдээх байлаа.

### Нэг хүлээлт БУРУУ байсан

Даалгаварт `sell_share` өсөхөд "OH-д оролцох wallet-ийн тоо буурна" гэсэн. **Буурдаггүй.**
Генератор нь `rng.randint(1, sellable)` буюу **хэсэгчлэн** зардаг тул wallet бараг
хэзээ ч яг тэг дээр буудаггүй: sell_share = 0.0 ба 0.9 хоёуланд нь эерэг үлдэгдэлтэй
wallet **12 хэвээр**. Хэмжсэн баримтыг тестэд бичиж тогтоов (позицийг бүрэн хаадаг
генератор ирвэл энэ тест барина); хөдөлдөг хэмжигдэхүүн нь **нийт inventory**.

## 4. F1 мета-тест

6 параметр хамрагдсаны дараа F1 **PASS болсон** → `xfail` **хасагдсан**.
Зураглал нь **хэмжилтээр** (`_parameters_varied_by_tests`, `param=` түлхүүр-аргумент
хэлбэр, өөрийн мөрийн литералуудыг тооцохгүй) тул `SyntheticConfig`-д шинэ параметр
нэмэгдэхэд гараар юу ч шинэчлэхгүйгээр автоматаар барина.
`UNEXERCISED_PARAMETERS` одоо **хоосон**.

**Үлдсэн `xfail` ганц:** A1 (`fwd_net_flow`-ийн label-ийн хил) — дахин extract-ийн
дараа шийдэгдэнэ, хөндөөгүй.

## `pytest -q` — бүтэн гаралт (шинэчилсэн)

```
x....................................................................... [ 36%]
........................................................................ [ 72%]
.......................................................                  [100%]
198 passed, 1 xfailed in 1.38s
```

**198 passed, 1 xfailed, 0 failed.** Өмнөх ажиллуулалтын 1 FAILED (Decimal-ийн
контекстын алдагдал) арилсан.

---

## Extract v2-ийн зан төлөвийн тестүүд (2026-08-19)

`tests/test_extract_v2.py` — 17 тест, бүгд PASS. `tests/test_audit_findings.py`-ийн
v1 тестүүдийг **хөндөөгүй**: A1 нь xfail хэвээр, B/C/E-ийн
`_documents_current_incorrect_behavior` тестүүд хэвээрээ. Хос болгож нэмсэн:

| v1 (одоогийн зан төлөв) | v2 (шинэ SQL-ийн зан төлөв) |
|---|---|
| A1 `fwd_net_flow` ижил slot-ыг тоолно → **xfail** | `test_v2_forward_flow_excludes_the_triggers_own_slot_correct_behavior` → **PASS** (+ хоосон биш болохыг батлах хамгаалагч) |
| B1 илгээгч 100,000,000 хэвээр | `test_v2_transfer_moves_the_balance_off_the_sender...` → **40,000,000** |
| B2 хүлээн авагч −60,000,000 | `test_v2_transfer_recipient_does_not_go_negative...` → **0** |
| B3 OH 2.5× хэтэрсэн | хувилбар (а) 40,000,000-оор үнэлнэ; (б) нь тэр fixture дээр (а)-тай **тэнцэнэ**, тусад нь ялгах fixture нэмсэн |
| C1 basis 5.5 | `test_v2_cost_basis_resets_after_a_full_exit...` → **10** |
| C2 basis 1 (шимтгэлгүй) | `test_v2_buy_fee_enters_the_cost_basis...` → **1.0125** |
| E1 `P_launch/P_inst = 1.5` | `test_v2_price_uses_the_live_reserves...` — үндсэн нь `x/y`, `p_launch` багана болж үлдсэн |

Нэмэлт: schema-ийн гурван тест (зөвхөн `ix_index` хасагдсан + `oh*` хос болсон;
түлхүүр нь түүхий хос; **баганын жагсаалт SQL-ээс задлан шинжилж тулгасан**) ба
transfer унтраасан үед v1-ийн ledger-тэй таарах parity тест.

### `pytest -q` — v2-ийн дараах бүтэн гаралт

```
x....................................................................... [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
215 passed, 1 xfailed in 1.25s
```

**215 passed, 1 xfailed, 0 failed.** Үлдсэн ганц xfail нь A1-ийн **v1** хувилбар —
дахин extract хийгдэх хүртэл хэвээр.
