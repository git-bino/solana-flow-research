# Extract v2 — баганын бүрэн жагсаалт

**Огноо:** 2026-08-19 · `sql/extract_v2.sql` · `src/extract_schema.py` (`CANON_V2`)
**АЖИЛЛУУЛААГҮЙ** — Dune-ийн API 402 буцааж байна. Зардал, хугацаа, мөрийн өргөн
**тооцоолоогүй**: transfer join хэзээ ч хэмжигдээгүй (probe A2 хоригдсон) тул ямар ч
тоо зохиомол байх байсан.

## Нэгтгэл

| | |
|---|---|
| v1 багана | **60** |
| v2 багана | **80** |
| Хасагдсан | `ix_index` (packed) — засвар 2 |
| Нэрлэгдсэн | `oh`, `oh_ratio`, `oh_conc`, `oh_n_wallets` → `_a` / `_b` хос (засвар 3) |
| Шинэ | 25 |
| Түлхүүр | `(token_mint, slot, tx_index, outer_ix_index, inner_ix_index)` |

## Багана тутам

| # | Багана | Тип | Тодорхойлолт | Spec | Шалтгаан |
|---|---|---|---|---|---|
| 1 | `token_mint` | string | Токены mint хаяг | §2.3 | хэвээр |
| 2 | `slot` | int64 | Trigger-ийн slot | §2.3 | хэвээр |
| 3 | `tx_index` | int64 | Транзакцийн индекс slot дотор | §2.3 | хэвээр |
| 4 | `outer_ix_index` | int64 | Түүхий outer instruction индекс | §2.3 | **шинэ** — засвар 2, packing хасагдсан |
| 5 | `inner_ix_index` | int64 | Түүхий inner instruction индекс | §2.3 | **шинэ** — засвар 2 |
| 6 | `event_seq` | int64 | Токен доторх event-ийн дугаар | §2.3 | **өөрчлөгдсөн** — эрэмбэ (slot, tx, outer, inner) |
| 7 | `block_time` | string | Trigger-ийн цаг (UTC) | §2.3 | **өөрчлөгдсөн** — UTC ил зааж |
| 8 | `minute_bucket` | string | block_time-ийн минут (UTC) | §6.3 | **өөрчлөгдсөн** — UTC ил зааж |
| 9 | `token_created_at` | string | createevent-ийн цаг (UTC) | §2.2 | **өөрчлөгдсөн** — UTC ил зааж |
| 10 | `age_min` | string | Launch-аас хойших минут | §2.2 | хэвээр |
| 11 | `quote_mint` | string ·nullable | Quote хөрөнгө (stratum) | §2.2 | хэвээр |
| 12 | `mayhem` | bool | Trigger мөрийн mayhem туг | §2.2 | хэвээр |
| 13 | `mayhem_at_launch` | bool | createevent-ийн mayhem туг | §2.2 | хэвээр |
| 14 | `x0_lam` | int64 | Зарлагдсан x0 (lamport) | §1.1 | хэвээр |
| 15 | `y0_units` | int64 | Зарлагдсан y0 (base unit) | §1.1 | хэвээр |
| 16 | `depth_x` | double | x(t), SOL — f4 | §3 f4 | хэвээр |
| 17 | `y_t` | double | **y(t), токен** | §1.1 | **шинэ** — засвар 6 |
| 18 | `curve_progress` | double | (x−30)/85 — f5 | §3 f5 | хэвээр |
| 19 | `p_t` | double | **P(t) = x/y** | §1.1 (v1.4) | **шинэ** — засвар 6, үндсэн үнэ |
| 20 | `p_launch` | double | x²/(x0·y0) — хуучин үнэ | §1.1 | **шинэ** — mayhem-ийн зөрүү хэмжигдэхээр үлдээв |
| 21 | `trigger_wallet` | string | Trigger хийсэн хаяг | §2.3 | хэвээр |
| 22 | `trigger_is_buy` | bool | Trigger buy эсэх | §2.3 | хэвээр |
| 23 | `trigger_sol` | double | Trigger-ийн SOL (net) | §2.3 | хэвээр |
| 24 | `trigger_tokens` | double | Trigger-ийн токен | §2.3 | хэвээр |
| 25 | `trigger_fee_sol` | double | fee + creator_fee, SOL | §1.1 | **шинэ** — засвар 5-ын оролт |
| 26 | `net_flow_3slot` | double | f1, 3 slot | §3 f1 | хэвээр |
| 27 | `net_flow_5slot` | double | f1, 5 slot | §3 f1 | хэвээр |
| 28 | `net_flow_12slot` | double | f1, 12 slot | §3 f1 | хэвээр |
| 29 | `net_flow_25slot` | double | f1, 25 slot | §3 f1 | хэвээр |
| 30 | `accel` | double ·nullable | f2 = nf5/(nf25/5) | §3 f2 | хэвээр |
| 31 | `n_buyers_12slot` | int64 | f3 | §3 f3 | **өөрчлөгдсөн** — түлхүүр tuple болсон |
| 32 | `n_trades_25slot` | int64 | 25 slot доторх арилжаа | §3 | хэвээр |
| 33 | `size_cv_25slot` | double ·nullable | f8 | §3 f8 | хэвээр |
| 34 | `round_frac_25slot` | double ·nullable | f9 | §3 f9 | хэвээр |
| 35 | `burst_age_slot` | int64 | Токены эхний арилжаанаас хойших slot | §2.3 | хэвээр |
| 36 | `oh_a` | double | **OH, хувилбар (а)**: transfer-ээр ирсэн токен ОРОХГҮЙ | §1.2 | **шинэ** — засвар 3 |
| 37 | `oh_b` | double | **OH, хувилбар (б)**: илгээгчийн basis өвлөнө | §1.2 | **шинэ** — засвар 3 |
| 38 | `oh_ratio_a` | double | oh_a / x(t) | §1.2 | **шинэ** — засвар 3 |
| 39 | `oh_ratio_b` | double | oh_b / x(t) | §1.2 | **шинэ** — засвар 3 |
| 40 | `oh_conc_a` | double | Дээд 3-ын хувь, (а) | §1.2 | **шинэ** — засвар 3 |
| 41 | `oh_conc_b` | double | Дээд 3-ын хувь, (б) | §1.2 | **шинэ** — засвар 3 |
| 42 | `oh_n_wallets_a` | int64 | Хувь нэмэр оруулсан хаяг, (а) | §1.2 | **шинэ** — засвар 3 |
| 43 | `oh_n_wallets_b` | int64 | Хувь нэмэр оруулсан хаяг, (б) | §1.2 | **шинэ** — засвар 3 |
| 44 | `cb_reset_gross` | double ·nullable | **Үндсэн basis**: reset + шимтгэлтэй | §1.2 | **шинэ** — засвар 4 + 5 |
| 45 | `cb_net` | double ·nullable | Basis, шимтгэлгүй (хуучин) | §1.2 | **шинэ** — засвар 5-ын лавлагаа |
| 46 | `cb_legacy` | double ·nullable | Basis, reset-гүй бүх түүх (хуучин) | §1.2 | **шинэ** — засвар 4-ийн лавлагаа |
| 47 | `held_from_buys` | double | Зөвхөн худалдаж авсан үлдэгдэл | §1.2 | **шинэ** — засвар 3, хувилбар (а)-д хэрэгтэй |
| 48 | `held_from_transfers` | double | Transfer-ээр ирсэн үлдэгдэл | §1.2 | **шинэ** — засвар 3 |
| 49 | `fwd_net_flow_5slot` | double | Label, (s, s+5] | §4.2 | **өөрчлөгдсөн** — засвар 1, slot хил сэргээгдсэн |
| 50 | `fwd_net_flow_12slot` | double | Label, (s, s+12] — үндсэн | §4.2 | **өөрчлөгдсөн** — засвар 1 |
| 51 | `fwd_net_flow_37slot` | double | Label, (s, s+37] | §4.2 | **өөрчлөгдсөн** — засвар 1 |
| 52 | `x_end_slot` | double | slot s-ийн ТӨГСГӨЛИЙН x | §4.2 | **шинэ** — засвар 1, үнийн суурь |
| 53 | `y_end_slot` | double | slot s-ийн ТӨГСГӨЛИЙН y | §4.2 | **шинэ** — засвар 1 + 6 |
| 54 | `x_at_plus5` | double | x, slot ≤ s+5 | §4.2 | хэвээр |
| 55 | `x_at_plus12` | double | x, slot ≤ s+12 | §4.2 | хэвээр |
| 56 | `x_at_plus37` | double | x, slot ≤ s+37 | §4.2 | хэвээр |
| 57 | `y_at_plus5` | double | y, slot ≤ s+5 | §4.2 | **шинэ** — засвар 6 |
| 58 | `y_at_plus12` | double | y, slot ≤ s+12 | §4.2 | **шинэ** — засвар 6 |
| 59 | `y_at_plus37` | double | y, slot ≤ s+37 | §4.2 | **шинэ** — засвар 6 |
| 60 | `fwd_price_ret_12slot` | double ·nullable | P(s+12)/P(end of s) − 1 | §4.2 | **шинэ** — засвар 1 + 6 |
| 61 | `v_latency_1slot` | double | V, L1 | §5 | хэвээр |
| 62 | `v_latency_2slot` | double | V, L2 доод | §5 | хэвээр |
| 63 | `v_latency_3slot` | double | V, L2 дээд | §5 | хэвээр |
| 64 | `v_latency_7slot` | double | V, L3 доод | §5 | хэвээр |
| 65 | `v_latency_8slot` | double | V, L3 дээд | §5 | хэвээр |
| 66 | `nf3_traj_75_incl_pre` | list⟨double⟩ | 75 slot-ын nf3 траектор | §4.3 | хэвээр |
| 67 | `nf3_excl_pre_1` | double | excl_pre, a=1 | §4.3 | хэвээр |
| 68 | `nf3_excl_pre_2` | double | excl_pre, a=2 | §4.3 | хэвээр |
| 69 | `traj_len` | int64 | Траекторын урт (=75) | §4.3 | хэвээр |
| 70 | `nonzero_incl` | int64 | Тэг биш элемент, incl | §4.3 | хэвээр |
| 71 | `nonzero_excl` | int64 | Тэг биш элемент, excl | §4.3 | хэвээр |
| 72 | `death_age_incl` | int64 ·nullable | Үхлийн нас, incl | §4.3 | хэвээр |
| 73 | `death_age_excl` | int64 ·nullable | Үхлийн нас, excl | §4.3 | хэвээр |
| 74 | `death_age_slot` | int64 ·nullable | Үхлийн нас, slot-оор | §4.3 | хэвээр |
| 75 | `censored_incl` | bool | incl цензурлагдсан эсэх | §4.3 | хэвээр |
| 76 | `censored_excl` | bool | excl цензурлагдсан эсэх | §4.3 | хэвээр |
| 77 | `hazard_censored` | bool | hazard цензурлагдсан эсэх | §3c | хэвээр |
| 78 | `qual_005` | bool | 0.05x босгыг хангасан эсэх | §3d | хэвээр |
| 79 | `qual_020` | bool | 0.20x босгыг хангасан эсэх | §3d | хэвээр |
| 80 | `launch_window_guard` | int64 | Guard CTE-ийн тогтмол 0 | §2.4 | хэвээр |

