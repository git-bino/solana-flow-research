# Phase 0 — Extract, хэсэг 1 (dev chunk 01)

**Огноо:** 2026-08-18 · SQL: `sql/extract_dev.sql` (ажилласан query бүтнээр) · Гаралт: `data/extract/dev_chunk01.parquet`
**Зогссон:** хэсэг 1 дуусмагц. Хэсэг 2 рүү ороогүй.

## Цонх (өөрчлөгдөөгүй)

```
launch  [2026-05-10 00:00 UTC, 2026-05-19 00:00 UTC)   9 хоног
event   [2026-05-10 00:00 UTC, 2026-08-15 23:59 UTC)  97 хоног
quote   SOL (§2.2)   ·   насны таслалт БАЙХГҮЙ (N = ∞)
шүүлт   идэвх / эзлэхүүн / наслалт / migration — БАЙХГҮЙ
```

## Эхний ажиллуулалт 0 мөр буцаасан — олдвор

`quote_mint` нь **2026-05-21-ээс өмнө 100% NULL**. Хэсэг 1-ийн launch цонх бүхэлдээ тэр мужид байгаа тул §2.2-ийн SOL-шүүлт бүх токеныг хассан.

| Огноо | createevent | quote NULL | quote = SOL |
|---|---|---|---|
| 2026-05-10 | 26,455 | **26,455** | 0 |
| 2026-05-14 | 29,805 | **29,805** | 0 |
| 2026-05-18 | 29,940 | **29,940** | 0 |
| 2026-05-25 | 28,993 | 0 | 28,655 |

**Зөвхөн `quote_mint` өртсөн.** `sol_amount`, `virtual_sol_reserves`, `fee`, `mayhem_mode` бүгд 2026-05-10 хүртэл NULL-гүй; v1 camelCase мөр 0 → May нь ижил program version, арифметик нь зөв ажиллах байсан.

Нотолгоо: `quote_mint` анх **2026-05-21**-нд гарч ирдэг ба **SOL бус quote мөн яг тэр өдөр** анх гарна (05-01..06-05 мужид 35,489,758 quote-той мөрөөс 1,173,435 нь SOL бус). Multi-quote дэмжлэг 05-21-нд нэвтэрсэнтэй нийцэж байгаа боловч "Dune-ийн decoder тэр өдөр шинэчлэгдсэн" гэдгээс энэ дата ялгаж чадахгүй.

**Шийдвэр (судалгааны удирдагч, 2026-08-18): NULL = SOL, §2.2-ийн 90 хоног хэвээр.** Хоёр талын (create ба trade) шүүлтэд хэрэглэсэн.

## Ажиллуулахын өмнөх тооцоо vs бодит

| | Тооцоо | ×3 марж | Босго | Бодит |
|---|---|---|---|---|
| Execution credit | ~63 | 190 | 700 ✓ | **41.94** (33% хямд) |
| Dune хугацаа | ~3.3 мин | 10 мин | 25 мин ✓ | **1.5 мин** |
| Burst мөр | 117–130k | | | **133,877** |
| Мөрийн өргөн | 1,062.5 B | | | **1,660.5 B (+56%)** |

> **Өргөний алдаа — шалтгаан.** Өмнөх бүх хэмжилт **нэг** траектортойгоор хийгдсэн (`nf3_traj_75_excl_pre`-г хассан), харин §2.3-ийн schema **хоёуланг** шаарддаг. Зөрүү бүхэлдээ тэр хоёр дахь 75-элемент массивынх. Иймд retrieval нь төсөөлснөөс ~1.8 дахин үнэтэй болсон.

      burst rows        133,877        tokens 92,206
      result set        222,307,888 B = 222.3 MB   width 1,660.5 B/row
      parquet on disk   81.2 MB (zstd, 37% of result set)
      execution         41.939 cr   Dune 90.9s   wall 95.8s
      export            440.00 cr   6 requests   47.6s   = 1.979 cr/MB
      TOTAL             481.94 cr      credits after 857.46, remaining 1642.55
    
      vs pre-run estimate: execution 63 -> 41.9 (33% cheaper), time 3.3min -> 1.5min, rows 117-130k -> 134k
      WIDTH MISS: projected 1,062.5 B/row, actual 1,660.5 (+56%) —

**Файл:** `data/extract/dev_chunk01.parquet` — 81.2 MB (zstd), result set-ийн 37%. `data/extract/` нь `.gitignore`-т аль хэдийн багтсан (`data/*`), нэмэлт өөрчлөлт шаардаагүй. `data/holdout/` **хоосон хэвээр**.

