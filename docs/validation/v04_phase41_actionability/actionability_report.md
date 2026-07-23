# rsi-exit v0.4 Phase 4.1 warning 事件时点可操作性验证

## 技术摘要

- **数据与合同：**12/12 个样本通过文件、schema、checksum 与 linkage 核对；失败 0 个。
- **事件规模：**OPENED 304（action date 304） / ESCALATED 140（action date 140） / CLEARED 26（action date 26） / INVALIDATED 138（action date 138）。
- **OPENED 无条件 5 日路径：**完整样本 304，期末中位数 0.38%，25%/75% 分位数 -4.16%/7.24%，区间最大/最小中位数 5.00%/-3.90%；该统计没有按未来终态分组。
- **ESCALATED 后 5 日路径：**完整样本 140，期末中位数 0.30%，25%/75% 分位数 -3.34%/7.45%，区间最大/最小中位数 5.33%/-4.11%。
- **等待成本：**lead 中位数 1 个交易日；OPENED close 到 ESCALATED close 中位数 -1.24%，到最早 action open 中位数 -1.35%。
- **正式背离 linkage：**正式背离 140，ESCALATED 140，唯一匹配 140，缺失 0，冲突 0。

这些结果是事件在收盘后已知、最早于下一真实交易日开盘行动的执行代理路径，不是策略收益，也不代表真实成交必然完成。

## 事件时点、cohort 与指标定义

- 数据范围：Phase 4 固定 12 样本，展示区间 2024-01-01 至 2026-07-20；不重新连接 AmazingData。
- event decision date 当日收盘后事件才完整可知；action date 是其后下一条真实交易行，action open 是该日前复权开盘价。
- OPENED、ESCALATED、CLEARED、INVALIDATED 每个实际展示区间事件一行；REFRESHED 不形成独立 action cohort，只保留截至事件可知的 refresh 审计。
- `ex_post_terminal_status` 只用于事后诊断，不能进入 OPENED 当日决策或 OPENED 主汇总。
- 1/3/5/10/20 日路径从 action open 起算；action day 是第 1 日，max 使用 high，min 使用 low，不完整 horizon 留空。

## OPENED 的无条件路径不足以单独形成直接操作规则

下表使用所有 OPENED，不按未来 ESCALATED、CLEARED 或 INVALIDATED 分组。这避免把事后终态泄漏回事件发生日。

| 事件 | 样本组 | 交易日 | 事件数 | action date 可用 | 完整样本 | 期末中位数 | 最大中位数 | 最小中位数 | 期末 P25 | 期末 P75 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OPENED | ALL | 1 | 304 | 304 | 304 | 0.08% | 2.06% | -1.72% | -1.92% | 2.14% |
| OPENED | ALL | 3 | 304 | 304 | 304 | 0.24% | 4.03% | -3.21% | -3.47% | 4.97% |
| OPENED | ALL | 5 | 304 | 304 | 304 | 0.38% | 5.00% | -3.90% | -4.16% | 7.24% |
| OPENED | ALL | 10 | 304 | 304 | 303 | 1.18% | 9.47% | -5.52% | -5.56% | 8.79% |
| OPENED | ALL | 20 | 304 | 304 | 300 | 1.19% | 13.37% | -7.19% | -7.66% | 16.10% |

**解释：**OPENED 5 日 action-open 路径完整样本 304，期末中位数 0.38%，25%/75% 分位数 -4.16%/7.24%，区间最大/最小中位数 5.00%/-3.90%。分布同时包含后来升级和后来失效的 warning，描述性结果本身不足以证明 OPENED 具有可直接执行的统一价值。

## ESCALATED 后的路径与板块差异

ESCALATED 表示正式背离已经在事件日收盘后确认；下表从下一真实交易日开盘起算，包含总体和每个固定 sample group。

