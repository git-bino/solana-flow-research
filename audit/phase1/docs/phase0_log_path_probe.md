# Phase 0 — `Transactions.log_messages` замын шалгалт

**Огноо:** 2026-08-17 · project `solana-flow-505812` · BigQuery Sandbox (1 TiB/сар)
**SQL:** `sql/log_path_probe.sql` (ажиллуулсан бүх query)
**Зөвхөн тоолол.** Anchor decoder бичээгүй — payload-ийн эхний 8 байт (discriminator) ба уртыг л шалгахаар кодлосон.

## Дүгнэлт нэг мөрөөр

> **`log_messages` багана байгаа, гэхдээ дата агуулаагүй.** Транзакц бүр яг **нэг** элементтэй массивтай, тэр элемент нь **хоосон мөр** (`max_element_chars = 0`). 18 сарын турших 4 өдөр дээр ижил. Тиймээс A–E, G, H нь **хэмжигдэх боломжгүй** — оролт хоосон учраас тэг гарч байна, "олдсонгүй" гэсэн үр дүн биш.
>
> **F нь log-оос хамаардаггүй тул хэмжигдсэн, эерэг гарсан:** `Transactions.index` нь блок дотор давхардалгүй.

## Алхам 0 — Schema (`INFORMATION_SCHEMA`, үнэгүй)

```
block_slot               INT64
block_hash               STRING
block_timestamp          TIMESTAMP
recent_block_hash        STRING
signature                STRING
index                    INT64            <- блок доторх транзакцийн дугаар
fee                      NUMERIC
status                   STRING
err                      STRING
compute_units_consumed   NUMERIC
accounts                 ARRAY<STRUCT<pubkey STRING, signer BOOL, writable BOOL>>
log_messages             ARRAY<STRING>    <- байгаа, тип зөв
balance_changes          ARRAY<STRUCT<account STRING, before NUMERIC, after NUMERIC>>
pre_token_balances       ARRAY<STRUCT<account_index INT64, mint STRING, owner STRING, amount BIGNUMERIC, decimals INT64>>
post_token_balances      ARRAY<STRUCT<account_index INT64, mint STRING, owner STRING, amount BIGNUMERIC, decimals INT64>>
```

`COLUMN_FIELD_PATHS`-аар nested бүх зам шалгасан (16 зам): `accounts.*`, `balance_changes.*`, `pre_token_balances.*`, `post_token_balances.*`.

**Inner instruction-ийн nested бүтэц БАЙХГҮЙ.** `Transactions` табл дээр instruction-ийн бүтэц ямар ч хэлбэрээр байхгүй — тиймээс "log-оос дээр зам" гэж хайсан зүйл олдсонгүй. `Instructions` табл нь outer-only (parent_index 100% NULL), `Transactions` нь instruction-гүй → **inner instruction нь энэ dataset-д ямар ч хүснэгтэд байхгүй.**

**Тэмдэглэл (шаардаагүй ч анхаарал татсан):** `balance_changes` (SOL-ийн дельта) ба `pre/post_token_balances` (mint + owner + amount) нь арилжааны **дүнг** decode хийхгүйгээр гаргаж чадах бүтэц. Гэхдээ тэд `virtual_sol_reserves`/`virtual_token_reserves`-ыг өгөхгүй — §2.3-ийн `x_post` нь тэднээс уншигдахгүй. Тоо гаргаагүй, зөвхөн бүтэц байгааг тэмдэглэв.

## Алхам 1 — dry_run

| Query | dry_run | Босго |
|---|---|---|
| Q1 (A–H, pump-filter log_messages дээр) | **7,121,911,732 B = 6.63 GiB** | Хүлээлт ~25 GiB, ЗОГС > 60 GiB → **давсан** |

6.63 GiB нь хүлээлтээс 3.7 дахин бага. Шалтгаан: `docs/phase0_bigquery_dryrun.md`-ийн 24.47 GiB/өдөр гэсэн тоо нь **98 өдрийн дундаж** (2.3415 TiB / 98). 2026-06-02-ын partition нь дунджаас хамаагүй жижиг — өөрөөр хэлбэл **partition-ийн хэмжээ өдрөөс өдөрт 3–4 дахин хэлбэлздэг**, нэг өдрөөр 98 өдрийг тооцоолвол дүнг доогуур харуулна.

## Алхам 2 — Бодит query-ийн үр дүн

### A–E, G, H: хэмжигдэх боломжгүй (оролт хоосон)

Q1 бүх багана дээр тэг буцаасан:

| Хэмжигдэхүүн | Үр дүн |
|---|---|
| A. pump.fun program_id агуулсан транзакц | **0** |
| A. ялгаатай блок · self-CPI-тай транзакц | 0 · 0 |
| B. `Program data:` мөртэй транзакц · нийт мөр | **0** · **0** |
| C. TradeEvent discriminator (`bddb7fd34ee661ee`) payload | **0** |
| C. CreateEvent · CompleteEvent · бүх payload | 0 · 0 · 0 |
| D. `Log truncated` агуулсан транзакц | **0** |
| E. Таслагдсан блок, тархалт | хэмжигдээгүй (D = 0) |
| G. Жишээ log массив | хоосон |
| H. Payload уртын тархалт | хоосон |

**C-ийн Dune-тэй харьцуулалт:** 2026-06-02-т Dune дээр **2,419,632** арилжааны event (SOL 2,262,987 + USDC 156,645). BigQuery-ийн log замаас **0** → **0.000%**.

