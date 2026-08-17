# Phase 0 — Extract schema-ийн бүрэн тооллого

**Огноо:** 2026-08-18 · SQL: `sql/extract_schema_probe.sql` · Cohort: 2026-06-01 launch, SOL-quote, event 06-11 23:59 хүртэл
**Зөвхөн тооллого ба хэмжилт.** Extract ажиллуулаагүй, багана хаяагүй, шийдвэр гаргаагүй.

**Credit:** бюджет ≤60 · **зарцуулсан 14.00** (301.93 → 315.93) · **үлдэгдэл 2,184.07**

---

## Алхам 1 — Тооллого

Ангилал: **(a)** burst мөрөнд скаляр · **(b)** траектор шаардана · **(c)** burst бус event-ийн мэдээлэл · **(d)** сүлжээ даяарх минутын aggregate · **(e)** ex-post rug label

| Хэмжигдэхүүн | Spec | Ангилал | Тэмдэглэл |
|---|---|---|---|
| `net_flow_5slot / 12slot / 25slot` | §3 f1 | **(a)** | 3 скаляр |
| `net_flow_3slot` | §4.3, §5.1, §12.4 | **(a)** | exit дүрэм ба hazard-ийн суурь |
| `accel` | §3 f2 | **(a)** | f1-ээс гарна |
| `n_buyers_12slot` | §3 f3 | **(a)** | window дотор `count(DISTINCT)` — доорх алхам 3 |
| `depth` = x | §3 f4 | **(a)** | мөрөөс шууд (`virtual_sol_reserves`) |
| `curve_progress` | §3 f5 | **(a)** | (x−30)/85 |
| `burst_age` | §3 f6 | **(a)** = 0 | burst_start дээр тодорхойлолтоор 0; hazard-д траектор болно → **(b)** |
| `OH_ratio` | §3 f7, §1.2 | **(a)** | батлагдсан (`docs/phase0_oh_feasibility.md`) |
| `OH_conc` | §3 f7b, §1.2 | **(a)** | батлагдсан |
| `size_cv` (25 slot) | §3 f8 | **(a)** | `stddev_pop`/`avg` window |
| `round_frac` (25 slot) | §3 f9 | **(a)** | 0.1/0.5/1.0 SOL |
| `mkt_active_bursts` | §3 f10 | **(d)** | минутын мөр; §0.1-д 129,600 мөр = 6.2 MB / 90 хоног |
| `mkt_total_flow` | §3 f11 | **(d)** | адил таталт |
| `cluster_seen` | §3 f12 | — | Phase 6 хүртэл тооцохгүй; санхүүжилтийн graph нь pump.fun table-д БАЙХГҮЙ өөр эх сурвалж |
| burst identity, threshold нүд | §4.1 | **(a)** | 0.05x/0.10x/0.20x — доорх сануулга |
| `fwd_net_flow(5/12/37 slot)` | §4.2 | **(a)** | forward RANGE frame; lookahead нь label тул зөв |
| `fwd_price_ret(τ)` | §4.2 | **(a)** | x(t+τ) → `last_value` forward |
| `fwd_net_ret(τ)` | §4.2, §5 | **(c)** | **exit дүрмээс хамаарна — доорх "гол хамаарал"** |
| `burst_alive(a)`, a = 1..75 slot | §4.3, §7 3c | **(a)** эсвэл **(b)** | "хэвээр" нь absorbing бол `death_age_slot` нэг скаляр хүрэлцэнэ; absorbing биш бол 75 утгын траектор — **хоёуланг тоолсон** |
| `V` = latency-ийн үеийн урсгал | §5 | **(c)** | L1 = 1 slot, L2 = 1000ms ≈ 2.5 slot, L3 = 3000ms ≈ 7.5 slot → 1/2/3/7/8 slot offset-ууд |
| `x_at_signal`, `K` | §5 | **(a)** | x мөрөөс, K = x₀·y₀ токен тус бүрээс |
| q, latency_ms, fees | §5 | — | параметр, дата биш |
| Exit агшин ба exit үнэ | §5.1 | **(b)+(c)** | exit slot нь `net_flow_3slot < 0` + A насны хязгаараас; A нь **Phase 3-ийн гаралт** |
| Exit latency-ийн V (нөхцөлт сөрөг) | §5.1.2 | **(c)** | exit агшны дараах slot-уудын урсгал |
| Rug tail case (dev dump танхайрсан) | §5.1.3 | **(c)+(e)** | dev хаяг + dump агшин шаардана |
| Baseline тархалт, power | §7 3a | **(a)** | `fwd_net_flow`-оос |
| Decile тест | §7 3b | **(a)** | OH_ratio + fwd_net_flow |
| Hazard, stratified hazard | §7 3c/3c-bis | **(a)/(b)** | `death_age_slot` + censoring туг |
| Sensitivity 3×3 нүд | §7 3d | **(a)** + мөрийн олонлог | 0.05x нь **шинэ мөр** нэмнэ — доорх сануулга |
| Rug-conditioned split | §7 3e | **(e)** | ex-post label, тусдаа query |
| double-cluster SE | §6.3 | **(a)** | `token_mint` + `minute_bucket` |
| Split-half | §6.5 | **(a)** | `token_mint`-ээс гарна |
| Placebo когорт | §6.6 | **(c)** *эргэлзээтэй* | идэвх/curve stage/цагаар таарсан **burst бус** агшин шаардаж магадгүй |
| Walk-forward + 62 slot embargo | §7 Phase 5 | **(a)** | `slot`, `block_time` |
| Expectancy × latency scenario | §7 Phase 7 | **(c)** | `fwd_net_ret`-ээс |
| Expectancy × curve depth | §7 Phase 7 | **(a)** | x-ээр bucket |
| q мэдрэмж (0.5/1/2/5 SOL) | §7 Phase 7 | **(a)** | x ба V-ээс локал бодогдоно, шинэ багана шаардахгүй |
| Exit fill бодит vs тэгш хэмтэй | §7 Phase 7 | **(c)** | exit траектор |
| Holdout | §6.1, Phase 7 | **(a)** | `token_created_at` → split |
| Phase 4-ийн 4 feature бүлэг | §7 Phase 4 | **(c)+(e)** | эзэмшлийн Gini/HHI, санхүүжилтийн graph, wash trading, dev түүх — **burst мөрөнд БАГТАХГҮЙ** |

