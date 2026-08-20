# Trade event-ийн хаягийн талбарууд — schema шалгалт

**Огноо:** 2026-08-20 · **Зарцуулсан: 7.552 / 25 credit** (мөчлөг 744.805 → 752.357)
Царав: 2026-06-06-ны нэг хуваалт; cohort нь тэр өдөр үүссэн SOL-curve mint (22,966).
**Юу ч засаагүй, schema өөрчлөөгүй, extract эхлүүлээгүй.**

---

## 1. SCHEMA

`information_schema.columns` нь Dune дээр **ажиллахгүй** (0 cr):
`Error listing table columns for catalog delta_prod: Unknown type: string`.
Тиймээс нэг мөрийн дээжийн `result_metadata.column_names` / `column_types`-аар авав.

### `pumpdotfun_solana.pump_evt_tradeevent` — 48 багана (0.480 cr)

**Хаягийн шинжтэй талбарууд:**

| багана | тип | утга | extract-д байгаа юу |
|---|---|---|---|
| **`user`** | varchar | арилжигчийн эзэмшигч | **тийм** (`trigger_wallet`) |
| **`evt_tx_signer`** | varchar | **транзакцийг гарын үсэглэсэн хаяг** | **ҮГҮЙ** |
| **`evt_outer_executing_account`** | varchar | гадаад дуудагч програм (CPI чиглүүлэлт) | **ҮГҮЙ** |
| `evt_inner_executing_account` | varchar | дотоод дуудагч програм | үгүй |
| `evt_executing_account` | varchar | гүйцэтгэгч програм | үгүй |
| `creator` | varchar | токен үүсгэгч | үгүй |
| `fee_recipient` | varchar | шимтгэл хүлээн авагч | үгүй |
| **`shareholders`** | **array(varchar)** | хуваалцагчдын хаяг | **ҮГҮЙ** |
| `mint`, `quote_mint` | varchar | токен | тийм |

Бусад: `evt_block_*`, `evt_tx_id`, `evt_tx_index`, `evt_inner/outer_instruction_index`,
`evt_is_inner`, `is_buy`/`isBuy`, `sol_amount`/`solAmount`, `token_amount`/`tokenAmount`,
`virtual_*`/`real_*` нөөц (snake ба camel), `fee`, `fee_basis_points`, `creator_fee`,
`creator_fee_basis_points`, `buyback_fee`, `buyback_fee_basis_points`, `cashback`,
`cashback_fee_basis_points`, `current_sol_volume`, `quote_amount`, `mayhem_mode`,
`track_volume`, `total_claimed_tokens`, `total_unclaimed_tokens`, `last_update_timestamp`,
`timestamp`, `ix_name`.

### `pump_evt_createevent` — 31 багана (0.730 cr)

Хаягийн талбар: **`user`**, **`evt_tx_signer`**, **`creator`**,
**`bonding_curve` / `bondingCurve`**, `token_program`, `quote_mint`, `mint`,
`evt_*_executing_account`.

> `bonding_curve` нь curve-ийн PDA-г **шууд** өгдөг — 4-р хэсэгт модаль эзэмшигчийн
> таамгийн оронд үүнийг ашиглав.

### `pump_evt_completeevent` — 19 багана (0.540 cr)

`user`, `evt_tx_signer`, `bonding_curve` / `bondingCurve`, `mint`, `quote_mint`.

### `pumpdotfun_solana.pump_call_buy` — 48 багана (0.169 cr) — ACCOUNT ЖАГСААЛТ БАЙНА

Instruction-ийн бүтэн account жагсаалт байдаг:

```
account_user                      account_associated_user / account_associatedUser   ← хэрэглэгчийн ATA
account_bonding_curve             account_associated_bonding_curve                    ← curve-ийн ATA
account_creator_vault             account_fee_recipient      account_fee_config
account_global                    account_global_volume_accumulator
account_user_volume_accumulator   account_mint               account_event_authority
account_token_program             account_system_program     account_rent  account_program
call_tx_signer   call_account_arguments   call_inner_instructions   call_log_messages
```

**Эцсийн эзэмшигчийн ATA (`account_associated_user`) ба owner (`account_user`) хоёулаа
байна.** `solana.instruction_calls` тусад нь шалгаагүй — pump.fun-ийн өөрийн call
хүснэгт аль хэдийн ижил мэдээллийг өгч байгаа тул шаардлагагүй болсон.
**ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР** (давхардсан хайлтад төсөв зарцуулаагүй).

---

## 2. `user`-ийн шинж (2026-06-06, 2,307,384 event)

### `user` vs `evt_tx_signer` (0.236 cr)

| | |
|---|---|
| Event | **2,307,384** |
| `user` = `evt_tx_signer` | **1,794,687 (77.78%)** |
| **`user` ≠ `evt_tx_signer`** | **512,697 (22.22%)** |
| Ялгаатай `user` | 98,641 |
| Ялгаатай signer | 98,102 |
| **Бүгд inner instruction** | **2,307,384 (100%)** |
| **CPI-аар чиглүүлэгдсэн** (outer ≠ pump.fun) | **1,471,970 (63.81%)** |
| Ялгаатай гадаад програм | **171** |