Тэгүүд нь "pump.fun байхгүй" гэсэн үг биш. Q1-ийн шүүлт нь `EXISTS (... UNNEST(log_messages) ... STRPOS(l, program_id) > 0)` — массив дотор хэрэглэгдэх мөр байхгүй бол шүүлт бүх транзакцийг хаядаг. Тиймээс дараагийн хоёр диагностик ажиллуулсан.

### Диагностик 1 — `log_messages` бөглөгдсөн үү? (2026-06-02, бүх транзакц)

| | |
|---|---|
| Нийт транзакц | **273,919,682** |
| `log_messages IS NULL` | 0 |
| Хоосон массив (`ARRAY_LENGTH = 0`) | 0 |
| Массив байгаа (`ARRAY_LENGTH > 0`) | **273,919,682 (100%)** |
| Массивын урт: p50 · max | **1 · 1** |
| Нийт log мөр | 273,919,682 (= транзакцийн тоо, мөр тутам яг 1) |
| `invoke` агуулсан транзакц | **0** |
| `Program ` агуулсан транзакц | **0** |

Мөр тутам яг нэг элемент, тэр нь Solana-ийн log-ийн ямар ч хэлбэрийг агуулаагүй.

### Диагностик 2 — Нэг өдрийн онцлог юу, эсвэл багана хэзээ ч бөглөгддөггүй юу?

| Өдөр | Транзакц | Массив урт p50/max | NULL элемент | **Хоосон мөр элемент** | **Элементийн max тэмдэгт** | Нийт тэмдэгт |
|---|---|---|---|---|---|---|
| 2025-02-01 | 398,949,369 | 1 / 1 | 0 | **398,949,369** | **0** | **0** |
| 2026-06-02 | 273,919,682 | 1 / 1 | 0 | **273,919,682** | **0** | **0** |
| 2026-07-15 | 291,516,731 | 1 / 1 | 0 | **291,516,731** | **0** | **0** |
| 2026-08-14 | 308,983,172 | 1 / 1 | 0 | **308,983,172** | **0** | **0** |

18 сарын турш, 1.27 тэрбум транзакц дээр: элемент бүр хоосон мөр, нийт тэмдэгтийн тоо **яг тэг**. `log_messages` нь схемд байгаа боловч **энэ public dataset-д хэзээ ч бөглөгдөөгүй**.

### F — `Transactions.index` (log-гүйгээр хэмжигдсэн, 2026-06-02 бүх транзакц)

| | |
|---|---|
| Мөр | **273,919,682** |
| Ялгаатай `(block_slot, index)` хос | **273,919,682** |
| Нэг хос дахь max мөр | **1** |
| Блок | 216,935 |
| `index` хүрээ | **0 … 13,084** |
| `min(index) = 0` байх блок | **216,935 / 216,935 (100%)** |
| `max−min+1 = COUNT(DISTINCT index)` байх блок | **216,935 / 216,935 (100%)** |
| `index` давтагдсан блок | **0** |
| Блок дахь транзакц: p50 · max | 1,204 · 13,085 |

**`Transactions.index` нь блок дотор давхардалгүй, 0-ээс эхэлдэг, тасралтгүй** — өөрөөр хэлбэл §2.4-ийн `tx_index` яг энэ. `Instructions`-ийн `index`-тэй эрс өөр: тэр нь транзакц дотор дугаарлагддаг (0..21, блокуудын 76%-д давтагдана — `docs/phase0_ordering_probe.md`).

## Scan-ийн хуримтлагдсан бүртгэл

dry_run ба бодит scan **бүх query дээр яг тэнцсэн** (өмнөх удаатай ижил — cluster pruning нэмэлт хямдрал өгөөгүй):

| Query | Processed | Billed | Квотын % |
|---|---|---|---|
| ordering_probe Q1 | 110,853,022 | 111,149,056 | 0.0101% |
| ordering_probe Q2 | 110,853,022 | 111,149,056 | 0.0101% |
| ordering_probe Q3 | 255,119,255 | 255,852,544 | 0.0233% |
| **log_path Q1 (A–H)** | **7,121,911,732** | 7,121,928,192 | **0.648%** |
| log_path Q2 (диагностик 1) | 2,739,196,820 | 2,739,929,088 | 0.249% |
| log_path Q3 (диагностик 2, 4 өдөр) | 12,733,689,540 | 12,733,906,944 | 1.158% |
| log_path Q4 (F) | 6,574,072,368 | 6,574,571,520 | 0.598% |
| Алхам 0 (`INFORMATION_SCHEMA` × 2) | 0 | 0 | 0% |
| **Нийт (миний бүх query)** | **29,645,695,759 B = 27.61 GiB** | 29,648,486,400 B | **2.697%** |

Сарын үлдэгдэл: **~972 GiB (97.3%)**. (Дээрх дүнд console-оос ажиллуулсан 2 × 10 MiB орсонгүй.)

## Юу тоологдож, юу тоологдоогүй

**Тоологдсон:** `log_messages` нь 1.27 тэрбум транзакц дээр хоосон (4 өдөр, 18 сар); `Transactions`-д inner instruction-ийн бүтэц байхгүй; `Transactions.index` нь блок дотор unique, 0-based, тасралтгүй; log замын TradeEvent хамрах хүрээ = Dune-ийн 2,419,632-ийн **0.000%**.

**Тоологдоогүй:** `balance_changes` / `pre/post_token_balances`-аас арилжааны дүнг гаргах боломжийн хэмжээ (бүтэц байгааг л тэмдэглэсэн, тоо гаргаагүй); өөр provider-ууд; Yellowstone gRPC (spec §2.1-ийн 3-р эх сурвалж).

Шийдвэр гаргаагүй, decoder бичээгүй.
