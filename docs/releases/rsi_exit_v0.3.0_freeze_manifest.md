# rsi-exit v0.3.0 freeze manifest

## Release identity

Package: rsi-exit

Version: 0.3.0

Semantic base commit: `2010817939f5cf3a039e2a96936513487fb5114f`

Source implementation PR: #5, `fix rsi-exit v0.3 canonical and anchor semantics`.

## Input baseline

Filename: `300308.SZ_v0.2.1_frozen_baseline.zip`

SHA-256: `EA026086B71A0A0CD537ADA177D141DC44DD634B4882C53F341A8605EE906FA5`

This private input is not committed, renamed, recompressed, edited, downloaded again, or
re-adjusted. `rsi_exit.release_check.load_frozen_bars()` validates and reads it.

## Output baseline

Filename: `300308.SZ_v0.3.0_frozen_baseline.zip`

Repository path: `baselines/300308.SZ_v0.3.0_frozen_baseline.zip`

SHA-256: `932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52`

Two independent generations produced the same SHA-256:

```text
baseline_a.zip  932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52
baseline_b.zip  932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52
```

Members, in archive order:

```text
300308.SZ/canonical_peaks.csv
300308.SZ/config_snapshot.yaml
300308.SZ/cycle_log.csv
300308.SZ/daily_features.csv
300308.SZ/freeze_manifest.json
300308.SZ/peaks.csv
300308.SZ/rsi_audit.csv
300308.SZ/signals.csv
300308.SZ/state_log.csv
```

The manifest records SHA-256 for every member except itself. ZIP members are sorted,
stored with timestamp `1980-01-01 00:00:00`, UTF-8 text, LF line endings, fixed table
ordering, sorted JSON keys, and no current time, username, random identifier, cache,
temporary file, or absolute path. The config snapshot excludes data-source and output
locations while retaining every business configuration section used by the analysis.

## Environment

The local release verification was run with:

- Python 3.10.4: `124 passed, 1 deselected`
- Python 3.13.14: `124 passed, 1 deselected`

GitHub Actions runs the same ordinary regression and compile checks on:

- Python 3.10
- Python 3.11
- Python 3.12
- Python 3.13

## Verification commands

PowerShell:

```powershell
$source = "outputs/v0.2.1_baseline/300308.SZ_v0.2.1_frozen_baseline.zip"
$env:RSI_EXIT_FROZEN_BASELINE_PATH = $source

python -m pytest
python -m compileall rsi_exit
python -m build --no-isolation
git diff --check

python -m rsi_exit.release_check --frozen-baseline $source
python -m pytest -m frozen_baseline_required

python -m rsi_exit.freeze_baseline `
  --source-baseline $source `
  --output outputs/v0.3.0_baseline/baseline_a.zip
python -m rsi_exit.freeze_baseline `
  --source-baseline $source `
  --output outputs/v0.3.0_baseline/baseline_b.zip

Get-FileHash outputs/v0.3.0_baseline/baseline_a.zip -Algorithm SHA256
Get-FileHash outputs/v0.3.0_baseline/baseline_b.zip -Algorithm SHA256

python -m rsi_exit.freeze_baseline `
  --source-baseline $source `
  --output baselines/300308.SZ_v0.3.0_frozen_baseline.zip
Get-FileHash baselines/300308.SZ_v0.3.0_frozen_baseline.zip -Algorithm SHA256
```

## Frozen semantics

The v0.3.0 comparison boundary freezes:

- canonical version immutability;
- latest confirmed canonical lineage;
- same-canonical +2.0 activation;
- price relation priority;
- dual RSI divergence validation;
- deep RSI resets;
- 28-day structural gap;
- forming audit-only behavior;
- v0.2.1 position/state rule reuse;
- risk cycle and divergence chain separation.

In particular, a canonical version replay cannot create a second event, a late version of
an old canonical cannot retake the momentum anchor, forming rows never enter the position
system, and an anchor breakout neither resets the risk cycle nor schedules
`APPLY_SIGNAL_CAP`.

## Frozen expected sequence

- `2026-04-23`: `PK0007 v2`; same-canonical `ANCHOR_RSI_BREAKOUT`; momentum-anchor RSI
  `84.396377`.
- `2026-04-30`: `PK0008 v1`; `NON_COMPARABLE_PEAK`; momentum anchor and last structural
  peak remain `PK0007`, while the confirmed canonical lineage advances.
- `2026-05-14`: `PK0008 v2`; same-canonical `ANCHOR_RSI_BREAKOUT`; becomes P0 momentum
  anchor; `divergence_count=0`; `position_eligible=false`; risk cycle remains `CYCLE0009`;
  no `APPLY_SIGNAL_CAP`.
- `2026-05-20`: `INTRADAY_POTENTIAL_RETEST`; `divergence_count=0`;
  `position_eligible=false`.
- `2026-05-28`: `NEW_HIGH_BEARISH_DIVERGENCE`; confirm `2026-05-29`; earliest action
  `2026-06-01`; count `1`; eligible; cap `0.7`.
- `2026-06-04`: `NEW_HIGH_BEARISH_DIVERGENCE`; confirm `2026-06-05`; earliest action
  `2026-06-08`; count `2`; eligible; cap `0.4`.
- `2026-06-18`: `DIVERGENCE_FORMING`; count `2`; ineligible.
- `2026-06-22`: `NEW_HIGH_BEARISH_DIVERGENCE`; confirm `2026-06-23`; earliest action
  `2026-06-24`; count `3`; eligible; cap `0.0`.
- `2026-06-25`: `NON_COMPARABLE_PEAK`; count `3`; ineligible.

`PK0008 v1` remains an immutable historical snapshot after `v2` is created.

## Change control

Any subsequent modification that changes the business results above must increment the
version. It must not overwrite these results under the v0.3.0 identity.

This freeze does not create a Git tag or GitHub Release. Those actions are permitted only
after the freeze PR is merged and must point at the resulting `main` commit.
