# rsi-exit v0.4 Phase 4 多样本描述性验证

## 执行摘要

- **执行结果：**12 个样本中 12 个成功，0 个失败；warning lifecycle 合同错误 0 个。
- **验证 cohort：**展示区间形成 304 个 warning，另有 0 个 carry-in；截止状态为 ACTIVE 0 / ESCALATED 140 / CLEARED 26 / INVALIDATED 138。
- **INVALIDATED 原因：**FORMING_CONDITION_BROKEN 138
- **ESCALATED lead time：**中位数 1 个交易日，范围 1–5 个交易日。
- **warning 密度：**最多为 45（002463.SZ），最少为 6（600519.SH）。

本报告只验证固定口径下的运行稳定性、事件合同和描述性价格路径；结果不用于比较个股优劣，也不构成参数或仓位建议。

## 固定样本的运行与合同结果

表中 warning 数与 event 数保持不同粒度；失败样本保留原 manifest 行。

| 代码 | 名称 | 组别 | 正式背离 | cohort | carry-in | ACTIVE | ESCALATED | CLEARED | INVALIDATED | 合同通过 | 错误 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 300308.SZ | 中际旭创 | AI_OPTICAL | 16 | 33 | 0 | 0 | 16 | 2 | 15 | 是 | — |
| 300502.SZ | 新易盛 | AI_OPTICAL | 17 | 34 | 0 | 0 | 17 | 1 | 16 | 是 | — |
| 300394.SZ | 天孚通信 | AI_OPTICAL | 11 | 26 | 0 | 0 | 11 | 1 | 14 | 是 | — |
| 002463.SZ | 沪电股份 | PCB | 16 | 45 | 0 | 0 | 16 | 3 | 26 | 是 | — |
| 600183.SH | 生益科技 | PCB | 21 | 33 | 0 | 0 | 21 | 2 | 10 | 是 | — |
| 688012.SH | 中微公司 | SEMICONDUCTOR_EQUIPMENT | 3 | 15 | 0 | 0 | 3 | 6 | 6 | 是 | — |
| 688072.SH | 拓荆科技 | SEMICONDUCTOR_EQUIPMENT | 6 | 18 | 0 | 0 | 6 | 2 | 10 | 是 | — |
| 300750.SZ | 宁德时代 | GROWTH_CYCLICAL | 18 | 28 | 0 | 0 | 18 | 3 | 7 | 是 | — |
| 300274.SZ | 阳光电源 | GROWTH_CYCLICAL | 6 | 16 | 0 | 0 | 6 | 2 | 8 | 是 | — |
| 601127.SH | 赛力斯 | GROWTH_CYCLICAL | 6 | 20 | 0 | 0 | 6 | 3 | 11 | 是 | — |
| 600519.SH | 贵州茅台 | LARGE_CAP_CONTROL | 3 | 6 | 0 | 0 | 3 | 1 | 2 | 是 | — |
| 601318.SH | 中国平安 | LARGE_CAP_CONTROL | 17 | 30 | 0 | 0 | 17 | 0 | 13 | 是 | — |

### 失败明细

- 无失败样本。

## 生命周期结构显示 refresh 与终态分布

展示区间 event 总数为 OPENED 304 / REFRESHED 148 / ESCALATED 140 / CLEARED 26 / INVALIDATED 138。下表同时给出 cohort 粒度的 refresh 汇总，避免把多次 refresh 误计为多个 warning。

| 指标 | 数量 |
| --- | --- |
| OPENED | 304 |
| REFRESHED | 148 |
| ESCALATED | 140 |
| CLEARED | 26 |
| INVALIDATED | 138 |
| 每个 cohort warning 的平均 refresh | 0.49 |
| 每个 cohort warning 的中位 refresh | 0 |
| 终态 ESCALATED | 140 |
| 终态 CLEARED | 26 |
| 终态 INVALIDATED | 138 |

**INVALIDATED end reason：**FORMING_CONDITION_BROKEN 138

**ESCALATED lead time：**中位数 1，范围 1–5 个交易日。

## 截止状态分组的后续价格路径

每行使用相同截止状态下的 cohort warning。完整样本数是展示结束日前确有足够后续交易行的 warning 数；不完整 horizon 不参与中位数。

