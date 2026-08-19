# Дахин extract-ийн дизайныг хаах хэмжилт

**Огноо:** 2026-08-19 · SQL: `sql/redesign_probe.sql` · **Зөвхөн aggregate, мөр экспортлоогүй**
**Зарцуулсан: 24.838 credit** (бюджет ≤ 250) · **Шийдвэр гаргаагүй**
**Төлөв: ДУУСААГҮЙ** — Dune-ийн гүйцэтгэл хоригдсон, доор.

## Гүйцэтгэлийн төлөв

| Хэсэг | Төлөв | Зардал |
|---|---|---|
| **A1** SPL transfer хүснэгт байгаа эсэх | **ДУУССАН** | ~0.5 |
| **A2** transfer-ийн тархалт | **АЖИЛЛААГҮЙ** — тооцоо × 3 > 120, доор | 0.617 (калибр) |
| **B1** balance хүснэгт байгаа эсэх | **ДУУССАН** | (A1-д багтсан) |
| **B2** агшин бүрийн эзэмшил гарах эсэх | **ДУУССАН** (метадатагаар) | 0 |
| **C** түүхий `(outer, inner)` | **ДУУССАН** | **8.755** |
| **D** KILL цонх 3, 5 | **УНАСАН** — Dune-ийн нөөцийн хязгаар | **14.424** (үр дүнгүй) |
| **E** mayhem reconciliation | **АЖИЛЛААГҮЙ** — хоригдсон | 0 |
| **F** quote × version кросс-таб | **АЖИЛЛААГҮЙ** — хоригдсон | 0 |
| | **НИЙТ** | **24.838** |

### Хоёр хориг

**1. Datapoint хязгаар — гүйцэтгэл бүрмөсөн зогссон.**

```
POST /query/8378270/execute -> 402:
  "This api request would exceed your configured datapoint limit per billing
   cycle. Please visit your subscription settings on dune.com and adjust your
   limits to perform this request."
```

`POST /api/v1/usage` нь **дууссан Free мөчлөгийг** харуулсаар байна —
`credits_used = 2500 / credits_included = 2500`, дараагийн мөчлөг 2026-08-31-нд
`credits_included = 0`. Analyst-ийн 4,000 энэ endpoint дээр **огт тусаагүй**.
Тиймээс (а) цаашид query ажиллахгүй, (б) `usage`-аар зардал хэмжих боломжгүй —
энэ тайлангийн бүх зардал **гүйцэтгэл тутмын `execution_cost_credits`**-ээс
тооцогдсон.

**2. Нөөцийн хязгаар — D унасан.**

```
QUERY_STATE_FAILED after 14.424 credits:
  "Query execution has exceeded the user defined maximum amount of resources"
```

`sql/phase0_kill_gate.sql`-ийн **яг тэр query** нь 2026-08-18-нд `performance =
medium` дээр цонх 2, 4, 6-д амжилттай ажилласан (26.99 / 21.53 / 18.67 cr).
Цонх 3 нь үлдсэн хамгийн урт event цонхтой (80 хоног). Кодыг өөрчлөөгүй.

---

## A. SPL TRANSFER

### A1 — байна

| Хүснэгт | Юу |
|---|---|
| `tokens_solana.spl_token_transfers` | Цэгцлэгдсэн SPL transfer, **21 багана** |
| `tokens_solana.spl_token_2022_transfers` | Token-2022 хувилбар |
| `tokens_solana.transfers` | Нэгтгэсэн (олон хөрөнгө) |
| `spl_token_solana.spl_token_call_transfer` | Түүхий instruction call |
| `spl_token_solana.spl_token_call_transferchecked` | Түүхий instruction call |

`tokens_solana.spl_token_transfers`-ийн багана:

```
block_time · action · amount · from_token_account · to_token_account
token_mint_address · symbol · amount_display · amount_usd
from_owner · to_owner · token_version · tx_id · tx_signer
outer_executing_account · block_date · block_slot · tx_index
outer_instruction_index · inner_instruction_index · unique_instruction_key
```

**Partition түлхүүр:** `block_date` (pump.fun-ийн хүснэгттэй ижил).
**Онцлох:** энд `outer_instruction_index` ба `inner_instruction_index` нь
**түүхийгээрээ** байна, мөн `from_owner` / `to_owner` нь **эзэмшигчийн** хаяг
(token account биш) — ledger-т шууд нийлүүлэхэд тохирно.

