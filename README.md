# RSI卖点信号识别器 v0.2.1

面向 A 股日线趋势股的 RSI 卖点与持仓去偏系统。它生成可审计的风险约束，不读取成本、盈亏或持仓时间，不自动下单。

v0.2.1 在 v0.2 基础上修复 signal cap 与 cycle reset 的同日待生效冲突，并补齐批量预热、预热信号溯源和参数化输出。AmazingData 仍是唯一在线行情源。

## 安装与测试

Python 3.10+：

```powershell
python -m pip install -e ".[test,amazingdata]"
python -m pytest -q
```

AmazingData 凭据仍由既有 `D:/ej/材料/codex/yh` 项目的环境变量或 `.env.local` 读取；本仓库不保存凭据。

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
- `peaks.csv`：每个不可变候选峰及其 canonical、版本、周期和展示标志；
- `canonical_peaks.csv`：每个 canonical 的当前代表候选；
- `signals.csv`：保留完整计算区间信号、预热/展示标志、cycle、current/previous canonical 版本快照、动能锚和生效日；
- `state_log.csv`、`cycle_log.csv`：状态和周期重置审计；
- `rsi_audit.csv`：原始/复权价格、因子、递推分子分母、预热标志和校验和；
- `summary.md`、`regression_comparison.md`、`annotated_chart.png`。

根输出目录另有 `peak_validation_summary.csv`。

## 关键语义

- 峰值 `t` 只在 `t+1` 双下降后确认，最早 `t+2` 生效；基础状态也只在下一真实交易日生效。
- S3/S4 中 RSI≥strong 且收盘高于 MA 时产生一次 `ALLOW_REENTRY`，基础状态回到 S0；S5 仅保留枚举兼容，不驻留。
- 默认候选只要求 `t` 相对 `t-1` 双上升、`t+1` 双下降。三日窗口最大值仅在 `require_recent_window_max=true` 时启用。
- RSI 恰好下降配置容差计为背离；低价且 RSI 容差内持平归为 `LOWER_PRICE_RSI_FLAT`。
- 同日先保存峰值关系，再执行只影响未来的周期重置。全局同波段合并和局部背离周期互不耦合。
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

详细口径见 [v0.2 技术说明](docs/rsi_exit_v02.md)。[v0.1 技术说明](docs/rsi_exit_v01.md) 保留为历史基线。