## Долоон засвар, хаана хэрэгжсэн

| # | Засвар | SQL дахь байрлал |
|---|---|---|
| 1 | Label-ийн хил `(s, s+τ]`; үнийн суурь = slot s-ийн төгсгөл | `flows` CTE — `RANGE BETWEEN 1 FOLLOWING`, `vsol_end_s` / `vtok_end_s` |
| 2 | Packing хасагдсан, түүхий tuple-ээр эрэмбэлнэ | `ev` (`oix`, `iix`), бүх `ORDER BY`, `f3_same`-ийн tuple харьцуулалт |
| 3 | Transfer-aware ledger, хоёр хувилбар | `xf`, `pos`, `run`, `wstate`, `xf_basis`, `contrib` |
| 4 | Cost basis reset | `segd` (`seg_id`), `wstate`-ийн `seg` window |
| 5 | Buy fee basis-д | `ev.fee_lam`, `creator_fee_lam` → `pos.d_lam_gross` |
| 6 | `y(t)`, `P = x/y` | `ev.vtok`, `p_t`, `p_launch`, `y_at_plus*` |
| 7 | UTC ил зааж | Бүх `TIMESTAMP` литерал |

## Хэмжигдээгүй, таамаглаагүй

- **Transfer join-ийн зардал.** Probe A2 хоригдсон. `tokens_solana.spl_token_transfers`
  нь нэг өдөрт 97,574,430 мөр (0.617 credit) гэж хэмжигдсэн боловч mint-ийн join-той
  71 хоногийн зардлыг **хэмжээгүй**.
