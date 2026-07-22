# RSI卖点信号识别器 v0.2 技术说明

## 1. 数据、预热与 RSI

在线模式先调用 AmazingData 交易日历，取展示起始日前至少 120 个实际交易日，再获取完整区间日 K 和复权因子。前复权公式仍为：

```text
adjusted_price[t] = raw_price[t] * backward_factor[t] / backward_factor[end]
```

MA 和 RSI 在完整计算区间递推，展示 CSV 最后裁剪。RSI 公式未改变：

```text
RSI = CN_SMA(MAX(CLOSE-REF(CLOSE,1),0), N, 1)
    / CN_SMA(ABS(CLOSE-REF(CLOSE,1)), N, 1) * 100
```

`N`、seed mode 和 MA 周期均来自配置。`rsi_audit.csv` 保留输入价格、复权字段、delta、gain、abs delta、两条 CN-SMA、RSI、区间标志和 SHA-256。历史不足时从 `UNINITIALIZED` 开始，并发出高优先级警告；CLI 离线入口直接拒绝不足 120 日的已裁剪 CSV。

## 2. 状态与生效时间

S3/S4 只有在 RSI 位于 life 与 strong 之间且收盘高于 MA 时进入/保持 S4。RSI 达到 strong 且收盘高于 MA 时产生一次 `ALLOW_REENTRY`，同时回到 S0。下一次普通 60—70 调整进入 S1，不会再次进入 S4。

所有每日输出区分：

- `decision_*`：当日收盘后形成；
- `earliest_action_date/effective_date`：下一实际交易日；
- `effective_*`：当日开盘前已经可用的历史约束。

待生效队列按交易日应用；同日多项约束分别在基础域和信号域取更严格值，最终再取二者较小值。回测只能使用 effective 列。

## 3. 峰值身份与因果

默认候选定义只有当日相对前日双上升、下一日双下降。`require_recent_window_max=false`；启用后才按配置 lookback 检查窗口最大值。

每个确认候选拥有不可变 `candidate_peak_id`。同波段使用稳定 `canonical_peak_id`，当前代表由 `representative_candidate_id` 指出，代表变化使 `canonical_version` 递增。`peaks.csv` 保存所有候选自身值；`canonical_peaks.csv` 保存当前代表。信号行固定记录形成时的 current/previous 候选、canonical 和版本，不因未来合并回写。

峰值 t 在 t+1 收盘后确认，最早 t+2 生效。追加未来行情不会改变已经确认的身份、版本快照和关系；只有当原数据末端尚不知道下一交易日时，末端 `earliest_action_date` 会暂为空。

## 4. 背离、动能锚与周期

RSI 明显降低使用闭区间：

```text
current_rsi <= previous_rsi - rsi_tolerance
```

低价且 RSI 容差内持平/轻微下降为 `LOWER_PRICE_RSI_FLAT`，不触发卖出；只有达到向上容差才叫 `LOWER_PRICE_RSI_IMPROVING`。

动能锚是当前背离周期内 RSI 最高的 canonical 代表快照。任何 canonical 合并更新都会与锚比较；价格更高但 RSI 更低可以更新代表，却不能降低锚。

当日状态和峰值共享同一 decision timestamp：先完整记录峰值关系，再因 S3、趋势强化、过长间隔或中间 RSI 跌破重置线关闭旧周期。`cycle_log.csv` 保存 reset decision/effective 日期。重置后第一个候选即使仍属于全局旧 canonical，也使用该候选自身值建立新周期基准。

## 5. 中际旭创 2026-07-20

本轮 AmazingData 前复权计算区间为 2025-08-06 至 2026-07-20，展示日前正好 120 个交易日。v0.2 结果为 38.846532；旧版展示起点播种结果约 38.8449。差异很小，来源是递推起点改变，不是公式、收盘价或股票特例。行情软件截图 42.68 只作为外部待核差异，程序没有把它当目标值。

完整 old/new 峰值、信号、状态、仓位、周期与动能锚对照见生成的 `regression_comparison.md`。
