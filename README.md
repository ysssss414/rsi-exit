# RSI卖点信号识别器 v0.1

本目录实现“趋势股RSI卖点与持仓去偏系统”的第一阶段：日线级 RSI14、高点确认、顶部背离/连续背离/弱反弹、六状态机、目标仓位上限、结构化 CSV、Markdown 摘要和标记图。策略只生成风险约束，不自动交易。

实现沿用现有 `D:/ej/材料/codex/db/trading_review_system` 与 `D:/ej/材料/codex/yh` 的约定：

- 复用 `yh_quant_shape.data_provider.AmazingDataProvider` 的登录、交易日历、代码信息和 `MarketData.query_kline`；
- 凭据继续由旧项目 `.env.local` 或 `AMAZINGDATA_*` 环境变量读取，不复制、不硬编码；
- 复权因子使用手册确认的 `BaseData.get_backward_factor`；
- 配置继续采用 JSON-compatible YAML，CSV 采用 UTF-8-SIG；
- AmazingData 1.1.6 延迟导入，避免核心算法测试依赖 SDK。

## 目录

```text
rsi_exit/
  cli.py                  命令行入口
  config.py               配置读取和校验
  indicators.py           国内公式 CN-SMA 与 RSI14
  peak_detector.py        候选、确认、独立波段与同波段合并
  divergence.py           四类峰值关系、连续背离与动能锚
  state_machine.py        S0-S5 基础状态机
  position_rules.py       目标仓位上限与取严合并
  pipeline.py             无未来逐日流水线和批量摘要
  plotting.py             双栏人工核验图
  reporting.py            CSV、summary 和批量汇总
  data/
    amazingdata_adapter.py 统一数据入口
    cache.py               原始日K缓存
config/rsi_exit_v01.yaml
docs/rsi_exit_v01.md
tests/
```

## 安装与测试

Python 3.10+：

```powershell
python -m pip install -e ".[test,amazingdata]"
python -m pytest -q
```

`amazingdata` 可选依赖用于 SDK 的 Pydantic v2 日K转换和 HDF5 复权因子缓存。AmazingData SDK 本身继续使用现有安装，不由本项目重新分发。

## 中际旭创运行

现有代码信息真实样本已确认：中际旭创为 `300308.SZ`。

```powershell
python -m rsi_exit.cli `
  --symbol 300308.SZ `
  --name 中际旭创 `
  --start 2026-02-01 `
  --end 2026-07-20 `
  --adjust forward `
  --plot
```

首次在线请求会把原始日 K 缓存在 `cache/amazingdata/raw/`；复权因子由 SDK 缓存在 `cache/amazingdata/factors/`。重复运行不加 `--force-refresh`。

已验证 CSV 的离线复核入口：

```powershell
python -m rsi_exit.cli `
  --symbol 300308.SZ `
  --name 中际旭创 `
  --start 2026-02-01 `
  --end 2026-07-20 `
  --adjust forward `
  --input-csv outputs/rsi_exit/300308.SZ/daily_features.csv `
  --plot
```

## 输出

默认目录为 `outputs/rsi_exit/<symbol>/`：

- `daily_features.csv`
- `peaks.csv`
- `signals.csv`
- `state_log.csv`
- `summary.md`
- `annotated_chart.png`（传入 `--plot`）
- `outputs/rsi_exit/peak_validation_summary.csv`（单股一行，批量时多行）

批量代码入口为 `rsi_exit.pipeline.run_batch`，汇总输出函数为 `rsi_exit.reporting.write_batch_summary`，字段契约包含在 `peak_validation_summary.csv` 中。第二批股票名称应先通过 `AmazingDataAdapter.resolve_symbol()` 查询基础信息，不在代码中手填证券代码。

## 当前中际旭创验收

在线 AmazingData 返回 2026-02-02 至 2026-07-20 共 110 个交易日。默认参数得到：14 个独立波段高点、2 次顶部背离、3 次弱反弹；一次/二次背离确认日为 2026-05-29、2026-06-05。区间盘中最高价 1416.88 出现在 2026-06-22，同日收盘高点被识别为 P0015，2026-06-23 确认，2026-06-24 才允许执行。详细解释见生成的 `summary.md`。

规则歧义、无未来约束、状态机保守解释与已知限制见 [v0.1 技术说明](docs/rsi_exit_v01.md)。