### 2б. Нэг транзакцид хоёр `user` — БАЙНА

| | |
|---|---|
| Транзакц | 2,271,793 |
| **>1 ялгаатай `user`-тэй tx** | **12,791 (0.563%)** |
| Үүнээс **ижил mint** дээр | **12,791 (100%)** |

Олон-`user` транзакц бүр ижил mint дээр — өөр өөр токенд хамаарах хоёр арилжаа биш,
**нэг токен дээр нэг транзакцид хоёр өөр `user`**.

### Атрибуцийн түлхүүрийг солих туршилт — ТААМАГ НЯЦААГДАВ (1.188 cr)

Ижил event цувааг `user`-ээр ба `evt_tx_signer`-ээр түлхүүрлэж, (mint, wallet) тутмын
гүйлгээний үлдэгдлийн **минимумыг** тооцов:

| түлхүүр | хос | сөрөг хос | **хувь** | сөрөг нэгж / эзэмшил |
|---|---|---|---|---|
| **`user`** | 525,891 | 16,303 | **3.100%** | **9.4243%** |
| `evt_tx_signer` | 526,573 | 27,960 | **5.310%** | 12.0181% |

> **`evt_tx_signer` нь ДОР атрибуцийн түлхүүр** — сөрөг хосыг 1.71 дахин нэмэгдүүлнэ.
> «`user` буруу, signer зөв» гэсэн таамаг **няцаагдав**.

Тэмдэглэл: энэ нь **нэг өдрийн** цонх (mint-үүд тэр өдөр үүссэн тул buy тал бүрэн,
харин дараагийн өдрүүдийн sell орхигдсон) — 3.100% нь **доод хязгаар**. Бүтэн цонхон
дээрх pipeline-ийн тоо **3.28%** байсан нь нийцэж байна.

### 2а. Сөрөг wallet-ууд — PDA биш, БОТ шинжтэй (1.944 cr)

| | сөрөг болсон wallet | сөрөг болоогүй |
|---|---|---|
| Тоо | **3,501 / 84,842 (4.13%)** | 81,341 |
| Хүрсэн ялгаатай mint p50 | **3.008** | 1.080 |
| p90 | **20.498** | 9.218 |
| max | **10,230** | 3,701 |

PDA бол цөөн токен дээр гарах ёстой; эдгээр нь **эсрэгээрээ** — сөрөг wallet-ууд
энгийн wallet-аас **2.8 дахин олон** токен хүрдэг. **PDA-ийн шинж алга, ботын шинж
байна.**

### ГОЛ ШИНЖ — сөрөг хосын 55.94% нь SELL-ЭЭР ЭХЭЛДЭГ

| | |
|---|---|
| Сөрөг (mint, wallet) хос | **16,303** |
| **Эхний event нь SELL** (өмнө нь buy ОГТ БАЙХГҮЙ) | **9,120** |
| **хувь** | **55.94%** |

Токен үүссэн тэр өдөр, бүрэн event цуваатай байхад л **тал хувь нь худалдан авалтгүй
зарж эхэлдэг**. Олж авалт нь TradeEvent-д **байхгүй**.

### 2в. Хэмжээ

Сөрөг болсон нэгжийн нийлбэр нь эерэг эзэмшлийн **9.4243%** (`user` түлхүүрээр).
Энэ нь ирмэгийн эффект биш — **леджерийн бараг аравны нэг**.

### 2г. Сөрөг wallet-ууд OH-д оролцдоггүй — бүтцээр (0 credit)

`oh` CTE нь `units_a > 0` ба `units_b > 0` шаарддаг; `units_a` нь
`greatest(held_from_buys_approx, 0)`, `units_b` нь `greatest(held, 0)`-оос гардаг тул
**сөрөг үлдэгдэлтэй wallet хоёуланд 0 оноо өгнө** — `oh_a`, `oh_b`, `oh_n_wallets_*`-д
огт орохгүй. Өмнөх даалгаварт `wat`-ийн 4,678 мөр (1.06%) сөрөг байсан нь бүгд
шүүгдсэн гэсэн үг.

> Өөрөөр хэлбэл алдагдсан олж авалт нь OH-г **дутуу** тооцоолуулна (тэр wallet-ийн
> жинхэнэ эзэмшил ба басис алга), **буруу тэмдэгтэй** болгохгүй.

---

## 3. Токен хаанаас ирдэг вэ — хассан хувилбарууд

### `spl_token_transfers` нь энэ cohort-д бараг хоосон (0.381 cr)

06-06-ны cohort mint-үүд дээр, мөн 06-06-нд:

| `action` | мөр | mint | pump.fun outer |
|---|---|---|---|
| `transfer` | **4,305** | 32 | 926 |
| `mint` | 38 | 38 | 38 |
| `burn` | 32 | 5 | 0 |
| **нийт** | **4,375** | | |