- **Query-ийн хугацаа, мөрийн өргөн, нийт credit.** Dune сэргэмэгц хэмжинэ.
- **`INCLUDE_TRANSFERS='false'` үед хуучин ledger-тэй яг таарах эсэх** — Python талд
  `tests/test_extract_v2.py::test_v2_ledger_with_transfers_off_matches_the_v1_inventory`
  баталсан; SQL талд ажиллуулж баталгаажаагүй.

## Мэдэгдэж буй хязгаарлалт — transfer-ийн basis өвлөх гинж

Хувилбар (б) нь хүлээн авагчид илгээгчийн basis-ыг өгнө. Хэрэв B нь A-аас авсан
токеноо C рүү дамжуулбал C юуг өвлөх ёстой вэ?

- **Python (`src/oh_reference.py`)** нь төлөвийг дараалан хөтөлдөг тул **гинжийг бүрэн
  дамжуулна**: B-ийн basis нь өвлөсөн хэсгээ аль хэдийн агуулсан байна.
- **SQL (`xf_basis` CTE)** нь илгээгчийн **зөвхөн худалдаж авсан** түүхээс гарсан
  basis-ыг өгнө — **нэг алхам**. Бүрэн хувилбар нь transfer-ийн граф дээрх тогтмол цэг
  шаардах бөгөөд Trino үүнийг илэрхийлж чадахгүй.