### Гол хамаарал — exit дүрмийн эргэлт

`fwd_net_ret` (§4.2-ийн "гол эдийн засгийн label") нь §5.1-ийн exit дүрмээр бодогддог. Тэр дүрмийн параметрүүд — `net_flow_3slot < 0` хэр хугацаанд, насны хязгаар `A` — нь **§7 3c/3c-bis-ийн hazard муруйн гаралт**. Өөрөөр хэлбэл:

> Burst мөрөнд `fwd_net_ret`-ийг тогтмол багана болгож бичих нь **Phase 3 хараахан гаргаж амжаагүй дүрмийг урьдчилан хөлдөөнө.**

Хоёр л зам: (1) траектор гаргаж, дүрмийг дараа локал хэрэглэх, эсвэл (2) Phase 3-ын дараа **хоёр дахь extract** ажиллуулах. Аль нь ч тоо биш — шийдвэр, чинийх. Доорх хэмжилт хоёуланд нь үнийн шошго тавьж байна.

### Threshold-ийн мөрийн олонлог (§3d)

`0.05x` босго нь `0.10x`-ийн **дэд олонлог биш** — сессиэлэлт бүр өөр болно, тиймээс шинэ burst мөр гарна. Хэмжсэн: одоогийн мөрүүдийн 951 (6.7%) нь `0.20x`-ыг ч давсан. `0.05x`-ийн бүрэн олонлогийг гаргах нь тусдаа query эсвэл union шаардана — энэ прототипт **хийгээгүй**, мөрийн өсөлт хэмжигдээгүй.

---

## Алхам 2 — Нэр дэвшигч schema (49 багана)

*Юуг ч хаяагүй. **Э** = эргэлзээтэй.*

