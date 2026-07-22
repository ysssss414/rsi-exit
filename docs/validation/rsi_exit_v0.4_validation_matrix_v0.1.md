# rsi-exit v0.4 预警层多样本验证矩阵（v0.1）

状态：`DRAFT`；用途：v0.4 Phase 0 验证规划。本文不指定真实股票，不下载数据，
不把新的私有行情数据提交仓库。

## 1. 验证对象与共同口径

验证对象是 `FORMING_DIVERGENCE_WARNING` 的追加式生命周期，而不是重新验证或修改
v0.3 正式背离定义。第一阶段不设 warning level，仓位效果固定为 `NONE`。

每个样本至少执行：

1. full analysis；
2. 对每个 warning 建立、刷新和终结日期的 prefix analysis；
3. 同输入重放两次；
4. warning 开关关闭时的 v0.3 输出对照；
5. warning 开关打开时的 v0.3 正式输出逐字段对照。

共同硬断言：

```text
observation_date <= decision_date <= available_date
第一阶段 observation_date = decision_date = available_date
warning_events 不包含 earliest_action_date 或 effective_date
同一 warning_event_id 只出现一次
终态 warning 不复活
prefix 事件集合等于 full 对应日期前缀
prefix/full 使用相同输入起点、配置和 symbol，仅改变截止日期
warning position_effect 恒为 NONE
warning 不产生 APPLY_SIGNAL_CAP / RESET_SIGNAL_DOMAIN
warning 不改变 divergence_count / divergence_chain_id / risk_cycle_id
warning 不改变 momentum_anchor / last_structural_peak / latest_confirmed_canonical
warning 不改变正式 position cap 或 S 状态
warning_events 与 AnalysisResult.warnings 内容和语义完全分离
formal escalation 不依赖 position_eligible
每个 formal signal 最多匹配一个 warning chain
每个 warning chain 最多升级到一个 formal signal
linked_formal_signal_ref 可由现有正式字段复算
deep reset 终结为 INVALIDATED，只有 anchor breakout 可产生 CLEARED
```

用户展示层对同一 `warning_id` 最多显示一个当前对象；`REFRESHED` 版本只在审计明细展开，
防止连续上升日形成事件洪水。独立审计文件固定为 `warning_events.csv`；现有
`AnalysisResult.warnings: list[str]` 继续只表示系统运行、数据质量和配置类警告。

## 2. 样本清单

实际 symbol、name 和日期由后续获准的数据任务填写。`TBD_PRIVATE` 表示数据不进入仓库；
可提交的测试只使用人工合成或脱敏 fixture。

| symbol | name | date_start | date_end | scenario_type | expected_anchor_count | expected_formal_divergence_count | expected_warning_behavior | negative_control | data_status | notes |
|---|---|---|---|---|---:|---:|---|---|---|---|
| `TBD_PRIVATE_A` | 待定 | 待定 | 待定 | A 强趋势、多次背离 | `>=1` | `1/2/3` 连续出现 | 每个可评估正式背离至多匹配一个先行 warning；不重复计数 | 同期同步走强区段不得预警 | 待补充 | 需要覆盖一背至三背 |
| `TBD_PRIVATE_B` | 待定 | 待定 | 待定 | B 强趋势、无背离 | `>=1` | `0` | `0 OPENED`，除非输入确有冻结条件的 forming | 全区间为负控 | 待补充 | 价格和 RSI 同步创新高 |
| `TBD_PRIVATE_C` | 待定 | 待定 | 待定 | C 高位横盘 | `>=1` | `0` 或少量 | 仅硬 forming 条件成立才开；不因“横盘”标签开 | 不满足双 RSI 阈值的横盘段 | 待补充 | 检查事件数量和解除 |
| `TBD_PRIVATE_D` | 待定 | 待定 | 待定 | D 单峰快速回落 | `>=1` | `0` | 最多一个 forming chain；随后 `INVALIDATED` | 无第二可比结构峰 | 待补充 | 不得伪造背离链 |
| `TBD_PRIVATE_E` | 待定 | 待定 | 待定 | E 假突破后回落 | `>=1` | `0` | `INTRADAY_POTENTIAL_RETEST` 本身不建立 warning | 收盘未进入可比区 | 待补充 | 只能审计、零仓位资格 |
| `SYNTHETIC_F` | canonical v1/v2/v3 | 待定 | 待定 | F canonical 连续更新 | `>=1` | 按 fixture | 同版本去重；旧组不复活；终态不回写 | 迟到旧版本 | 可合成 | 必须覆盖 latest lineage |
| `TBD_PRIVATE_G` | 待定 | 待定 | 待定 | G 深度 reset | `>=2`（reset 前后） | 按样本 | 旧 warning 在阈值首次完成日 `INVALIDATED / DEEP_RSI_RESET_COMPLETED`；新周期使用新 id | 49 单日、49/50/49、40.1 | 待补充 | 不得显示趋势重新转强 |
| `TBD_PRIVATE_H` | 待定 | 待定 | 待定 | H 震荡噪声 | 可多 | `0` 或少量 | warning chain 数不超过唯一 forming id 数；摘要不重复显示版本 | 频繁小高点无双 RSI 条件 | 待补充 | 衡量事件洪水 |

