# Phase 0 — `P(t)`-ийн `k`-ийн эх сурвалж

**Огноо:** 2026-08-18 · Зөвхөн код унших + локал хэмжилт · **Dune query ажиллуулаагүй** (үлдэгдэл 26.84)
**Шийдвэр гаргаагүй.** Засвар хийгээгүй, дахин extract төлөвлөөгүй.

## Хариулт

> **(а) launch k = createevent-ийн `x₀ · y₀`, токен тутам тогтмол.**

SQL болон Python **хоёулаа ижил (а)-г** ашиглаж байна. `x(t)` нь мөрөөс шууд уншигддаг ч
`k` нь уншигддаггүй — `y(t)` extract-д огт орж ирдэггүй.

---

## 1. SQL — `P(t)` бодогдож буй яг мөрүүд

`P(t)` нь `sql/extract_chunk02.sql` дотор **зөвхөн нэг газар**, OH-ын `contrib` CTE дотор
гарна — нэг удаа утга болж, нэг удаа шүүлт болж. Өөр хаана ч спот үнэ бодогддоггүй
(`grep`-ээр `vsol * vsol` хэлбэр бүхэлдээ 2 удаа, хоёулаа энэ CTE дотор).

### `contrib` CTE, мөр 344–359, бүтнээр

```sql
contrib AS (
    SELECT b.mint, b.seq,
           w.wallet,
           (CAST(w.held_units AS double) / 1e6)
             * ((CAST(b.vsol AS double) * CAST(b.vsol AS double))
                  / (CAST(b.x0_lam AS double) * CAST(b.y0_units AS double) * 1000.0)
                - CAST(w.buy_lam AS double) / (CAST(w.buy_units AS double) * 1000.0)) AS oh_w
    FROM bursts b
    JOIN wstate w
      ON w.mint = b.mint AND w.seq <= b.seq
     AND (w.next_seq IS NULL OR w.next_seq > b.seq)
    WHERE w.held_units > 0 AND w.buy_units > 0
      AND CAST(w.buy_lam AS double) / (CAST(w.buy_units AS double) * 1000.0)
          < (CAST(b.vsol AS double) * CAST(b.vsol AS double))
            / (CAST(b.x0_lam AS double) * CAST(b.y0_units AS double) * 1000.0)
),
```

Тодоор:

```
P(t) = b.vsol² / (b.x0_lam · b.y0_units · 1000.0)
       ^^^^^^     ^^^^^^^^^^^^^^^^^^^^^
       x(t), мөрөөс   k, launch-аас
```

`1000.0` нь нэгжийн хөрвүүлэлт: `vsol` нь lamport (1e9/SOL), `y0_units` нь base unit
(1e6/токен), тиймээс `x²/k` нь lamport/unit гарах ба SOL/токен болгоход 1e9-д хувааж
1e6-аар үржүүлнэ = 1e3-д хуваана. `held_units / 1e6` нь base unit → токен.

### `k`-ийн бүрэлдэхүүн хэсэг тус бүрийн мөшгөлт

| багана | хаанаас | мөр | тогтмол уу |
|---|---|---|---|
| `b.vsol` | `ev.vsol` ← `t.virtual_sol_reserves` (**tradeevent**, мөр тутам) | 70 | **event тутам** |
| `b.x0_lam` | `sel.x0_lam` = `max(virtual_sol_reserves)` (**createevent**) | 34 | **токен тутам тогтмол** |
| `b.y0_units` | `sel.y0_units` = `max(virtual_token_reserves)` (**createevent**) | 35 | **токен тутам тогтмол** |

Дамжуулалтын гинж: `sel` (мөр 32–37, createevent-ийн aggregate)
→ `ev` (мөр 60: `SELECT s.mint, s.created_at, s.x0_lam, s.y0_units, s.mayhem_at_launch, …`)
→ `seqd` → `bursts` → `contrib`. **Дунд нь дахин уншилт, шинэчлэлт байхгүй.**

`depth_x` нь тусдаа зам: `seqd.x_sol = CAST(vsol AS double) / 1e9` (мөр 86) →
`b.x_sol AS depth_x` (мөр 396). Энэ нь **мөрөөс шууд** уншигдсан x(t) — зөв.
`x0_lam`, `y0_units` нь мөн extract-д гарна (мөр 382), гэхдээ launch утгаараа.

**`tradeevent.virtual_token_reserves` буюу `y(t)` нь `ev` CTE-д ОГТ сонгогддоггүй.**
Тиймээс instantaneous k нь query дотор ч, экспортын дараа ч байхгүй.