| 截止状态 | 交易日 horizon | warning 数 | 完整样本数 | 期末收益中位数 | 区间最大收益中位数 | 区间最小收益中位数 |
| --- | --- | --- | --- | --- | --- | --- |
| ACTIVE | 1 | 0 | 0 | — | — | — |
| ACTIVE | 3 | 0 | 0 | — | — | — |
| ACTIVE | 5 | 0 | 0 | — | — | — |
| ACTIVE | 10 | 0 | 0 | — | — | — |
| ACTIVE | 20 | 0 | 0 | — | — | — |
| ESCALATED | 1 | 140 | 140 | -0.71% | -0.71% | -0.71% |
| ESCALATED | 3 | 140 | 140 | -1.25% | 0.81% | -2.61% |
| ESCALATED | 5 | 140 | 140 | -0.41% | 2.46% | -3.21% |
| ESCALATED | 10 | 140 | 140 | -0.12% | 4.67% | -4.62% |
| ESCALATED | 20 | 140 | 138 | 0.53% | 7.04% | -5.73% |
| CLEARED | 1 | 26 | 26 | -0.55% | -0.55% | -0.55% |
| CLEARED | 3 | 26 | 26 | -1.01% | 0.30% | -2.43% |
| CLEARED | 5 | 26 | 26 | -2.88% | 0.44% | -3.31% |
| CLEARED | 10 | 26 | 26 | -3.35% | 1.77% | -5.34% |
| CLEARED | 20 | 26 | 25 | -7.94% | 5.19% | -10.27% |
| INVALIDATED | 1 | 138 | 138 | 0.65% | 0.65% | 0.65% |
| INVALIDATED | 3 | 138 | 138 | 3.39% | 4.92% | -0.26% |
| INVALIDATED | 5 | 138 | 138 | 2.61% | 6.60% | -0.61% |
| INVALIDATED | 10 | 138 | 137 | 2.21% | 8.41% | -2.93% |
| INVALIDATED | 20 | 138 | 137 | 4.37% | 15.42% | -4.41% |

**解释边界：**这些值只是 warning 后的描述性价格路径，不是策略收益；没有计入可执行价格、滑点、涨跌停或交易成本，也不能据此直接形成仓位规则。

## 稳定排序选取的代表案例

每种实际出现的截止状态最多列 2 个，按 symbol、opened_date、warning_id 排序选取；复用正常单股输出中的本地图表，不另行绘图。


### ESCALATED

- `002463.SZ` / `FWARN-0829B5C41300D0F1847170112379DEAF01A9F688918F085488E00ECC316C9089`：OPENED 2024-02-23，refresh 2 次，截止状态 ESCALATED，terminal reason FORMAL_DIVERGENCE_CONFIRMED，escalation lead 3.0；5 日路径 期末 7.62%，最大 7.62%，最小 -0.08%，20 日路径 期末 25.75%，最大 30.37%，最小 -0.08%；图表 `outputs/validation/v04_phase4/002463.SZ/annotated_chart.png`。
- `002463.SZ` / `FWARN-DC1F0C143BCD7520CFAE4E6EB3457C7097E0A2C4D97FAE79D2D859E61F8ABD40`：OPENED 2024-03-13，refresh 3 次，截止状态 ESCALATED，terminal reason FORMAL_DIVERGENCE_CONFIRMED，escalation lead 4.0；5 日路径 期末 8.91%，最大 10.59%，最小 0.84%，20 日路径 期末 1.31%，最大 10.59%，最小 -3.55%；图表 `outputs/validation/v04_phase4/002463.SZ/annotated_chart.png`。

### CLEARED

- `002463.SZ` / `FWARN-5767E1E64837E185F500AE91AB4BE2B6BE1AB3CD5D74DD895684F733FB5DF7A8`：OPENED 2024-04-01，refresh 0 次，截止状态 CLEARED，terminal reason MOMENTUM_ANCHOR_REBUILT，escalation lead —；5 日路径 期末 -8.43%，最大 -3.33%，最小 -8.43%，20 日路径 期末 4.09%，最大 5.44%，最小 -9.72%；图表 `outputs/validation/v04_phase4/002463.SZ/annotated_chart.png`。
- `002463.SZ` / `FWARN-1FE06CFE8323878F49E32C579444992C94E11DCB458C83A617C1AE52390E9CED`：OPENED 2024-07-09，refresh 1 次，截止状态 CLEARED，terminal reason MOMENTUM_ANCHOR_REBUILT，escalation lead —；5 日路径 期末 -1.81%，最大 2.00%，最小 -3.24%，20 日路径 期末 -22.87%，最大 2.00%，最小 -25.79%；图表 `outputs/validation/v04_phase4/002463.SZ/annotated_chart.png`。