| # | Багана | Тип | Тодорхойлолт | Spec |
|---|---|---|---|---|
| 1 | `token_mint` | varchar | токен | §2.3 |
| 2 | `slot` | bigint | дараалал | §2.4 |
| 3 | `tx_index` | int | slot доторх | §2.4 |
| 4 | `ix_index` | int | tx доторх (outer·64+inner) | decisions.md |
| 5 | `block_time` | timestamp | цаг | §2.3 |
| 6 | `event_seq` | bigint | токен доторх дугаар | — |
| 7 | `token_created_at` | timestamp | launch | §2.2 |
| 8 | `age_min` | double | нас минутаар | burst inventory |
| 9 | `minute_bucket` | timestamp | double-cluster ба f10/f11-ийн join түлхүүр | §6.3, §3 |
| 10 | `mayhem` | boolean | event дээрх туг | §2.2 |
| 11 | `mayhem_at_launch` | boolean | launch дээрх туг | §2.2 |
| 12 | `x0_lam` | bigint | токений x₀ | §1.1 |
| 13 | `y0_units` | bigint | токений y₀ | §1.1 |
| 14 | `trigger_wallet` | varchar | **Э** — Phase 6-ийн cluster-д магадгүй | §3 f12 |
| 15 | `trigger_is_buy` | boolean | **Э** | — |
| 16 | `trigger_sol` | double | **Э** | — |
| 17 | `trigger_tokens` | double | **Э** | — |
| 18 | `net_flow_3slot` | double | exit/hazard суурь | §4.3, §5.1 |
| 19–21 | `net_flow_5slot/12slot/25slot` | double | f1 | §3 |
| 22 | `accel` | double | f2 | §3 |
| 23 | `n_buyers_12slot` | bigint | f3 | §3 |
| 24 | `depth_x` | double | f4 | §3 |
| 25 | `curve_progress` | double | f5 | §3 |
| 26 | `burst_age_slot` | int | f6, burst дээр 0 | §3 |
| 27 | `oh` | double | §1.2 | §3 f7 |
| 28 | `oh_ratio` | double | **үндсэн feature** | §3 f7 |
| 29 | `oh_conc` | double | f7b | §3 f7b |
| 30 | `oh_n_wallets` | bigint | хангасан wallet-ийн тоо | §1.2 |
| 31 | `size_cv_25slot` | double | f8 | §3 |
| 32 | `round_frac_25slot` | double | f9 | §3 |
| 33 | `n_trades_25slot` | bigint | **Э** — f8/f9-ийн хуваарь | §3 |
| 34–35 | `qual_005`, `qual_020` | boolean | §3d-ийн нүд (сессиэлэлтгүй) | §7 3d |
| 36–38 | `fwd_net_flow_5slot/12slot/37slot` | double | §4.2 | §4.2 |
| 39–41 | `x_at_plus5/12/37` | double | `fwd_price_ret`-ийн суурь | §4.2 |
| 42–46 | `v_latency_1/2/3/7/8slot` | double | §5-ийн V, L1–L3 | §5 |
| 47 | `death_age_slot` | bigint | hazard | §4.3, §7 3c |
| 48 | `hazard_censored` | boolean | censoring туг | §7 3c |
| 49 | `nf3_traj_75` | array(double) | **Э** — absorbing биш бол л хэрэгтэй | §4.3 |

**Schema-д ОРООГҮЙ, өөр эх сурвалж шаардах:** f10/f11 (d), rug label (e), Phase 4-ийн 4 feature бүлэг, Phase 6-ийн санхүүжилтийн graph, `fwd_net_ret` (exit дүрэм тогтоогдоогүй), placebo когортын burst бус агшнууд.

---

## Алхам 3 — Хэмжилт (1 өдрийн cohort)

| | |
|---|---|
| Burst мөр | **14,300** |
| Багана | **49** |
| Result set | 14,787,306 B |
| **Мөрийн өргөн** | **1,034.1 B/мөр** |
| Execution credit | **3.405** (usage_delta 3.41 — тэнцсэн) |
| Хугацаа | 33s wall / **29.2s Dune** |

### Хамгийн өргөн баганууд

Хоёр вариантыг тусад нь ажиллуулж салгасан (хэмжсэн, тооцоолоогүй):