| 事件 | 样本组 | 交易日 | 事件数 | action date 可用 | 完整样本 | 期末中位数 | 最大中位数 | 最小中位数 | 期末 P25 | 期末 P75 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ESCALATED | ALL | 1 | 140 | 140 | 140 | -0.25% | 2.13% | -1.67% | -1.94% | 1.78% |
| ESCALATED | ALL | 3 | 140 | 140 | 140 | -0.25% | 4.02% | -3.05% | -2.16% | 5.06% |
| ESCALATED | ALL | 5 | 140 | 140 | 140 | 0.30% | 5.33% | -4.11% | -3.34% | 7.45% |
| ESCALATED | ALL | 10 | 140 | 140 | 140 | 0.23% | 7.92% | -4.96% | -5.10% | 12.44% |
| ESCALATED | ALL | 20 | 140 | 140 | 137 | 1.78% | 13.29% | -6.33% | -4.26% | 17.90% |
| ESCALATED | AI_OPTICAL | 1 | 44 | 44 | 44 | -1.26% | 2.40% | -3.05% | -2.70% | 0.65% |
| ESCALATED | AI_OPTICAL | 3 | 44 | 44 | 44 | 0.50% | 4.64% | -3.89% | -2.92% | 6.00% |
| ESCALATED | AI_OPTICAL | 5 | 44 | 44 | 44 | 2.56% | 7.30% | -4.81% | -3.04% | 9.38% |
| ESCALATED | AI_OPTICAL | 10 | 44 | 44 | 44 | -0.38% | 13.22% | -5.94% | -5.81% | 13.42% |
| ESCALATED | AI_OPTICAL | 20 | 44 | 44 | 43 | -1.61% | 14.82% | -10.96% | -7.95% | 19.68% |
| ESCALATED | PCB | 1 | 37 | 37 | 37 | 1.75% | 3.50% | -1.39% | -0.75% | 4.35% |
| ESCALATED | PCB | 3 | 37 | 37 | 37 | 5.40% | 6.94% | -2.34% | -0.55% | 9.53% |
| ESCALATED | PCB | 5 | 37 | 37 | 37 | 6.60% | 9.90% | -3.04% | -2.46% | 10.45% |
| ESCALATED | PCB | 10 | 37 | 37 | 37 | 9.20% | 17.06% | -3.86% | -1.88% | 17.48% |
| ESCALATED | PCB | 20 | 37 | 37 | 35 | 8.73% | 22.64% | -3.86% | 1.02% | 23.68% |
| ESCALATED | SEMICONDUCTOR_EQUIPMENT | 1 | 9 | 9 | 9 | -0.54% | 2.67% | -2.24% | -3.34% | 1.28% |
| ESCALATED | SEMICONDUCTOR_EQUIPMENT | 3 | 9 | 9 | 9 | -1.01% | 4.30% | -3.32% | -3.31% | 0.16% |
| ESCALATED | SEMICONDUCTOR_EQUIPMENT | 5 | 9 | 9 | 9 | -3.22% | 5.60% | -6.83% | -3.91% | 3.50% |
| ESCALATED | SEMICONDUCTOR_EQUIPMENT | 10 | 9 | 9 | 9 | -6.09% | 6.73% | -9.51% | -11.03% | 2.62% |
| ESCALATED | SEMICONDUCTOR_EQUIPMENT | 20 | 9 | 9 | 9 | 3.86% | 10.91% | -9.51% | -5.90% | 9.07% |
| ESCALATED | GROWTH_CYCLICAL | 1 | 30 | 30 | 30 | -0.34% | 1.48% | -1.48% | -1.97% | 0.68% |
| ESCALATED | GROWTH_CYCLICAL | 3 | 30 | 30 | 30 | -1.04% | 2.14% | -3.68% | -2.82% | 0.98% |
| ESCALATED | GROWTH_CYCLICAL | 5 | 30 | 30 | 30 | -1.23% | 2.60% | -4.41% | -4.40% | 1.68% |
| ESCALATED | GROWTH_CYCLICAL | 10 | 30 | 30 | 30 | -1.96% | 5.37% | -5.13% | -5.86% | 6.11% |
| ESCALATED | GROWTH_CYCLICAL | 20 | 30 | 30 | 30 | 1.07% | 7.51% | -5.92% | -5.71% | 8.83% |
| ESCALATED | LARGE_CAP_CONTROL | 1 | 20 | 20 | 20 | -0.39% | 0.54% | -1.00% | -0.94% | 0.31% |
| ESCALATED | LARGE_CAP_CONTROL | 3 | 20 | 20 | 20 | -0.90% | 0.76% | -2.15% | -1.71% | -0.04% |
| ESCALATED | LARGE_CAP_CONTROL | 5 | 20 | 20 | 20 | -0.91% | 0.76% | -2.74% | -1.98% | 0.37% |
| ESCALATED | LARGE_CAP_CONTROL | 10 | 20 | 20 | 20 | -0.91% | 2.72% | -3.00% | -2.49% | 2.70% |
| ESCALATED | LARGE_CAP_CONTROL | 20 | 20 | 20 | 20 | 0.20% | 3.79% | -3.33% | -2.51% | 2.58% |