## 3. 分类型验证矩阵

### A. 强趋势、多次背离

| 项目 | 要求 |
|---|---|
| 走势类型 | 价格持续创新高，RSI 逐级下降，出现第 1、2、3 次正式背离 |
| 正样本要求 | 至少一个完整 momentum anchor；三次正式背离均有完整前一日/确认日/行动日 |
| 负样本要求 | 同一趋势内至少一段价格与 RSI 同步走强，或 structural-without-divergence |
| 关键断言 | warning 不早于其形成条件；正式确认时匹配至多一个 ACTIVE chain；formal count 仍为 1/2/3；第三背前 warning 不强制 S3 |
| 数据范围 | anchor 建立前至少 30 个交易日，第三背确认后至少 5 个交易日 |
| 通过标准 | 所有可评估正式背离的匹配唯一；无重复 warning event；v0.3 正式输出与关闭 warning 时一致 |
| 失败标准 | warning 使用确认日之后信息；一个正式背离匹配多个 chain；warning 改变 count/cap/S 状态 |

### B. 强趋势、无背离

| 项目 | 要求 |
|---|---|
| 走势类型 | 价格和 RSI 持续同步创新高 |
| 正样本要求 | 至少三个确认结构峰和一个 anchor breakout |
| 负样本要求 | 全区间均不满足 local 与 anchor 双 RSI 下降 |
| 关键断言 | `STRICT_NEW_HIGH` 本身不建立 warning；anchor breakout 可清除旧 warning 但不建立新 warning |
| 数据范围 | 不少于 60 个交易日，覆盖至少三个独立 canonical |
| 通过标准 | 双 RSI 条件未成立的区段 `OPENED=0` |
| 失败标准 | 因创新高、RSI 高位或 S1 状态持续提示顶部风险 |

### C. 高位横盘

| 项目 | 要求 |
|---|---|
| 走势类型 | 价格维持可比区，RSI 逐渐下降，没有明显严格新高 |
| 正样本要求 | 至少两次 `FORMAL_NEAR_HIGH_RETEST` 或盘中触及 |
| 负样本要求 | 至少一段 local RSI 降幅小于 1.0，或只满足 anchor 条件 |
| 关键断言 | 不因“高位横盘”文本标签建立事件；仅现有 `DIVERGENCE_FORMING` 硬条件可开 |
| 数据范围 | 横盘前含 anchor，横盘不少于 15 个交易日，突破或回落后不少于 5 日 |
| 通过标准 | 未满足双 RSI 条件的横盘段无 warning；活动 warning 有唯一下一日结局 |
| 失败标准 | 引入未批准的横盘窗口、评分或永久 ACTIVE warning |

### D. 单峰快速回落

