# Phase 0.1 — BigQuery dry_run хэмжилт

**Огноо:** 2026-08-17 · project `solana-flow-505812` · **BigQuery Sandbox** (billing байхгүй, сард 1 TiB үнэгүй)
**Зөвхөн `--dry_run`.** Бодит query ажиллуулаагүй — нэг ч байт scan хийгээгүй, нэг ч төгрөг/credit зарцуулаагүй.
**Цонх:** `block_timestamp >= 2026-05-10` ба `< 2026-08-16` = **98 өдөр** (event-ийн 7 хоногийн сүүл орсон, §2.2 + decisions.md)
**pump.fun program id:** `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` (Dune-ийн `evt_executing_account`-аас баталгаажсан)

## Table-ийн бүтэц (metadata, үнэгүй)

`Instructions` — 1,142,855,562,113 мөр, 853.91 TiB:

```
timePartitioning: {field: block_timestamp, type: DAY, requirePartitionFilter: True}
clustering:       {fields: [program_id]}
```

`Transactions` — 563,992,927,167 мөр, 855.72 TiB:

```
timePartitioning: {field: block_timestamp, type: DAY, requirePartitionFilter: True}
clustering:       {fields: [signature]}
```

**Хоёр зүйл шийдвэрлэх ач холбогдолтой:**

1. `Instructions` нь **`program_id`-аар clustered**. Бидний бүх шүүлт яг тэр баганаар явна.
2. `Transactions` нь **`signature`-аар clustered**, `program_id` байхгүй → транзакцуудыг program-аар хямдхан шүүх боломжгүй.

> **`upper bound` гэдгийн утга.** dry_run нь partition pruning-ийг тооцдог ч **cluster pruning-ийг тооцдоггүй**. Тиймээс `Instructions`-ийн тоонууд нь **дээд хязгаар** — `program_id` clustering-ийн ачаар бодит scan нь мэдэгдэхүйц бага байх магадлалтай (pump.fun нь Solana-ийн бүх instruction-ийн бага хувь). Харин `Transactions`-ийн query-үүд нь **`signature`-аар clustered бөгөөд бид signature-аар шүүхгүй** тул тэдний тоо бодит хэмжээндээ ойр. Энэ асимметр нь доорх Зам 1 ба Зам 2/3-ын зөрүүг бодит байдалд бүр илүү өргөсгөнө.

## Алхам бүрийн dry_run

Бүх query-д `WHERE block_timestamp >= TIMESTAMP '2026-05-10' AND block_timestamp < TIMESTAMP '2026-08-16'` (= `$W`) байна.

### A. Хамгийн бага: мөр тоолох

```sql
SELECT COUNT(*) FROM `bigquery-public-data.crypto_solana_mainnet_us.Instructions`
WHERE $W AND program_id = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
```

**67,627,071,855 B = 63.0 GiB = 0.0615 TiB = сарын үнэгүй 1 TiB-ийн 6.2%** · 0.64 GiB/өдөр

### B. Бүрэн projection (8 багана, `accounts` орсон)

```sql
SELECT block_slot, block_timestamp, tx_signature, index, parent_index, accounts, data, program_id
FROM `...Instructions` WHERE $W AND program_id = '6EF8...'
```

**1,252,453,636,859 B = 1,166.4 GiB = 1.1391 TiB = 113.9%** — сарын үнэгүй хэмжээг **давна** · 11.90 GiB/өдөр

### C. Partition filter-гүй (харьцуулалт)

```sql
SELECT COUNT(*) FROM `...Instructions` WHERE program_id = '6EF8...'
```

**ГҮЙЦЭТГЭГДЭХГҮЙ.** Query шатнаасаа татгалзагдана:

```
Cannot query over table '...Instructions' without a filter over column(s)
'block_timestamp' that can be used for partition elimination
```

`requirePartitionFilter: True` тул "филтергүй" тоо гэж байхгүй — table өөрөө хамгаалагдсан. Энэ нь 853.91 TiB-ийг санамсаргүй scan хийх эрсдэлийг бүтцээрээ хааж байна.