**总体解释：**ESCALATED 5 日 action-open 路径完整样本 140，期末中位数 0.30%，25%/75% 分位数 -3.34%/7.45%，区间最大/最小中位数 5.33%/-4.11%。总体期末中位数没有呈现持续下跌，四分位区间和样本组差异也较宽；因此当前证据只显示短期下行暴露，不能证明统一、稳定的短期风险方向。样本组差异只用于描述稳健性，不用于个股优劣或参数选择。

## 等待 OPENED 升级为 ESCALATED 的时间与价格空间

| 指标 | 样本数 | 中位数 | P25 | P75 | 范围 |
| --- | --- | --- | --- | --- | --- |
| lead trading days | 140 | 1 | 1 | 2 | 1 至 5 |
| OPENED close → ESCALATED close | 140 | -1.24% | -2.78% | -0.21% | -10.91% 至 10.05% |
| OPENED close → ESCALATED action open | 140 | -1.35% | -4.13% | 0.44% | -29.75% 至 15.05% |

等待成本同时报告 OPENED close 到 ESCALATED close，以及 OPENED close 到 ESCALATED 后最早 action open；后者更接近真正可操作时点，但仍未计入涨跌停、滑点和交易成本。等待的中位价格成本为负，但 INVALIDATED 事件数量接近 ESCALATED 且事件后路径分布宽，现有描述证据不足以证明在 OPENED 统一行动所节省的风险能覆盖机会成本。

## INVALIDATED 后路径描述取消 warning 之后的市场状态

| 事件 | 样本组 | 交易日 | 事件数 | action date 可用 | 完整样本 | 期末中位数 | 最大中位数 | 最小中位数 | 期末 P25 | 期末 P75 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| INVALIDATED | ALL | 1 | 138 | 138 | 138 | 0.58% | 2.54% | -1.75% | -1.44% | 2.13% |
| INVALIDATED | ALL | 3 | 138 | 138 | 138 | -0.01% | 5.03% | -3.25% | -3.31% | 4.45% |
| INVALIDATED | ALL | 5 | 138 | 138 | 138 | -0.10% | 5.45% | -4.50% | -3.79% | 5.36% |
| INVALIDATED | ALL | 10 | 138 | 138 | 137 | 1.00% | 8.03% | -5.76% | -5.79% | 8.30% |
| INVALIDATED | ALL | 20 | 138 | 138 | 137 | 2.12% | 13.41% | -7.15% | -8.16% | 17.08% |

**解释：**INVALIDATED 5 日 action-open 路径完整样本 138，期末中位数 -0.10%，25%/75% 分位数 -3.79%/5.36%，区间最大/最小中位数 5.45%/-4.50%。这可以支持研究取消 warning 后恢复普通观察，但不等于自动恢复仓位或生成买入动作。

## CLEARED 前后的两段路径必须分开解释

OPENED close 到 CLEARED close 的事前等待段：样本 26，中位数 -0.98%，P25/P75 -2.55%/-0.25%，范围 -9.26% 至 13.75%。

| 事件 | 样本组 | 交易日 | 事件数 | action date 可用 | 完整样本 | 期末中位数 | 最大中位数 | 最小中位数 | 期末 P25 | 期末 P75 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLEARED | ALL | 1 | 26 | 26 | 26 | -0.10% | 1.73% | -2.27% | -1.66% | 1.06% |
| CLEARED | ALL | 3 | 26 | 26 | 26 | -0.57% | 2.24% | -3.72% | -2.85% | 4.56% |
| CLEARED | ALL | 5 | 26 | 26 | 26 | -2.60% | 2.89% | -4.86% | -5.54% | 3.89% |
| CLEARED | ALL | 10 | 26 | 26 | 26 | -1.05% | 5.47% | -6.86% | -7.55% | 6.36% |
| CLEARED | ALL | 20 | 26 | 26 | 25 | -7.25% | 6.52% | -10.90% | -14.75% | -1.79% |

**CLEARED 事件后的路径：**5 日 action-open 路径完整样本 26，期末中位数 -2.60%，25%/75% 分位数 -5.54%/3.89%，区间最大/最小中位数 2.89%/-4.86%。不能再用从 OPENED 起算的 CLEARED 组收益解释 CLEARED 当日动作。