### INVALIDATED

- `002463.SZ` / `FWARN-DDCDA8521DF7EAB4E1E7D44A2A530C605B2FC584B19CA9E48F795B74360E127B`：OPENED 2024-02-29，refresh 1 次，截止状态 INVALIDATED，terminal reason FORMING_CONDITION_BROKEN，escalation lead —；5 日路径 期末 9.28%，最大 9.28%，最小 3.22%，20 日路径 期末 15.38%，最大 25.04%，最小 3.22%；图表 `outputs/validation/v04_phase4/002463.SZ/annotated_chart.png`。
- `002463.SZ` / `FWARN-2CBDAD59953787B042A3238A9EA23423F37DA2202C5BD513E64BA788B946CAEB`：OPENED 2024-03-20，refresh 0 次，截止状态 INVALIDATED，terminal reason FORMING_CONDITION_BROKEN，escalation lead —；5 日路径 期末 -7.47%，最大 -2.06%，最小 -7.47%，20 日路径 期末 -7.81%，最大 -2.06%，最小 -11.44%；图表 `outputs/validation/v04_phase4/002463.SZ/annotated_chart.png`。

## 范围、数据与指标定义

- 数据源：AmazingData；展示区间：2024-01-01 至 2026-07-20；复权：forward；配置：仓库默认配置；统一使用现有 warmup 要求。
- 主 cohort：OPENED decision_date 位于展示区间；carry-in 单列且不进入价格路径分母。
- duration 与 escalation lead time 均为 `daily_features` 实际交易行索引差；OPENED、latest 与 terminal 价格/RSI 只接受同日精确匹配。
- 1/3/5/10/20 日路径只使用展示结束日前数据；不足完整 horizon 时三个收益字段为空且 complete=False。

## 方法、稳健性与隔离检查

- 每个样本先对完整 warning history 执行结构检查，再调用现有 `derive_warning_states` 推导展示结束日状态；验证层不复制状态机。
- 检查 OPENED 唯一、REFRESHED 版本递增、最多一个终态、终态后无事件、event/status 对应、event ID 唯一、position_effect 全为 NONE、recommended_position_cap 全为空。
- 验证函数只读取 AnalysisResult 的副本；生产输出对象、schema、summary 和图表逻辑均不在本模块内修改。

## 观察到的异常、限制与后续人工问题

- 运行/合同异常：未观察到。
- 无 cohort warning 的样本：无。
- 最长观察生命周期为 5 个交易日：688012.SH/FWARN-3193C36A2CC81390398CC9EB74CA7F63D948804436F9C93C0057E4C32CFC1A4C, 688012.SH/FWARN-A4D39711DD8A3A93284BF60A30720CF93C66E1D03FE9DF55F0A2CD2782B89469, 688012.SH/FWARN-3C81CC60CC8E7841F6B53383DB97E0EA7A927E1017C9EDB1FDC498B7A08FA617。
- 最高 refresh count 为 4：688012.SH/FWARN-3193C36A2CC81390398CC9EB74CA7F63D948804436F9C93C0057E4C32CFC1A4C, 688012.SH/FWARN-A4D39711DD8A3A93284BF60A30720CF93C66E1D03FE9DF55F0A2CD2782B89469, 688012.SH/FWARN-3C81CC60CC8E7841F6B53383DB97E0EA7A927E1017C9EDB1FDC498B7A08FA617。
- 20 日内继续上涨路径的最大观察值为 110.57%：300502.SZ/FWARN-25F06D0FAF280C59C31E59AD2FCD8A1C52E34A6E93E3F89C92943DCAD400DF78；这只是路径观察，不是交易收益。
- 样本和时间窗均为固定的描述性检查；小样本结果不支持统计显著性、因果或泛化结论。
- 下一阶段如需研究 warning 过密、长期 ACTIVE、高 refresh 或正式背离缺少提前 warning，应先人工逐案审阅；本阶段不调参、不修改规则。