| # | Багана | Өргөн | Хувь |
|---|---|---|---|
| 1 | **`nf3_traj_75`** (array) | **612.4 B/мөр** | **59.2%** |
| 2 | `token_mint` (base58 44) | ~43.9 B | 4.2% |
| 3 | `trigger_wallet` (base58 44) | ~43.9 B | 4.2% |
| 4–6 | `block_time`, `token_created_at`, `minute_bucket` | ~27 B тус бүр *(типээс гаргасан, тусад нь хэмжээгүй)* | ~7.8% |
| — | бусад 43 багана | нийт ~256 B, дунджаар ~6 B | ~24.7% |

Хэмжсэн вариантууд: 49 багана **1,034.1** → trajectory-г хассан **421.7** → хоёр base58-ыг ч хассан **333.9** B/мөр.

### SQL дээр юу унасан, юу workaround шаардсан

| Хэсэг | Үр дүн |
|---|---|
| `count(DISTINCT wallet) OVER (...)` — f3 | **Trino дээр window function-д `DISTINCT` зөвшөөрөгдөхгүй.** Workaround: `cardinality(array_distinct(array_agg(if(is_buy, wallet)) OVER (RANGE 12 PRECEDING ...)))`. Ажилласан, NULL 0 мөр. |
| Яг DECIMAL-аар OH | `DECIMAL(p1,s1) × DECIMAL(p2,s2) → DECIMAL(p1+p2, s1+s2)` нь 38 орны хязгаараас хэтрэхэд **analysis шатанд** унана; яг рационал OH ~44 орон шаардана (`docs/phase0_oh_feasibility.md`). Дүн бүхэл bigint, хоёр харьцаа DOUBLE, алдаа хэмжигдсэн 1.6e-15. |
| `stddev_pop` window (f8) | Ажилласан, NULL 0 мөр. |
| Forward `RANGE ... FOLLOWING` (§4.2, §5 V) | Ажилласан. |
| `min(if(nf3<=0, slot)) OVER (ROWS 1 FOLLOWING..UNBOUNDED)` — death age | Ажилласан. censored 78 (0.55%), death_age median **5.48** slot, p90 **20.34** slot. |
| `array_agg(...) OVER (RANGE 1 FOLLOWING AND 75 FOLLOWING)` | Ажилласан **боловч заасан хэлбэрээр биш**: 75 slot дотрын **event тус бүрийг** цуглуулдаг, slot тутмын нэг утга биш. Урт: median **28.3**, **max 788**, NULL 181. 75 утгын тогтмол урттай траектор хүсвэл slot-оор bucket-лах өөр aggregate шаардана — энэ прототипт хийгээгүй. |

---

## Алхам 4 — 90 хоногийн экстраполяци (ажиллуулаагүй)

Масштаб: 1 өдрийн cohort 2,228,204 event → 90 хоногийн universe 198,774,630 event = **89.2 дахин**. Burst мөр: **1,172,640** (доорх баталгаажуулалт).

| Хувилбар | B/мөр | 90д MB | Retrieval | Execution | **Нийт** | Free-сар | 90д хугацаа |
|---|---|---|---|---|---|---|---|
| 49 багана (trajectory-тай) | 1,034.1 | 1,213 | 2,856 | 248–304 | **3,103–3,159** | 1.24–1.26 | **43.4 мин** |
| trajectory-гүй | 421.7 | 495 | 1,165 | 268–324 | **1,432–1,488** | 0.57–0.60 | 21.8 мин |
| trajectory + base58-гүй | 333.9 | 392 | 922 | 377–433 | **1,299–1,355** | 0.52–0.54 | 41.0 мин |

Retrieval нь хэмжсэн 2.355 credit/MB (`docs/phase0_dune_cost_structure.md`). Execution-ий доод хязгаар нь `0.637 + b×Mevents` fit, дээд хязгаар нь өдрийн дүнг 89.2-оор шугаман өсгөсөн.

### Train / holdout салгасан хоёр query

Dev = токен үүссэн `[2026-05-10, 2026-07-12)` = 63 хоног (70%), holdout = `[2026-07-12, 2026-08-08)` = 27 хоног (30%).

| Хувилбар | Dev query | Holdout query | 30 хоногийн хэсэг |
|---|---|---|---|
| 49 багана | **30.4 мин** | 13.0 мин | 14.5 мин |
| trajectory-гүй | 15.2 мин | 6.5 мин | 7.3 мин |
| trajectory + base58-гүй | 28.7 мин | 12.3 мин | 13.7 мин |