## 正式背离与 ESCALATED linkage 逐条一致性

| 指标 | 数量 |
| --- | --- |
| 正式背离 | 140 |
| ESCALATED | 140 |
| 唯一匹配 | 140 |
| 缺失匹配 | 0 |
| 冲突 | 0 |

核对包含 linked ref、decision date、symbol、signal type、canonical ID/version 与 divergence chain；不是只比较总数。

## 按 5 日路径选择的代表案例

每个 lifecycle event 最多列出 action 后下跌较明显、上涨较明显和接近中位数各一个；`ex_post_terminal_status` 仅作事后标签。


### OPENED

- **下跌较明显** `688012.SH` / `FWARN-88B6811009623756E4DF2D43CA991331A3367F15D2B959ECB7A52E91228C67BE`：event 2026-05-25，action 2026-05-26，5 日期末 -42.60%，事后终态 ESCALATED；图表 `outputs/validation/v04_phase4/688012.SH/annotated_chart.png`。
- **上涨较明显** `300502.SZ` / `FWARN-34AA600DC5B6DAE64579D5D10D0C2E55F6E2A7BC41BF37399BD512AA57BE15C5`：event 2024-05-31，action 2024-06-03，5 日期末 44.50%，事后终态 INVALIDATED；图表 `outputs/validation/v04_phase4/300502.SZ/annotated_chart.png`。
- **接近中位数** `600183.SH` / `FWARN-3E01E2674F50B6D4E1F217DB5F58F4597FA3861EAB9B74BD6AA8B8A0FC53196E`：event 2024-06-20，action 2024-06-21，5 日期末 0.44%，事后终态 ESCALATED；图表 `outputs/validation/v04_phase4/600183.SH/annotated_chart.png`。

### ESCALATED

- **下跌较明显** `688012.SH` / `FWARN-88B6811009623756E4DF2D43CA991331A3367F15D2B959ECB7A52E91228C67BE`：event 2026-05-26，action 2026-05-27，5 日期末 -39.05%，事后终态 ESCALATED；图表 `outputs/validation/v04_phase4/688012.SH/annotated_chart.png`。
- **上涨较明显** `300274.SZ` / `FWARN-5D6B8544BAA023EC4ECFBAB023ECB198E9F72951BE59F3BB2DF91C3E024375DA`：event 2025-09-01，action 2025-09-02，5 日期末 37.41%，事后终态 ESCALATED；图表 `outputs/validation/v04_phase4/300274.SZ/annotated_chart.png`。
- **接近中位数** `300502.SZ` / `FWARN-B810263FFD1BFBF80B5D75425218DC43E8F9CD36E1E09011AB87772BCA8099A9`：event 2026-03-26，action 2026-03-27，5 日期末 0.27%，事后终态 ESCALATED；图表 `outputs/validation/v04_phase4/300502.SZ/annotated_chart.png`。

### CLEARED

- **下跌较明显** `300274.SZ` / `FWARN-3A84C32DF64A3C62BFACD3B42470812DF86028DD02FB12D18FE50D1C2A9DDBA6`：event 2024-06-07，action 2024-06-11，5 日期末 -29.87%，事后终态 CLEARED；图表 `outputs/validation/v04_phase4/300274.SZ/annotated_chart.png`。
- **上涨较明显** `688012.SH` / `FWARN-0A53A33E1F1FA9DDF11AD60F605A7E008E243BBA5E0CA48BE6039FCFD759CAFC`：event 2024-11-06，action 2024-11-07，5 日期末 20.95%，事后终态 CLEARED；图表 `outputs/validation/v04_phase4/688012.SH/annotated_chart.png`。
- **接近中位数** `600519.SH` / `FWARN-14ABBE7F21DAE621A60CCA6E49872C7A192C33D5C15030B41E9303143AA0B9C3`：event 2025-05-15，action 2025-05-16，5 日期末 -3.30%，事后终态 CLEARED；图表 `outputs/validation/v04_phase4/600519.SH/annotated_chart.png`。

### INVALIDATED