---

## 2. Python — `src/oh_reference.py`

```python
    def spot_price(self, vsol: int) -> Decimal:
        return (Decimal(vsol) * Decimal(vsol)) / (
            Decimal(self.x0_lam) * Decimal(self.y0_units) * THOUSAND
        )
```

`TokenState` нь токен тутам **нэг удаа** баригдана:

```python
    state = TokenState(ordered[0].x0_lam, ordered[0].y0_units)   # replay_token, мөр 241
```

`Event.x0_lam` / `Event.y0_units`-ийн тайлбар нь өөрөө эх сурвалжийг нэрлэдэг:

```python
    x0_lam: int         # this token's createevent virtual_sol_reserves
    y0_units: int       # this token's createevent virtual_token_reserves
```

`TokenState.apply()` нь `wallets`-ыг л шинэчилдэг — `x0_lam`, `y0_units` **хэзээ ч
өөрчлөгддөггүй**. Модулийн толгойн тайлбар мөн ижлийг бичсэн:
`P(t) = vsol² / (x₀_lamports × y₀_units × 1000)`.

### Дүгнэлт: SQL ба Python ижил `k` ашиглаж байна

Хоёулаа `k = x0_lam · y0_units`, createevent-ээс, токен тутам тогтмол. Томьёо нь тэмдэгт
тэмдэгтээрээ ижил (`vsol²`, `× 1000`).

**Тиймээс parity 88/88 нь энэ талаар ЮУ Ч БАРИХГҮЙ.** Хоёр тал ижил `k`-г ижил байдлаар
буруу ашиглаж байсан ч parity төгс таарна. Энэ нь `tests/test_parity.py`-ийн толгойд
бичигдсэн үлдэгдэл эрсдэл — *"a definition both sides share would survive both"* —
ба §8.2-ийн 8-р шаардлагын "parity дангаараа хуваалцсан алдааг өнгөрөөнө" гэсэн
жишгийн **бодит тохиолдол**. Синтетик тестүүд ч барихгүй: `tests/synthetic.py` нь
`src.curve`-ийн `X0_LAMPORTS`, `Y0_UNITS`-ээр дата үүсгэдэг тул mayhem-ийн
reparameterization-ыг огт загварчилдаггүй (`mayhem_share` нь зөвхөн тугийн хувь).

---

## 3. Локал хэмжилт (Dune хандалтгүй)

### mayhem burst мөр

| хэсэг | burst мөр | mayhem | % |
|---|---|---|---|
| 01_v3 | 133,877 | 7,788 | 5.82 |
| 02 | 108,385 | 5,541 | 5.11 |
| 03 | 107,563 | 8,211 | 7.63 |
| 04 | 94,544 | 10,061 | 10.64 |
| 05 | 109,534 | 10,010 | 9.14 |
| 06 | 113,906 | 9,530 | 8.37 |
| **нийт** | **667,809** | **51,141** | **7.66** |

`mayhem` ба `mayhem_at_launch` нь **667,809 мөрийн бүгд дээр тэнцүү** (зөрүү 0) — энэ
датад mayhem нь launch-ийн шинж чанар, токен дотор тогтмол.

### instantaneous k vs launch k — **локал дээр сэргээгдэхгүй**

Канон schema-ийн 60 баганад `y(t)`-г сэргээх багана **байхгүй**:

| хайсан | байдал |
|---|---|
| `virtual_token_reserves` / `vtok` / `y_t` / `y_units` / `token_reserves` | **алга** |
| `y0_units`, `x0_lam` | байна (launch утга) |
| `depth_x` (= x(t) SOL) | байна |
| `trigger_tokens` | байна (тухайн арилжааны token_amount, y(t) биш) |

`y(t)` байхгүй тул `k(t) = x(t)·y(t)` нь бодогдохгүй, улмаас mayhem мөрүүд дээр
instantaneous k ба launch k-ийн харьцангуй зөрүүг **локал дээр гаргах боломжгүй**.
Таамаглан тооцоолоогүй.

Зөвхөн шууд бус, аль хэдийн хэмжигдсэн заалт бий: KILL хаалганы 1b нь mayhem хосууд
дээр `|Δ(x·y)/(x·y)|` p50 = **0.0743–0.0765**, p99 ≈ **0.46**, max **8.0–8.7**
(`docs/phase0_kill_gate.md`, цонх 4 ба 6). Энэ нь **дараалсан хос тутмын** хөдөлгөөн;
launch-аас хойш хуримтлагдсан хазайлт нь үүнээс хамаагүй том байж болно, гэхдээ
хэмжээгүй.