| 项目 | 要求 |
|---|---|
| 走势类型 | 没有第二个可比确认结构峰，单峰后直接深度回调 |
| 正样本要求 | 峰日可选择满足 forming 条件，以验证失效/解除 |
| 负样本要求 | 不存在正式第二结构峰和正式背离 |
| 关键断言 | warning 不建立 structural peak，不增加 count；下一日条件中断时终结 |
| 数据范围 | 峰前 30 日、峰后至少覆盖一次 reset 完成 |
| 通过标准 | formal divergence count 保持 0；warning 最多一个 chain 并有因果终态 |
| 失败标准 | 伪造 previous/anchor、背离链或卖出动作 |

### E. 假突破后回落

| 项目 | 要求 |
|---|---|
| 走势类型 | 盘中触及可比区或前高，收盘未站上可比区下沿 |
| 正样本要求 | 至少一个确认的 `INTRADAY_POTENTIAL_RETEST` |
| 负样本要求 | 无 `STRICT_NEW_HIGH`，无正式近高收盘，或 RSI 双验证不成立 |
| 关键断言 | `INTRADAY_POTENTIAL_RETEST` 仅留在 v0.3 audit；不能单独 OPEN warning |
| 数据范围 | 前一结构峰前一交易日到假突破确认后至少 5 日 |
| 通过标准 | 该事件的 warning/cap/count/state 增量全部为 0 |
| 失败标准 | 盘中触及被解释为正式顶部风险或进入仓位 |

### F. canonical 连续更新

| 项目 | 要求 |
|---|---|
| 走势类型 | 同一 canonical 依次出现 v1、v2、v3，并有更新 canonical 分组 |
| 正样本要求 | 当前 latest 分组的合法递增版本；至少一个 forming v1/v2/v3 chain |
| 负样本要求 | 同版本重放；更新分组出现后的旧 canonical 迟到版本 |
| 关键断言 | warning 事件不可变；同版本去重；终态不复活；旧 lineage 不得新开或升级 |
| 数据范围 | 覆盖版本形成前、每次确认日和更新分组确认后 |
| 通过标准 | prefix/full 逐字段一致；每个 event id 唯一；历史 warning 内容不变 |
| 失败标准 | canonical 更新回写旧 warning；迟到版本重开；重放增加行数 |

### G. 深度 reset

| 项目 | 要求 |
|---|---|
| 走势类型 | RSI 严格 `<50` 连续 3 个交易日，或单日 `<=40` |
| 正样本要求 | 两种 reset 路径各至少一个；reset 前有 ACTIVE warning |
| 负样本要求 | 单日 49；49/50/49；最低 40.1 |
| 关键断言 | 第三日或 `<=40` 当日收盘后才 `INVALIDATED / DEEP_RSI_RESET_COMPLETED`；不得提前；新 forming 使用新 warning id |
| 数据范围 | reset 前至少 10 日，完成后至少至下一个结构峰确认 |
| 通过标准 | 正边界全部终止且显示“预警因 RSI 深度重置终止”；负边界全部不终止；v0.3 divergence/risk 生命周期不被 warning 反向写入 |
| 失败标准 | 50 使用 `<=`、40 使用 `<`、“即将 reset”提前触发，或显示“风险解除/动能恢复” |

### H. 震荡噪声

| 项目 | 要求 |
|---|---|
| 走势类型 | 频繁小高点，无持续主趋势，价格多次不可比 |
| 正样本要求 | 可含少量真正满足双 RSI 的 forming，以验证折叠和失效 |
| 负样本要求 | 大量 `NON_COMPARABLE_PEAK`、单条件 RSI 下降和盘中触及 |
| 关键断言 | 非 forming 事件不建 warning；一个 forming id 只有一个用户可见 chain；刷新版本不重复弹窗 |
| 数据范围 | 不少于 120 个交易日，包含至少 10 个 candidate peak |
| 通过标准 | `warning_id` 数 `<=` 唯一满足条件的 forming id 数；展示活动数 `<=` 审计活动 chain 数；无重复 event id |
| 失败标准 | warning 数随所有小高点线性增长；同一 forming 版本重复；非可比峰形成事件洪水 |