- **下跌较明显** `688072.SH` / `FWARN-472FB695B85516FC0A95D9A433D108A8438236EEB3B8CE99D94417B99C5C08E0`：event 2026-05-25，action 2026-05-26，5 日期末 -19.11%，事后终态 INVALIDATED；图表 `outputs/validation/v04_phase4/688072.SH/annotated_chart.png`。
- **上涨较明显** `688072.SH` / `FWARN-7AB085285099C6D13C22225128BEACEF6071A4CA9B9582D02BFB5FA25E0930FA`：event 2026-05-18，action 2026-05-19，5 日期末 37.28%，事后终态 INVALIDATED；图表 `outputs/validation/v04_phase4/688072.SH/annotated_chart.png`。
- **接近中位数** `300750.SZ` / `FWARN-7054ED634FD47D63545C55E1250A0AF28BAAC63ED41F21A9F0D1CD0575E930D0`：event 2024-10-11，action 2024-10-14，5 日期末 -0.04%，事后终态 INVALIDATED；图表 `outputs/validation/v04_phase4/300750.SZ/annotated_chart.png`。

## 样本文件、schema 与 checksum 核对

| symbol | name | sample_group | input_checksum_sha256 | display_bar_count | files_validation_passed | schema_validation_passed | checksum_validation_passed | linkage_validation_passed | error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 300308.SZ | 中际旭创 | AI_OPTICAL | 94f2f2f35fce6121e53a1019d8281b196b133ecd7bace1e7052aa9eb9def26e5 | 615 | 是 | 是 | 是 | 是 | — |
| 300502.SZ | 新易盛 | AI_OPTICAL | 62c85b5a7e070149295f486321f576098e12087b4503ace7f1d4403bfa1fd37f | 615 | 是 | 是 | 是 | 是 | — |
| 300394.SZ | 天孚通信 | AI_OPTICAL | d5e4e519dd895d4d3a756819cc475a493e91ecfc712469ac81537832e2e67b9f | 615 | 是 | 是 | 是 | 是 | — |
| 002463.SZ | 沪电股份 | PCB | 410a201b13a4ca7502d5386d2faadd15283800f07332ccdf423b7f8abd284c20 | 615 | 是 | 是 | 是 | 是 | — |
| 600183.SH | 生益科技 | PCB | 3ebafe6c3c78047bfbeb3de69ec3cdbdf6db36232e177732b1e0d0d7a5c47de6 | 615 | 是 | 是 | 是 | 是 | — |
| 688012.SH | 中微公司 | SEMICONDUCTOR_EQUIPMENT | de2cda9cb567b98f1d11387ca44472867dc924020396a92332b05746c02776b7 | 606 | 是 | 是 | 是 | 是 | — |
| 688072.SH | 拓荆科技 | SEMICONDUCTOR_EQUIPMENT | baed37823eadcbd7f8e5deeefa077f9cf45059237cbea15ae00b259707f59a1c | 605 | 是 | 是 | 是 | 是 | — |
| 300750.SZ | 宁德时代 | GROWTH_CYCLICAL | ec6be3d0a6cf07b7c8dee642009dd61fc105935d3aaac990b62bd69f89967897 | 615 | 是 | 是 | 是 | 是 | — |
| 300274.SZ | 阳光电源 | GROWTH_CYCLICAL | 9421cfd55826cc8c09e19afd2f70b28a7efcc8ef5be8f87874c2e08f0f70b6c5 | 615 | 是 | 是 | 是 | 是 | — |
| 601127.SH | 赛力斯 | GROWTH_CYCLICAL | 1a8c19182fbac8ab8b998cd0c928641a828418a0178c0db9ee7f5568021fc026 | 615 | 是 | 是 | 是 | 是 | — |
| 600519.SH | 贵州茅台 | LARGE_CAP_CONTROL | b197be054a8482a1a1561de1ede8f8870da17f741680be27fe54964b2bcbb968 | 615 | 是 | 是 | 是 | 是 | — |
| 601318.SH | 中国平安 | LARGE_CAP_CONTROL | 66ee6ad9b385b0452c0dbe7f297a58fc976f9eccadfc7f6afd47d6c955ee017a | 615 | 是 | 是 | 是 | 是 | — |

### 失败明细

- 无失败样本。

## 限制、稳健性与不可越过的解释边界

- action open 只是最早可执行价格代理；未验证真实成交量、涨跌停、滑点、交易成本或订单冲击。
- 所有 horizon 严格截断在 Phase 4 展示结束日；近期事件的不完整路径不进入分位数。
- OPENED 的主要统计没有使用未来终态；任何 ex-post 状态差异只可用于人工诊断，不能转化为实时信号。
- 报告使用精确审计表而不新增图；代表案例只引用 Phase 4 既有单股图表。