---

## 4. Spec юу гэж бичсэн

### §1.1 (мөр 48–63) — `k` нь launch-аас

```
x · y = k
x₀ = 30 SOL          (virtual SOL reserve)
k  = x₀ · y₀
```

> x₀, y₀, k нь тогтмол биш. Токен бүрийн createevent-ээс уншина. Эмпирик (81,052 токен):
> y₀ = 1,073,000,000 (base unit 1.073e15), x₀ = 30 SOL.

**Spot үнэ:** `P(x) = x² / k`

→ **Spec нь (а)-г заасан**, бөгөөд `k`-ийн эх сурвалжийг createevent гэж нэрлэсэн.
**Код spec-тэй нийцэж байна.**

### §1.2 (мөр 128) — гэвч дотоод зөрчилтэй

> Cost basis нь бодит SOL/токеноос бодогддог тул virtual reserve-ийн reparameterization
> (mayhem) түүнд нөлөөлөхгүй. **P(t), x(t) шууд уншигдана.** Иймд OH, OH_ratio, slippage
> mayhem токен дээр ч зөв ажиллана.

Энэ тэмдэглэл нь `P(t)` **шууд уншигдана** гэж баталж, түүн дээрээ түшиглэн "mayhem
токен дээр ч зөв" гэсэн дүгнэлт гаргаж байна. Гэвч:

- Кодод `x(t)` **шууд уншигдаж байна** (`b.vsol`), харин `P(t)` **уншигдахгүй, launch
  k-аас бодогдож байна**. §1.2-ийн урьдчилсан нөхцөл кодод биелээгүй.
- `P(t)`-г үнэхээр "шууд унших" гэвэл `P = x(t)/y(t)` (учир нь instantaneous k үед
  `x²/(x·y) = x/y`) — үүнд `y(t)` хэрэгтэй, тэр нь **уншигддаггүй**.
- §1.1-ийн `x · y = k` гэсэн үндэслэл нь mayhem токен дээр биелэхгүй нь KILL хаалганы
  1b-ээр хэмжигдсэн (хос тутам ~7.5%). Өөрөөр хэлбэл §1.1 ба §1.2-ийн тэмдэглэл нь
  mayhem-ийн хувьд **хоорондоо зөрчилдөж байна**, код нь §1.1-ийг дагасан.

### §2.3-ын нэмэлт олдвор — шаардсан багана дутуу

§2.3-ын "Curve state" мөр (spec мөр 184) дараах баганыг шаарддаг:

```
| Curve state | `depth_x` (trigger мөрийн `x_post`), `y`, `k`, `curve_progress`, `P_t` | §1.1, f4, f5 |
```

Канон 60 баганад: `depth_x` ✓, `curve_progress` ✓, харин **`y` алга, `k` алга, `P_t` алга**.
`y` экспортлогдсон байсан бол дээрх 3-р зүйлийн харьцуулалт локал дээр хийгдэх байсан.

---

## Товч дүгнэлт

| асуулт | хариу |
|---|---|
| SQL-ийн `P(t)` ямар k-аар? | **(а)** launch k = `x0_lam · y0_units`, createevent-ээс |
| Python-ийх? | **(а)**, яг ижил томьёо |
| Хоёул ижил k үү? | **Тийм** → parity 88/88 энэ талаар юу ч барихгүй |
| Spec §1.1 юу заасан? | **(а)** — код нийцэж байна |
| Spec §1.2 юу гэсэн? | `P(t)` шууд уншигдана → **кодод биелээгүй**, §1.1-тэй зөрчилдөнө |
| mayhem-ийн хамрах хүрээ | **51,141 / 667,809 burst мөр = 7.66%**, mayhem = mayhem_at_launch (зөрүү 0) |
| instantaneous vs launch k зөрүү | **локал дээр сэргээгдэхгүй** (`y(t)` экспортлогдоогүй) |

Асуултын томьёоллын дагуу: **(а) бол mayhem токенуудын `P(t)`, улмаар `OH`, `OH_ratio`,
`OH_conc` бүгд буруу** — энэ нь 51,141 burst мөрд (7.66%) хамаарна. Хэмжигдсэн зүйл нь
`x·y` хос тутам ~7.5% хөдөлдөг гэдэг; хазайлтын хуримтлагдсан хэмжээ, улмаас OH-д
үзүүлэх бодит нөлөө нь **хэмжигдээгүй**.

Юу хийхийг заагаагүй — шийдвэр судалгааны удирдагчийнх.