## 4. 因果与不可变性专项

| 测试 | 方法 | 通过标准 |
|---|---|---|
| 当日因果 | 截断在每个 OPENED 日 | evidence 不含后续 confirm/canonical/终态 |
| 次日转换 | 分别构造延伸、正式确认、非正式确认和混合涨跌 | 只走一个固定优先级转换 |
| prefix/full | 对每个事件日做前缀，和完整结果按日期过滤比较 | DataFrame 逐字段相等 |
| 重放 | 同一输入和同一事件重复处理 | 行数、状态、哈希不变 |
| canonical 更新 | 保存事件后推进 v2/v3 | 旧事件对象和值不变 |
| 迟到旧组 | 新 canonical 确认后投递旧组更新 | 不开、不刷、不升级、不复活 |
| 输出顺序 | 打乱等价输入投递顺序后按规定排序 | 序列化输出一致 |
| source contract | 构造 signal type/status/relation 合法但安全不变量损坏的 forming fact | 明确报数据合同失败，不建立 warning，不静默重算 |
| formal position independence | 构造 `position_eligible` 不同、其他正式身份相同的 formal fact | matcher 结果完全相同，不修改 v0.3 正式输出 |
| formal 匹配基数 | 分别构造 0、1、2 个满足谓词的 formal facts | 0 个走其他终止、1 个升级、2 个明确报合同错误 |
| formal 引用 | 从已有 symbol/type/canonical/version/date/chain 复算引用 | 与 `ESCALATED.linked_formal_signal_ref` 完全一致 |
| symbol 隔离 | 两个 symbol 使用相同 forming id 和 chain id | warning_id 不碰撞，跨标的不匹配 |
| deep reset 语义 | reset 与 formal 同日、以及 reset 单独完成各一例 | 同日 formal 优先；reset 单独完成只产生 INVALIDATED |

## 5. 仓位和状态隔离专项

对每个 A–H 样本，warning 功能关闭结果记为 control，打开结果记为 treatment。以下表必须
逐字段相等，而不是只比较行数：

- 正式 `signals` 中除未来新增 warning 引用列外的全部 v0.3 字段；
- `daily_features` 的 decision/effective base、signal、final cap；
- `state_log` 的 S 状态、trigger、position cap；
- `cycle_log` 的 risk cycle/reset；
- 正式 structural/canonical/anchor/last structural/divergence chain 序列；
- `AnalysisResult.warnings` 的内容、顺序、类型和语义；
- v0.3.0 冻结样本的所有冻结断言和 ZIP SHA-256。

`warning_events` 是 treatment 新增的独立 DataFrame；它不得替换或复用
`AnalysisResult.warnings`，其序列化文件只能命名为 `warning_events.csv`。

任一差异均为阻断失败，不能以“预警更准确”为理由接受。

## 6. 数据范围与数据治理

- 每个真实样本必须包含足够 warmup，不能从首个目标峰当天起算。
- 日期必须是真实交易日序列；不能用自然日补齐 reset 或间隔。
- OHLCV 与 RSI 输入口径必须记录，但私有原始行情不提交仓库。
- 可提交 fixture 只能是人工合成或脱敏序列，并明确其预期事件。
- 不使用 300308.SZ 单样本调参数；该样本只承担冻结兼容和一个 A 类回归角色。
- 本文的 symbol/name/date 均为占位，后续补样本必须单独审核数据授权。

## 7. 总体通过与失败标准

全部通过需同时满足：

1. A–H 每类至少一个样本，且 B/E/H 有明确负控；
2. 所有共同硬断言为真；
3. 全部 prefix/full、重放、lineage 专项通过；
4. v0.3 正式输出 control/treatment 等价；
5. warning 活动、升级、解除、失效均能由原因码和证据复算；
6. 无私有行情或重新生成的 v0.3 冻结 ZIP 进入提交。

出现以下任一项即总体失败：未来数据、重复事件、终态复活、事件洪水、无明确原因的状态
变化、warning 影响正式 count/chain/cycle/cap/S 状态，或为了单只股票增加日期特例。
