# Audit bundle — Phase 0 and Phase 3a

Solana pump.fun bonding-curve flow-continuation study. This bundle is
self-contained: it carries the pre-registration, every decision record, every
measurement log, the full source, and the git history needed to date them.

Snapshot taken 2026-08-19. Repository state: commit at the tip of `main` as
listed last in `git_log.txt`.

Not included, by instruction: parquet extracts and the ClickHouse data
directory (size); `data/holdout/` (the sealed test set, empty until Phase 7);
API keys, credentials and `.env` (the Dune key is read from the environment or a
gitignored `.env`, never from source).

## Navigation

| File | What it is |
|---|---|
| `spec.md` | The pre-registration, v1.3. Sections referenced throughout as §n. |
| `decisions.md` | Every research decision, dated. Maintained by the research lead. |
| `test_log.md` | §6.7 log: one row per look at data, with cell, source and result. |
| `git_log.txt` | Full commit history, oldest first, `%H %ad %s` with ISO dates. |
| `git_log_decisions.txt` | Commit history of `decisions.md` alone, oldest first. |
| `10_numbers.md` | One page of headline numbers with § references. No commentary. |

### `docs/` — reports, one per measurement or build step

| File | What it is |
|---|---|
| `phase0_prompt.md` | The original Phase 0 execution brief. |
| `phase0_size_estimate.md` | First universe sizing; y₀ and x₀ read from createevent. |
| `phase0_measurements.md` | Early Dune measurements. |
| `phase0_bigquery_dryrun.md` | BigQuery dry-run costs. |
| `phase0_ordering_probe.md` | Ordering-key counts on BigQuery. |
| `phase0_log_path_probe.md` | Whether `log_messages` can carry TradeEvent. |
| `phase0_burst_inventory.md` | Burst counts by age × mayhem. |
| `phase0_dune_cost_structure.md` | Measured Dune cost function. |
| `phase0_oh_feasibility.md` | Proof that f7/OH is expressible in Dune SQL. |
| `phase0_extract_schema.md` | Full column inventory for the extract. |
| `phase0_test_suite.md` | The §8.2 requirement-8 test suite and its findings. |
| `phase0_window_audit.md` | Audit of all 35 window clauses; f3/f8/f9 fixes. |
| `phase0_extract_run.md` | Every extract chunk: windows, costs, sanity, extrapolation. |
| `phase0_quote_mint_verify.md` | Verification that NULL `quote_mint` means SOL. |
| `phase0_quote_filter_source.md` | `createevent.virtual_sol_reserves` as the quote classifier. |
| `phase0_schema_reduction.md` | The excl_pre trajectory reduction to two scalars. |
| `phase0_kill_gate.md` | §7 checks 1a/1b/1c across four launch windows. |
| `phase0_k_source.md` | Which `k` the code uses in `P(t)`, traced line by line. |
| `phase0_clickhouse_load.md` | The load into `flow.burst` and its asserts. |
| `phase3a_baseline_power.md` | §7 Phase 3a: baseline distribution and power analysis. |

### `sql/`

| File | What it is |
|---|---|
| `extract_dev.sql` | Extract, chunk 1. The base query all later chunks derive from. |
| `extract_chunk02.sql` … `extract_chunk06.sql` | Chunks 2–6; differ from chunk 1 only in window literals. |
| `phase0_kill_gate.sql` | The §7 1a/1b/1c aggregate query, one window per execution. |
| `clickhouse_burst.sql` | DDL for `flow.burst`. |
| `extract_schema_probe.sql` | Column-inventory probe that preceded the extract. |
| `oh_prototype.sql` | OH/OH_ratio feasibility prototype. |
| `burst_inventory.sql` | Burst counts by age × mayhem. |
| `cost_structure_probe.sql` | Dune cost-function measurement. |
| `quote_mint_verify.sql` | NULL-quote verification. |
| `quote_filter_source.sql` | Declared-reserve quote classifier. |
| `ordering_probe.sql`, `log_path_probe.sql` | BigQuery probes. |
| `query_ids.json` | Dune saved-query ids: which query produced which data. |

### `src/`

| File | What it is |
|---|---|
| `config.py` | Paths and constants. No credentials. |
| `ingest_dune.py` | Dune API client, cost logging, execution and paging. |
| `curve.py` | Integer bonding-curve helpers. |
| `oh_reference.py` | Independent Python reference for OH, OH_ratio, OH_conc, bursts, death age. |
| `features_reference.py` | Python reference for f1–f9 and the §4.2 forward labels. |
| `extract_schema.py` | The canonical Arrow schema and `load_chunk()`. |
| `load_clickhouse.py` | Table creation, load and post-load asserts. |
| `phase3a_baseline.py` | Phase 3a: distribution, clusters, two-way cluster bootstrap. |
| `stats.py` | Shared statistics helpers. |
| `validate_phase0.py` | Phase 0 validation entry point. |

### `tests/`

| File | What it is |
|---|---|
| `synthetic.py` | Parameterised synthetic event generator and three perturbations. |
| `test_leakage.py` | Features blind to the future; forward labels required to move. |
| `test_cost_basis.py` | §1.2 cost basis. |
| `test_curve.py` | Curve arithmetic. |
| `test_burst.py` | §4.1 burst detection. |
| `test_slot_ordering.py` | Slot ordering and window boundaries. |
| `test_label_boundary.py` | §4.2 row-level label boundary. |
| `test_parity.py` | SQL ↔ Python parity on cached real data. |
| `verify_canon_schema.py` | Proof that the canonical cast changes no value. |
| `conftest.py` | pytest configuration. |