## Sanity — зөвхөн бүтцийн

Outcome-ийн тархалт (fwd_net_flow, oh_ratio, death_age-ийн квантиль/decile/hazard) **гаргаагүй** — тэдгээр нь Phase 3-ынх.

| Шалгалт | Үр дүн |
|---|---|
| `traj_len = 75` бүх мөр дээр | **True** (distinct: [75]) |
| Хоёр траекторын элементийн тоо | incl_pre [75], excl_pre [75] |
| `oh ≥ 0` | **True** (min 0) |
| `0 ≤ oh_conc ≤ 1` | **True** |
| `oh_ratio ≥ 0` | **True** |
| NULL-тай багана | **3 / 58** — `death_age_slot` 671 (0.50%), `death_age_incl` 9 (0.01%), `death_age_excl` 5 (0.00%) = censored burst |
| Ялгаатай `token_mint` | **92,206** |
| launch_time муж | 2026-05-10 00:00:12 … 2026-05-18 23:59:56 |
| Бүх launch цонхонд багтсан | **True** |
| Holdout `[2026-07-12, 2026-08-08)`-тай огтлолцол | **0 мөр** |
| `launch_window_guard` (query доторх assert) | **[0]** — guard давсан |
| Давхардсан `(token_mint, slot, tx_index, ix_index)` | **0** |
| burst `block_time` муж | 2026-05-10 00:00:12 … 2026-08-15 21:35:27 |
| token_age муж | 0.00 … 96.2 хоног (N = ∞ тул таслалтгүй) |

### Launch өдрөөр burst тоо (зөвхөн дата дутуу эсэхийг харах)

| Launch өдөр | Burst | Токен |
|---|---|---|
| 2026-05-10 | 11,965 | 8,355 |
| 2026-05-11 | 17,576 | 12,517 |
| 2026-05-12 | 17,468 | 12,163 |
| 2026-05-13 | 15,174 | 10,066 |
| 2026-05-14 | 16,087 | 11,034 |
| 2026-05-15 | 14,371 | 9,977 |
| 2026-05-16 | 13,233 | 8,921 |
| 2026-05-17 | 12,889 | 8,740 |
| 2026-05-18 | 15,114 | 10,433 |

min / median / max = 11,965 / 15,114 / 17,576, max/min = **1.47**. Огцом уналт байхгүй — дата дутуугүй.

=== REMAINING 6 DEV CHUNKS (not run) ===
  Export is ~constant per chunk: bursts cluster in the first minutes of a
  token's life, so a shorter event tail removes few rows. Execution scales
  with the event window (partition scan).

| chunk | launch window | event days | exec cr | export cr | total | cumulative |
|---|---|---|---|---|---|---|
| 2 | 05-19..05-28 | 88 | 38.0 | 440 | 478 | 478 ✓ |
| 3 | 05-28..06-06 | 79 | 34.2 | 440 | 474 | 952 ✓ |
| 4 | 06-06..06-15 | 70 | 30.3 | 440 | 470 | 1,422 ✓ |
| 5 | 06-15..06-24 | 61 | 26.4 | 440 | 466 | 1,889 ✗ |
| 6 | 06-24..07-03 | 52 | 22.5 | 440 | 462 | 2,351 ✗ |
| 7 | 07-03..07-12 | 43 | 18.6 | 440 | 459 | 2,810 ✗ |

  remaining budget 1,642.55 cr  ->  **3 of 6** further dev chunks fit this cycle
  all 6 would need 2,810 cr; short by 1,167
  full dev (7 chunks) actual+projected: 3,292 cr
  earlier projection for all 90 days was 2,650-3,570 cr — understated because
  of the one-trajectory width; on measured numbers dev alone is ~3,292.

=== HOLDOUT (next cycle, not run) ===
| chunk | launch window | event days | exec cr | export cr | total |
|---|---|---|---|---|---|
| H1 | 07-12..07-21 | 34 | 14.7 | 440 | 455 |
| H2 | 07-21..07-30 | 25 | 10.8 | 440 | 451 |
| H3 | 07-30..08-08 | 16 | 6.9 | 440 | 447 |

  holdout total ~1,352 cr over 3 chunks of 9 days.
  (The brief said 4 chunks; 27 days at the dev chunk size of 9 gives 3.
   At 7-day chunks it is 4, costing ~1,803 cr.)

  billing period resets 2026-08-31 with 2,500 credits.