Тэр өдөр ижил mint-үүд дээр **2,048,120 арилжааны event** байсан. Өөрөөр хэлбэл
`spl_token_transfers` нь эдгээр токены хөдөлгөөний **~0.2%**-ийг л агуулж байна.
Бидний материалчилсан transfer нь маш нимгэн зүсэм.

### Хассан leg-үүд `user`-тэй таарч байна (0.977 cr)

`createevent.bonding_curve`-ийг curve-ийн PDA болгон авч, pump.fun-ийг outer болгосон
932 leg-ийг тухайн tx+mint-ийн TradeEvent `user`-тэй тулгав:

| | |
|---|---|
| Хассан leg | **932** |
| curve биш тал = TradeEvent `user` | **921 (98.8%)** |
| taarаагүй | **7** |
| аль ч тал curve биш | 2 |
| TradeEvent олдоогүй | 4 |

**Хасалтын дүрэм атрибуцийг эвдээгүй** — хүргэлт нь яг `user` руу очиж байна.

### `shareholders` / claim талбарууд — механизм БИШ (0.907 cr)

| | |
|---|---|
| `shareholders` хоосон биш | **24,709 (1.21%)**, max урт **2** |
| `total_claimed_tokens > 0` | **0** |
| `total_unclaimed_tokens > 0` | **0** |
| `cashback > 0` | 546,962 (26.7%) |
| `mayhem_mode` | 691,038 (33.7%) |

Claim талбарууд бүхэлдээ тэг тул токен тараах суваг **биш**. `shareholders` нь 1.21%
дээр л дүүрдэг бөгөөд хамгийн ихдээ 2 хаягтай.

---

## ДҮГНЭЛТ

### Extract-ийн schema-д нэмэх багана байна уу — БАЙНА, гэхдээ аль нь ч согогийг заагаагүй

| нэр дэвшигч | хэмжсэн байдал | Одоогийн нотолгоо |
|---|---|---|
| **`evt_tx_signer`** | `user`-ээс **22.22%** ялгаатай | Атрибуцийн түлхүүр болгоход **дордуулна** (сөрөг 3.10% → 5.31%) |
| **`evt_outer_executing_account`** | **63.81%** CPI-аар чиглүүлэгдсэн, **171** програм | Чиглүүлэлтийг ялгах цорын ганц талбар; **хэмжигдээгүй** нөлөө |
| `shareholders` | 1.21% дүүрсэн, ≤2 | Токен тараах суваг биш |
| `pump_call_buy.account_associated_user` | ATA ба owner хоёулаа байна | Өөр хүснэгт, **join шаардана** |

**Зардал (retrieval давамгайлдаг, 2.13 cr/MB, мөрийн өргөн 1,301.2 B):**

| нэмэх багана | мөрийн өргөн | 9 хоногийн хэсэг | dev 6 хэсэг |
|---|---|---|---|
| `evt_tx_signer` (~44 B base58) | +3.4% | +8.8 cr | **+53 cr** |
| `evt_outer_executing_account` (~44 B) | +3.4% | +8.8 cr | **+53 cr** |
| хоёулаа | +6.8% | +17.6 cr | **+106 cr** |

### Тогтоогдсон зүйл

1. **`user` нь одоогийн хамгийн сайн эзэмшигчийн түлхүүр.** Хоёр дахь нэр дэвшигч
   (`evt_tx_signer`) хэмжигдээд **дордуулсан**.
2. **Сөрөг үлдэгдлийн шалтгаан нь атрибуцийн буруу талбар БИШ.** Сөрөг хосын
   **55.94%** нь худалдан авалт огт байхгүйгээр зарж эхэлдэг — олж авалт нь
   TradeEvent-д ч, `spl_token_transfers`-т ч (энэ cohort-д тэр хүснэгт хөдөлгөөний
   ~0.2%-ийг л агуулдаг), pump.fun-ийн claim/shareholder талбарт ч **байхгүй**.
3. **Сөрөг wallet-ууд PDA биш, бот шинжтэй** (mint p50 3.0 vs 1.08, max 10,230).
4. **Сөрөг wallet-ууд OH-д огт оролцдоггүй** (`units > 0` шүүлт) — алдагдсан олж
   авалт нь OH-г **дутуу** үнэлүүлнэ, буруу тэмдэгтэй болгохгүй.

### Хэмжигдээгүй хэвээр

Токен яг ямар замаар wallet руу очдог. Хассан хувилбарууд: TradeEvent (бүрэн, KILL
хаалтаар батлагдсан), материалчилсан transfer (99.43% хамааралгүй), pump.fun leg-ийн
хасалт (98.8% нь `user`-т таарсан), claim/shareholder талбар (тэг). **Дөрөв дэх
механизм байна** — Dune-ийн `spl_token_transfers` нь энэ cohort-ийн хөдөлгөөний
~0.2%-ийг л агуулж байгаа нь хамгийн хүчтэй сэжиг, гэхдээ **шалтгааныг
тогтоогоогүй**.

## `pytest -q`

```
x....................................................................... [ 32%]
........................................................................ [ 64%]
........................................................................ [ 96%]
........                                                                 [100%]
223 passed, 1 xfailed in 1.79s
```
