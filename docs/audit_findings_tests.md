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