Тиймээс transfer дахин дамжуулагдсан газарт хоёр тал **зөрнө**. Зөрүүний хэмжээ
**хэмжигдээгүй** — үүнд transfer-ийн гинжний давтамжийг мэдэх шаардлагатай, тэр нь
probe A2-той хамт хоригдсон. **ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР** (нэг алхмаар
хязгаарлах); өөр сонголт нь SQL талд хувилбар (б)-г огт хэрэгжүүлэхгүй байх байсан.

## Бусад CLAUDE CODE-ИЙН ШИЙДВЭР

1. **Худалдан авсан токеныг эхэлж хасах.** Sell буюу transfer-out нь `held_from_buys`-ыг
   эхлээд бууруулж, дараа нь transfer-ээр ирсэн хэсгийг хөнддөг. Spec дарааллыг
   заагаагүй; энэ уншилт нь хувилбар (а)-г **консерватив** байлгана — OH-д тооцогдох
   токеныг эхэлж тэтгэнэ.
2. **Үндсэн basis = reset + шимтгэлтэй, үндсэн үнэ = `x/y`.** `cb_net`, `cb_legacy`,
   `p_launch` нь лавлагаа болж үлдэнэ. Transfer-ийн хувилбар дээр **сонголт хийгээгүй** —
   хоёулаа тэнцүү эрхтэй багана.
3. **DEX-ийн leg-ийг хасаагүй, зөвхөн pump.fun-ийнхыг хассан.** Бусад AMM/router-ийн
   дуудсан transfer нь эзэмшигчийн үлдэгдлийг curve-ээс гаргаж байгаа **бодит**
   хөдөлгөөн тул хасвал ledger-ийн харахгүй байгаа inventory-г дутуу үнэлнэ.