### Багана тус бүрийн зардал (нэмэлт dry_run-ууд)

Baseline = `program_id` + partition filter = 62.98 GiB. Багана нэмэх нэмэлт зардал:

| Багана | Нэмэлт | Baseline-тай нийт |
|---|---|---|
| **`accounts`** (REPEATED STRING) | **925.08 GiB** | 988.07 GiB |
| `tx_signature` | 107.01 GiB | 170.00 GiB |
| `data` | 52.01 GiB | 114.99 GiB |
| `block_slot` | 9.53 GiB | 72.52 GiB |
| `index` | 9.53 GiB | 72.52 GiB |
| `parent_index` | 0.29 GiB | 63.27 GiB |
| `program_id` | 0 (baseline) | 62.98 GiB |

Нийлбэр 1,166.44 GiB = B-ийн хэмжилт 1,166.44 GiB — **яг таарна**, тооцоо нэмэгддэг шинжтэй.

**`accounts` нь бүх зардлын 79% -ийг эзэлж байна.** Түүнийг хасах эсэх нь decode-ын хэрэгцээнээс хамаарна: Anchor-ийн `TradeEvent` payload дотор `mint`, `user` аль хэдийн байдаг тул `accounts` шаардлагагүй байж **магадгүй** — гэхдээ би decode-ыг эхлүүлээгүй тул үүнийг батлаагүй. Тоо л гаргаж байна.

### E. `accounts`-гүй lean projection (7 багана)

```sql
SELECT block_slot, block_timestamp, tx_signature, index, parent_index, data, program_id
FROM `...Instructions` WHERE $W AND program_id = '6EF8...'
```

**259,153,030,538 B = 241.4 GiB = 0.2357 TiB = 23.6%** · 2.46 GiB/өдөр

### F. Хамгийн lean (4 багана)

```sql
SELECT block_slot, index, parent_index, data
FROM `...Instructions` WHERE $W AND program_id = '6EF8...'
```

**144,248,766,114 B = 134.3 GiB = 0.1312 TiB = 13.1%** · 1.37 GiB/өдөр

### G–H. `tx_index` авах зардал (join)

`Instructions`-д **транзакцийн блок доторх дугаар байхгүй**. Байгаа нь `index` (транзакц доторх instruction-ийн дугаар) ба `parent_index`. §2.4-ийн `ORDER BY (token_mint, slot, tx_index, ix_index)`-ийн `tx_index` нь **`Transactions.index`** дотор байна → join шаардлагатай.

**G. Зөвхөн Transactions-ийн join key:**

```sql
SELECT signature, index FROM `...Transactions` WHERE $W
```

**2,886,150,325,954 B = 2,687.9 GiB = 2.6249 TiB = 262.5%** · 27.43 GiB/өдөр

`Transactions`-ийг program-аар шүүх боломжгүй тул 98 өдрийн **бүх** транзакцийн хоёр багана уншигдана.

**H. Бүрэн join:**

```sql
SELECT i.block_slot, i.block_timestamp, i.tx_signature, t.index AS tx_index,
       i.index, i.parent_index, i.data
FROM `...Instructions` i JOIN `...Transactions` t ON i.tx_signature = t.signature
WHERE i.$W AND t.$W AND i.program_id = '6EF8...'
```

**3,145,303,356,492 B = 2,929.3 GiB = 2.8606 TiB = 286.1%** · 29.89 GiB/өдөр

### I. Өөр зам: `Transactions.log_messages`-аас Anchor event унших

```sql
SELECT block_slot, index, log_messages FROM `...Transactions` WHERE $W
```

**2,574,520,893,852 B = 2,397.7 GiB = 2.3415 TiB = 234.2%** · 24.47 GiB/өдөр

Энэ зам нь `tx_index`-ийг үнэгүй өгнө (`Transactions.index`), гэхдээ program-аар шүүх боломжгүй тул сүлжээний **бүх** транзакцийн log уншигдана.

## 98 өдрийн бүрэн extract-ийн нийт тооцоо

