# rsi-exit v0.4.0 freeze manifest

## Release identity

Package: rsi-exit

Version: 0.4.0

Semantic base commit: `06e1468c0f76be13dbb3966707babc7a1d4dd281`

Warning implementation and validation range:

- Phase 1, warning events: PR #8
- Phase 2, warning lifecycle: PR #9
- Phase 3, warning reporting: PR #10
- Phase 4, multi-sample validation: PR #11
- Phase 4.1, warning actionability: PR #12

## Input baseline

Filename: `300308.SZ_v0.2.1_frozen_baseline.zip`

SHA-256: `EA026086B71A0A0CD537ADA177D141DC44DD634B4882C53F341A8605EE906FA5`

The private input remains outside the repository. The v0.4 freeze entry validates
its established identity before reading the original bars.

## Output baseline

Filename: `300308.SZ_v0.4.0_frozen_baseline.zip`

Repository path: `baselines/300308.SZ_v0.4.0_frozen_baseline.zip`

SHA-256: `623EE4EB5892AF4CCDB14DEE0CCD7CBF3CFB9AF12D115D3C6E9D61F1884B4C86`

Two independent generations produced byte-identical archives:

```text
baseline_a.zip  623EE4EB5892AF4CCDB14DEE0CCD7CBF3CFB9AF12D115D3C6E9D61F1884B4C86
baseline_b.zip  623EE4EB5892AF4CCDB14DEE0CCD7CBF3CFB9AF12D115D3C6E9D61F1884B4C86
```

Members, in stable archive order:

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
300308.SZ/warning_events.csv
```

The manifest covers every member except itself with a SHA-256 digest. Members use
stable sorting, timestamp `1980-01-01 00:00:00`, UTF-8, LF, and the established
fixed table/float formatting. The archive excludes charts, reports, data caches,
absolute paths, current time, usernames, and temporary files.

## Environment

Final local verification:

- Python 3.10.4: `284 passed, 1 deselected`; frozen marker `1 passed`;
  historical release check, compile, and build passed
- Python 3.13.14: `284 passed, 1 deselected`; frozen marker `1 passed`;
  historical release check, compile, and build passed

GitHub Actions matrix:

- Python 3.10–3.13: pending Draft PR

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

python -m rsi_exit.freeze_baseline_v04 `
  --source-baseline $source `
  --output outputs/v0.4.0_baseline/baseline_a.zip
python -m rsi_exit.freeze_baseline_v04 `
  --source-baseline $source `
  --output outputs/v0.4.0_baseline/baseline_b.zip

Get-FileHash outputs/v0.4.0_baseline/baseline_a.zip -Algorithm SHA256
Get-FileHash outputs/v0.4.0_baseline/baseline_b.zip -Algorithm SHA256
Get-FileHash baselines/300308.SZ_v0.4.0_frozen_baseline.zip -Algorithm SHA256
```

The v0.3 generator and frozen archive remain independently verifiable with
`python -m rsi_exit.freeze_baseline`.

## Frozen semantics

v0.4.0 freezes:

- `OPENED`, `REFRESHED`, `ESCALATED`, `CLEARED`, and `INVALIDATED`;
- append-only warning history and as-of-date state derivation;
- warning summary and chart reporting;
- Phase 4 and Phase 4.1 committed validation evidence;
- `position_effect=NONE` and an empty `recommended_position_cap` for every event;
- unique `ESCALATED` linkage to an existing formal divergence;
- position effects exclusively in the base-state and formal signal-cap domains.

The event decision is knowable after the decision-date close. Its earliest action
proxy is the next real trading day, but a warning event never creates an action.

## Frozen warning expectations

Full history:

```text
OPENED 7
REFRESHED 9
ESCALATED 3
CLEARED 0
INVALIDATED 4
```

Status as of 2026-07-20:

```text
ACTIVE 0
ESCALATED 3
CLEARED 0
INVALIDATED 4
```

Display-range events:

```text
OPENED 4
REFRESHED 8
ESCALATED 3
CLEARED 0
INVALIDATED 1
```

The archive contains three formal top divergences and three unique matched
formal-warning links. Their existing formal signal-cap sequence remains
`0.7, 0.4, 0.0`; warnings apply no additional cap.

## v0.3 isolation

The v0.3.0 archive remains
`932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52`.
The following v0.4 members are byte-identical to their v0.3 counterparts:

```text
canonical_peaks.csv
cycle_log.csv
daily_features.csv
peaks.csv
rsi_audit.csv
signals.csv
state_log.csv
```

Only the config version snapshot, freeze manifest, added `warning_events.csv`, and
total ZIP SHA differ.

## Position-neutral decision and change control

Warning lifecycle is permanently position-neutral in v0.4.0. `ESCALATED` delegates
position constraints to its linked formal divergence and does not establish a
warning position domain. Based on the Phase 4 and Phase 4.1 evidence, the proposed
Phase 5 warning-position feature is cancelled.

Any future change to this boundary or another frozen business result requires a new
version and must not overwrite the v0.4.0 archive or committed validation artifacts.
This freeze PR does not create a Git tag or GitHub Release.
