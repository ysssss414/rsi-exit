# RSI卖点信号识别器 v0.3.0

面向 A 股日线趋势股的 RSI 卖点与持仓去偏系统。它生成可审计的风险约束，不读取成本、盈亏或持仓时间，不自动下单。

v0.3.0 在 v0.2.1 基线上重构顶部背离：引入 structural peak、前峰真实交易日收盘可比区、新高/近高双 RSI 背离、独立 divergence chain 和只审计不入仓位的 forming 事件。AmazingData 仍是唯一在线行情源。

## 当前冻结版本

- Current frozen version: v0.3.0
- Semantic base commit: `2010817939f5cf3a039e2a96936513487fb5114f`
- 冻结规格：[v0.3 顶部背离规格](docs/specs/rsi_exit_v0.3_top_divergence_spec_v0.2.md)
- 冻结清单：[v0.3.0 freeze manifest](docs/releases/rsi_exit_v0.3.0_freeze_manifest.md)
- 私有输入：`300308.SZ_v0.2.1_frozen_baseline.zip`，SHA-256 `EA026086B71A0A0CD537ADA177D141DC44DD634B4882C53F341A8605EE906FA5`
- 冻结输出：`300308.SZ_v0.3.0_frozen_baseline.zip`，SHA-256 `932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52`

发布验收命令：`python -m rsi_exit.release_check --frozen-baseline <输入ZIP路径>`。

## 安装与测试

Python 3.10+：

```powershell
python -m pip install -e ".[test,amazingdata]"
python -m pytest
```

普通测试会排除强制私有冻结验收；若 ZIP 不在工作区，pytest 会明确显示真实冻结回归
未执行。发布冻结前必须运行：

```powershell
python -m rsi_exit.release_check `
  --frozen-baseline outputs/v0.2.1_baseline/300308.SZ_v0.2.1_frozen_baseline.zip
python -m pytest -m frozen_baseline_required
```

AmazingData 凭据仍由既有 `D:/ej/材料/codex/yh` 项目的环境变量或 `.env.local` 读取；本仓库不保存凭据。

## v0.4 Phase 4 多样本描述性验证

固定样本见 `validation/v04_phase4_samples.csv`。验证脚本复用单个 AmazingData
session 和默认配置，生成正常单股输出以及 warning 生命周期、cohort 和描述性价格路径汇总：

```powershell
python scripts/run_v04_phase4_validation.py `
  --manifest validation/v04_phase4_samples.csv `
  --display-start 2024-01-01 `
  --display-end 2026-07-20 `
  --adjust forward `
  --output-dir outputs/validation/v04_phase4
```

如需绕过既有行情缓存可增加 `--force-refresh`。任一样本失败时仍会保留错误行并处理
其他样本，脚本最终返回非零；这些结果只用于描述性验证，不是策略收益或仓位建议。

## v0.4 Phase 4.1 warning 事件时点可操作性验证

Phase 4.1 只读取 Phase 4 已生成的 12 个样本输出，不连接 AmazingData。它以事件后下一
真实交易日开盘作为最早执行代理，并核对正式背离与 ESCALATED warning 的逐条链接：

```powershell
python scripts/run_v04_phase41_actionability.py `
  --phase4-output outputs/validation/v04_phase4 `
  --output-dir outputs/validation/v04_phase41_actionability
```

任一样本文件、schema、checksum 或 linkage 核对失败时脚本返回非零。输出仅用于描述性
验证，不是策略收益、成交承诺或仓位建议。

## 中际旭创回归

```powershell
python -m rsi_exit.cli `
  --symbol 300308.SZ `
  --name 中际旭创 `
  --start 2026-02-01 `
  --end 2026-07-20 `
  --adjust forward `
  --plot
```

在线入口先通过 AmazingData 交易日历定位展示日前第 120 个真实交易日，在完整前复权序列上计算 MA、RSI、峰值和状态，最后才裁剪 `daily_features.csv`。离线入口必须传入包含足量前置历史的原始标准日 K CSV；传入已裁剪的展示 CSV 会明确报错。

若需用已归档的 v0.1 输出生成 old/new 对照，可增加：

```powershell
--comparison-baseline-dir outputs/rsi_exit_v01_baseline/300308.SZ
```

## 输出

单股目录 `outputs/rsi_exit/<symbol>/`：

- `daily_features.csv`：同列输出 decision 与 effective 状态、动作和仓位上限；
- `peaks.csv`：每个不可变候选峰及其 canonical、结构资格、价格关系、双周期和展示标志；
- `canonical_peaks.csv`：每个 canonical 的当前代表候选；
- `signals.csv`：保留 forming/formal、new-high/near-high、可比区、last structural、动能锚、divergence chain、risk cycle 和生效日；
- `warning_events.csv`：记录完整、append-only 的背离预警生命周期；当前不影响仓位或自动交易；
- `state_log.csv`、`cycle_log.csv`：状态和周期重置审计；
- `rsi_audit.csv`：原始/复权价格、因子、递推分子分母、预热标志和校验和；
- `summary.md`：展示截至展示结束日的 warning 状态和展示区间事件时间线；
- `annotated_chart.png`：在 RSI 子图轻量显示每个 warning 的 OPENED 和最新生命周期结果；
- `regression_comparison.md`：记录旧输出与当前正式输出的回归对照。

根输出目录另有 `peak_validation_summary.csv`。

## 关键语义

- 峰值 `t` 只在 `t+1` 双下降后确认，最早 `t+2` 生效；基础状态也只在下一真实交易日生效。
- S3/S4 中 RSI≥strong 且收盘高于 MA 时产生一次 `ALLOW_REENTRY`，基础状态回到 S0；S5 仅保留枚举兼容，不驻留。
- 默认候选只要求 `t` 相对 `t-1` 双上升、`t+1` 双下降。三日窗口最大值仅在 `require_recent_window_max=true` 时启用。
- RSI 恰好下降 1.0 点计为背离；正式背离同时验证相邻结构峰和 momentum anchor。
- 同日先保存不可变正式快照；risk cycle 与 divergence chain 互不耦合，S3/再入不清背离链。
- canonical 正式快照以 `(canonical_peak_id, canonical_version)` 为不可变键；同 canonical
  新版本默认只审计，只有结构合格且较同组上一正式版本 RSI 至少提高 2.0 时，才以无
  仓位资格的 `ANCHOR_RSI_BREAKOUT` 重建动能锚和背离链。
- 普通信号上限使用 `APPLY_SIGNAL_CAP`，周期重置使用 `RESET_SIGNAL_DOMAIN`；reset 使旧 cycle 的待生效和已生效信号约束失效，新 cycle 从 signal cap=1.0 开始。

批量 Python 入口必须显式传入展示区间，避免把计算区间首日误当展示首日：

```python
results, summary = run_batch(
    items,
    config=config,
    display_start_date="YYYY-MM-DD",
    display_end_date="YYYY-MM-DD",
)
```

冻结口径见 [v0.3 顶部背离规格](docs/specs/rsi_exit_v0.3_top_divergence_spec_v0.2.md)。[v0.2 技术说明](docs/rsi_exit_v02.md) 与 [v0.1 技术说明](docs/rsi_exit_v01.md) 保留为历史基线。