**Хэмжээ (хэмжсэн, 2026-06-10 нэг өдөр):**

| | |
|---|---|
| Transfer мөр | **97,574,430** |
| үүнээс `action = 'transfer'` | 95,981,741 (98.37%) |
| Ялгаатай mint | 68,989 |
| Ялгаатай `outer_executing_account` | 1,525 |
| `inner_instruction_index` NULL | 4,341,587 (4.45%) |
| `inner` max · `outer` max | 59 · 27 |
| Зардал | **0.617 credit / өдөр** |

### A2 — АЖИЛЛААГҮЙ, тооцоо хаалтыг давсан

Chunk 4-ийн event цонх нь **71 хоног** тул scan ≈ 71 × 97.6M ≈ **6.9 тэрбум мөр**.
Хэмжсэн ханшаар 71 × 0.617 ≈ **44 credit**, mint-ийн join-ийн нэмэлттэй **~66**.
**66 × 3 = 198 > 120** → урьдчилж бүртгэсэн дүрмээр **ЗОГСООД асуув**.

**DEX-ийн дотоод transfer-ийг хасах арга** (query бичигдсэн, ажиллаагүй):
swap-ийн token хөдөлгөөнийг AMM/router **програм** дуудсан байдаг тул
`outer_executing_account`-оор ялгана; pump.fun-ийн өөрийн програмыг
(`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) нэрээр нь хасна. Нэг өдөрт
ялгаатай 1,525 outer program байгаа тул энэ ялгаварлалт бодитой.

---

## B. TOKEN BALANCE

### B1 — байна

| Хүснэгт | Багана | Мөн чанар |
|---|---|---|
| `solana_utils.daily_balances` | `day, month, address, sol_balance, token_mint_address, token_balance, token_balance_owner, block_time, block_slot, unique_address_key, updated_at` | **ӨДРИЙН** snapshot |
| `solana_utils.latest_balances` | `address, block_time, block_slot, sol_balance, token_balance, token_mint_address, token_balance_owner, updated_at` | зөвхөн **хамгийн сүүлийн** төлөв |
| `solana_utils.token_accounts` | `address, address_prefix, token_mint_address, token_balance_owner, account_type` | account → owner зураглал |

### B2 — агшин бүрийн эзэмшил ГАРАХГҮЙ

`daily_balances`-ийн мөчлөг нь `day` — өдөрт нэг snapshot (`block_slot` нь тухайн
snapshot-ийн slot). Burst нь slot-ийн нарийвчлалтай тул **burst-ийн агшинд бүх
holder-ийн балансыг энэ хүснэгтээс шууд гаргах боломжгүй**: өдрийн эхний
snapshot дээр тухайн өдрийн доторх бүх transfer ба trade-ийг давхар тавьж
дахин барих шаардлагатай — өөрөөр хэлбэл ledger-ийг арилгахгүй, зөвхөн
**эхлэлийн цэгийг** өгнө.

`latest_balances` нь түүхэн агшин өгөхгүй.

> **Cost basis энэ замаар ГАРАХГҮЙ.** Баланс нь **хэдэн ширхэг** эзэмшиж байгааг
> өгнө, **ямар үнээр** орсныг өгөхгүй. §1.2-ийн `cb(w) = Σ SOL_in / Σ tokens_received`
> нь арилжааны түүх шаарддаг тул balance-ийн зам нь ledger-ийг **орлохгүй**,
> хамгийн сайндаа түүнийг **шалгах** хэрэгсэл болно.

Зардал тооцоолоогүй: B2-ийн хариу нь метадатагаар шийдэгдсэн тул query
шаардлагагүй болсон.

---

## C. `ix_index`-ийн ТҮҮХИЙ (outer, inner) — АУДИТЫН БЛОКЛОГЧ 2 ХААГДЛАА

Цонх: launch [2026-06-06, 2026-06-15), event 2026-08-15 хүртэл, x₀ = 30e9.
**19,088,528 event.** Зардал **8.755 credit**, 28.8s.

| Хэмжигдэхүүн | Утга |
|---|---|
| `inner` max | **51** |
| **`inner ≥ 64` байх мөр** | **0** |
| `inner` p50 · p99 | 5.06 · 15.17 |
| `outer` max · p99 | **18** · 7 |
| `inner` NULL | **0** |
| `outer` NULL | **0** |
| Ялгаатай `(mint, slot, tx_index, outer, inner)` | **19,088,528** |
| Ялгаатай `(mint, slot, tx_index, outer*64+inner)` | **19,088,528** |
| **Packed түлхүүрийн collision** | **0** |
| Нэгээс олон мөртэй packed түлхүүр | **0** |

**Энэ цонхон дээр packing нь мэдээлэл алдагдуулаагүй.** `inner` нь 64-ийн
хязгаараас хол доогуур (max 51), NULL байхгүй, түүхий хос ба savласан утга хоёр
**яг ижил** тооны ялгаатай түлхүүр өгч байна. Collision байхгүй тул
оношлогооны дээж шаардлагагүй.

Хамрах хүрээний хязгаар: энэ бол **нэг 9 хоногийн launch цонх**. `inner` max нь
51 буюу 64-т ойрхон тул өөр цонхонд давах магадлалыг энэ хэмжилт үгүйсгэхгүй.

---

## D. KILL хаалганы цонх 3 ба 5 — УНАСАН

Цонх 3 нь **14.424 credit** зарцуулаад `QUERY_STATE_FAILED` болов:
*"Query execution has exceeded the user defined maximum amount of resources"*.
Цонх 5 хүртэл хүрээгүй.

Query нь `sql/phase0_kill_gate.sql`-ээс **зөвхөн хоёр огнооны литералаар**
ялгаатай бөгөөд тэр query 2026-08-18-нд цонх 2, 4, 6-д `performance = medium`
дээр амжилттай ажилласан (26.99 / 21.53 / 18.67 cr, 44.6 / 44.7 / 134.6s).

Цонх 3 нь үлдсэн хамгийн урт event цонхтой (**80 хоног** vs 71 ба 53), мөн
2026-08-18-нд хамгийн удаан ажилласан (193.2s) — гэвч тэр үед амжилттай дууссан.
Ялгаа нь query-д биш, гүйцэтгэлийн орчинд байна. **Шалтгааныг хэмжээгүй.**

Тиймээс KILL хаалганы хамрах хүрээ **өөрчлөгдөөгүй хэвээр**: цонх 1 (эшлэл),
2, 4, 6 PASS; **цонх 3 ба 5 хэмжигдээгүй**.

---

## E ба F — АЖИЛЛААГҮЙ

Хоёуланг **нэг pass**-аар үйлчлэх query бичсэн (`sql/redesign_probe.sql`), учир
нь хоёулаа dev цонхны бүх createevent + тэдгээрийн trade-ийн нэг удаагийн
уншилт дээр тогтоно. Тооцоо: ~115M event × 0.31 cr/M ≈ **36 credit**
(×3 = 108 < 120 ✓). Datapoint хязгаараас болж **гүйцэтгэгдээгүй**.

F-ийн query нь **x₀-ийн шүүлтгүй** — completeness-ийг хэмжих ёстой тул
30e9-ээс өөр бүх утгыг гаргана.

---

## Зардлын нэгтгэл

| # | Юу | credit |
|---|---|---|
| 1–2 | `SHOW SCHEMAS` ×2 | 0.783 |
| 3–8 | `SHOW TABLES` ×6 | 0.140 |
| 9–12 | `DESCRIBE` ×4 | 0.119 |
| 13 | A2 калибр (1 өдөр transfers) | 0.617 |
| 14 | **C** | **8.755** |
| 15 | **D цонх 3 (УНАСАН)** | **14.424** |
| | **НИЙТ** | **24.838** |

Бюджет ≤ 250 → **225.162 ашиглагдаагүй**, гэвч Dune гүйцэтгэл хоригдсон тул
одоогоор зарцуулах боломжгүй.

Хоёр дэд бүтцийн саад:
- **Private query-ийн дээд хязгаарт** хүрсэн (30 private query) — бүх probe
  нэг дахин ашиглагдах saved query-гээр (`8378270`) ажилласан.
- `usage` endpoint нь Free мөчлөгийг харуулсаар — зардлын хэмжилт
  `execution_cost_credits`-т шилжсэн.