## Phase 5 决策门只记录证据，不实现规则

- **OPENED：**应继续保持 `position_effect=NONE`；无条件描述性路径不足以支持统一仓位动作。
- **ESCALATED：**具有唯一 formal linkage 和明确事件时点，值得进入下一阶段的仓位规则研究；现有分布尚未证明统一、稳定的短期风险方向，本阶段不实现规则。
- **INVALIDATED：**值得研究“取消风险降级”是否合理；本报告不实现恢复仓位逻辑。
- **CLEARED：**必须继续区分 OPENED 至 CLEARED 的既有路径与 CLEARED 之后路径；业务含义仍需结合逐案审阅。
- **人工审阅：**仍需重点检查极端 5 日案例、板块差异、action open 可成交性和小样本 CLEARED。

## 后续人工问题

- OPENED 的无条件分布是否在更长时间窗和不同市场状态下保持稳定？
- ESCALATED 的等待成本是否足以覆盖大量 INVALIDATED warning 的机会成本？
- INVALIDATED 与 CLEARED 的恢复含义能否在不引入未来信息的前提下定义？

## 全事件总体汇总

| 事件 | 样本组 | 交易日 | 事件数 | action date 可用 | 完整样本 | 期末中位数 | 最大中位数 | 最小中位数 | 期末 P25 | 期末 P75 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OPENED | ALL | 1 | 304 | 304 | 304 | 0.08% | 2.06% | -1.72% | -1.92% | 2.14% |
| OPENED | ALL | 3 | 304 | 304 | 304 | 0.24% | 4.03% | -3.21% | -3.47% | 4.97% |
| OPENED | ALL | 5 | 304 | 304 | 304 | 0.38% | 5.00% | -3.90% | -4.16% | 7.24% |
| OPENED | ALL | 10 | 304 | 304 | 303 | 1.18% | 9.47% | -5.52% | -5.56% | 8.79% |
| OPENED | ALL | 20 | 304 | 304 | 300 | 1.19% | 13.37% | -7.19% | -7.66% | 16.10% |
| ESCALATED | ALL | 1 | 140 | 140 | 140 | -0.25% | 2.13% | -1.67% | -1.94% | 1.78% |
| ESCALATED | ALL | 3 | 140 | 140 | 140 | -0.25% | 4.02% | -3.05% | -2.16% | 5.06% |
| ESCALATED | ALL | 5 | 140 | 140 | 140 | 0.30% | 5.33% | -4.11% | -3.34% | 7.45% |
| ESCALATED | ALL | 10 | 140 | 140 | 140 | 0.23% | 7.92% | -4.96% | -5.10% | 12.44% |
| ESCALATED | ALL | 20 | 140 | 140 | 137 | 1.78% | 13.29% | -6.33% | -4.26% | 17.90% |
| CLEARED | ALL | 1 | 26 | 26 | 26 | -0.10% | 1.73% | -2.27% | -1.66% | 1.06% |
| CLEARED | ALL | 3 | 26 | 26 | 26 | -0.57% | 2.24% | -3.72% | -2.85% | 4.56% |
| CLEARED | ALL | 5 | 26 | 26 | 26 | -2.60% | 2.89% | -4.86% | -5.54% | 3.89% |
| CLEARED | ALL | 10 | 26 | 26 | 26 | -1.05% | 5.47% | -6.86% | -7.55% | 6.36% |
| CLEARED | ALL | 20 | 26 | 26 | 25 | -7.25% | 6.52% | -10.90% | -14.75% | -1.79% |
| INVALIDATED | ALL | 1 | 138 | 138 | 138 | 0.58% | 2.54% | -1.75% | -1.44% | 2.13% |
| INVALIDATED | ALL | 3 | 138 | 138 | 138 | -0.01% | 5.03% | -3.25% | -3.31% | 4.45% |
| INVALIDATED | ALL | 5 | 138 | 138 | 138 | -0.10% | 5.45% | -4.50% | -3.79% | 5.36% |
| INVALIDATED | ALL | 10 | 138 | 138 | 137 | 1.00% | 8.03% | -5.76% | -5.79% | 8.30% |
| INVALIDATED | ALL | 20 | 138 | 138 | 137 | 2.12% | 13.41% | -7.15% | -8.16% | 17.08% |