| Зам | Юу авна | TiB | Сарын 1 TiB-тэй | Billing байвал ($6.25/TiB) |
|---|---|---|---|---|
| **1. Instructions, leanest (F)** | slot, ix index, parent_index, data | **0.1312** | **13.1%** | $0.82 |
| **1b. Instructions, lean (E)** | + block_timestamp, tx_signature | **0.2357** | **23.6%** | $1.47 |
| 2. Instructions бүрэн (B) | + `accounts` | 1.1391 | 113.9% | $7.12 |
| **3. Join-той, `tx_index`-тэй (H)** | Зам 1b + `Transactions.index` | **2.8606** | **286.1%** | $17.88 |
| 4. log_messages зам (I) | бүх транзакцийн log | 2.3415 | 234.2% | $14.63 |
| (лавлагаа) A — зөвхөн тоолох | — | 0.0615 | 6.2% | $0.38 |

**Sandbox-ийн 1 TiB/сарын дор:**

- Зам 1 / 1b нь **нэг сард багтана**, 76–87% нөөцтэй. Дахин ажиллуулах, туршилт, баталгаажуулалтад орон зай үлдэнэ.
- Зам 3 (`tx_index`-тэй) нь **3 сарын үнэгүй хэмжээ** шаардана, эсвэл 98 өдрийг ~34 өдрийн 3 хэсэг болгож сар дамжуулан татна.
- Зам 2 ба 4 нь нэг сард багтахгүй.

Харьцуулалт: **Dune Free** дээр ижил 98 өдрийн event-level дата нь 691,084 credit = **276 сарын budget** (`docs/phase0_size_estimate.md`). BigQuery-ийн Зам 1b нь **нэг сарын үнэгүй квотын 23.6%**.

## Sandbox-ийн хязгаарлалтууд (тэмдэглэсэн, тойрч гараагүй)

| Хязгаарлалт | Нөлөө |
|---|---|
| Billing байхгүй → 1 TiB/сар давбал query **түгжигдэнэ** (төлбөр нэхэхгүй) | Зам 3-ыг сар дамжуулан хуваах шаардлагатай |
| DML байхгүй | Дүн бүртгэх/шинэчлэх table үүсгэх боломжгүй; decode-ыг локал талд хийнэ |
| Table 60 хоногт устана | Түр table-д хадгалах стратеги ажиллахгүй |
| GCS руу export нь billing шаардаж магадгүй | **Хэмжээгүй.** ~490M мөрийг API-аар татах нь практик биш; extract-ийн бодит хүргэлтийн зам батлагдаагүй хэвээр |

Сүүлийн мөр нь чухал: dry_run нь **уншигдах** байтыг хэлдэг, **гаргах** зам биш. Зам 1b-ийн scan нь 0.24 TiB боловч гарах мөрүүдийг локал машин руу яаж авах нь тусдаа шалгагдаагүй асуудал.

## Хэмжигдээгүй үлдсэн зүйл

**Мөрийн тоо.** `SELECT COUNT(*)` (алхам A) нь **бодит query** бөгөөд 63.0 GiB = сарын квотын 6.2% зарцуулна. Prompt-ийн дагуу бодит scan хийгээгүй — pump.fun-ийн 98 өдрийн instruction мөрийн тоо тодорхойгүй хэвээр. Ажиллуулах эсэхийг чи шийднэ.

Дүнгийн хувьд Dune-ээс мэдэгдэж байгаа зүйл: SOL-quote арилжаа ~2.26M/өдөр. Anchor-ийн self-CPI event хэлбэрийн улмаас арилжаа тутам **хоёр** instruction мөр (үндсэн buy/sell + event CPI) байх магадлалтай тул 98 өдөрт ~440M мөрийн эрэмбэ гарна — **энэ нь тооцоолол, хэмжилт биш.**

## Ажиллуулсан бүх алхам

Бүгд `--dry_run`, нийт **19 dry_run** (A, B, C, D, E, F, G, H, I + 10 багана тус бүрийн). Scan = **0 байт**, зардал = **$0**.