Retrieval ба execution credit нь 70/30 харьцаагаар хуваагдана, нийт дүн бараг өөрчлөгдөхгүй (нэг нэмэлт execution overhead л нэмэгдэнэ). Holdout query нь §6.1-ийн дагуу **Phase 7 хүртэл ажиллахгүй**.

### Dune-ийн 30 минутын хязгаар

- **49 багана, бүтэн 90 хоног: 43.4 минут → хязгаараас хэтэрнэ.**
- Dev-ээр салгасан ч 30.4 минут → **хязгаар дээр яг тулна.**
- trajectory-гүй бол 21.8 минут (бүтэн), 15.2 (dev) → багтана.
- 30 хоногийн хэсгээр хуваавал бүх хувилбар багтана (7.3–14.5 минут).

Гурав дахь хувилбар (41.0 мин) нь хоёр дахиас (21.8) **удаан** байгаа нь анхаарал татаж байна — ижил ажил, бага гаралт. Хугацааны хэмжилт нь Dune-ийн тэр үеийн кластерийн ачааллаас хамаарч ганхдаг гэдгийг харуулж байна; тиймээс дээрх хугацааны экстраполяцийг ±2 дахин гэж уншина.

---

## Баталгаажуулалт

### 1,172,640 burst мөр нь N=∞ дээр бодогдсон

`docs/phase0_burst_inventory.md`-ийн "нийт" хүснэгтээс:

| N | bursts_kept (нийт) | × 30 = 90 хоног |
|---|---|---|
| 5 мин | 34,801 | 1,044,030 |
| 15 мин | 36,596 | 1,097,880 |
| 30 мин | 37,194 | 1,115,820 |
| 60 мин | 37,592 | 1,127,760 |
| **∞** | **39,088** | **1,172,640** ← өмнөх экстраполяцийн тоо |

Тиймээс **N=∞ дээр**. N=5 минутын хязгаартай бол 1,044,030 (11.0% бага).

### OH_conc-ийн `nullif`: OH=0 бүхий burst мөр байдаг

1 өдрийн cohort дээр тоолсон:

| | |
|---|---|
| Burst мөр | 14,300 |
| **OH = 0 (хангасан wallet байхгүй)** | **120 (0.84%)** |
| `oh` aggregate мөр байгаа боловч wallet 0 | 0 |

120 мөр нь `oh` CTE-д **мөр үүсгэдэггүй** (GROUP BY нь хоосон бүлэг гаргахгүй) тул `LEFT JOIN` дараа `oh = NULL → coalesce → 0`, харин `oh_conc = oh_top3 / nullif(0, 0)` = **NULL**. Python лавлагаа тэдгээр мөр дээр `oh_conc = 0` гаргана (`src/oh_reference.py`: `if oh > 0 ... else Decimal(0)`).

Тиймээс **зөрүү нь баталгаажсан, арифметикаар тодорхой: 0.84% мөр дээр SQL NULL, Python 0.** Эдгээр мөр дээр parity-г бодит датаар дахин шалгахад тэдгээр токений түүхий event-ийг татах шаардлагатай (өмнөх parity нь 200 токен = 2.18 MB ≈ 5.5 credit); **ажиллуулаагүй**, учир нь зөрүү нь кодын хоёр мөрөөс гарч байгаа нь ил, мөн бюджет тооллогод зориулагдсан.

---

## Хэмжигдээгүй

- `0.05x` босгын бүрэн burst олонлог (мөрийн өсөлт).
- 75 slot тутмын **тогтмол урттай** траектор (одоогийн array нь event тутам, урт 788 хүртэл).
- `fwd_net_ret` — exit дүрмийн параметр Phase 3-аас гарах тул одоо бодогдохгүй.
- Phase 4-ийн feature бүлгүүд, Phase 6-ийн санхүүжилтийн graph, rug label — burst мөрөнд багтахгүй, тусдаа эх сурвалж/query.
- Timestamp баганы өргөнийг тусад нь хэмжээгүй (типээс гаргасан ~27 B).
