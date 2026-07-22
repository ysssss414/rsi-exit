# rsi-exit v0.4 预警与持仓去偏层规格草案（v0.1）

状态：`DRAFT`；阶段：`v0.4 Phase 0`；本文件不构成业务代码、仓位规则或版本发布。

设计基线是 v0.3.0 Release commit `49c8323218226ee1ec3e14f52fe951b533333315`。
v0.3.0 tag、Release、冻结输出和既有业务语义均不可由本规格改写。

## 0. 决策摘要

- 一句话定义：**预警不是正式背离，而是在当日已知数据上已经满足正式背离的价格可比、
  相邻峰 RSI 走弱和动能锚 RSI 走弱条件，但当前峰尚未得到次日确认的、只用于审计和
  持仓去偏提示的因果观察。**
- v0.4 第一阶段只批准一种预警：`FORMING_DIVERGENCE_WARNING`，输入必须是 v0.3 的
  `DIVERGENCE_FORMING`。
- 采用追加式 `WarningEvent`，当前状态由事件历史派生；不把可变状态回写到旧事件。
- 第一阶段不采用 W0/W1/W2/W3 等级。`W0` 只是没有活动预警，`W3` 与正式背离重复，
  `W1/W2` 需要尚未通过多样本验证的新阈值。
- 生命周期状态为 `ACTIVE`、`ESCALATED`、`CLEARED`、`INVALIDATED`。`OBSERVING` 与
  `ACTIVE` 在唯一硬触发条件下没有可验证差异，暂不采用。
- 正式背离确认时追加 `ESCALATED` 事件并终结活动状态，完整 warning chain 永久保留。
- 第一阶段 `position_effect = NONE`：不生成或修改正式 position cap，不进入 S 状态机。

## 1. 问题定义

v0.3 已能在 canonical peak 确认后产生正式顶部背离，并已有 `DIVERGENCE_FORMING`
因果快照；但 forming 行目前主要是信号审计项，没有独立生命周期、明确解除原因或面向
持仓者的去偏表达。v0.4 要回答的是：在不污染正式背离链、风险周期、仓位和状态机的
前提下，如何把这类尚未确认的客观事实显示为可追踪、可解除、可复核的预警。

预警必须同时满足：

1. 只使用决策时点已经可见的数据；
2. 由布尔条件建立，不使用主观评分；
3. 有唯一、可执行的终止规则；
4. 与正式背离、仓位、S1/S2/S3 完全隔离；
5. 在前缀运行和完整运行中保持同一历史前缀；
6. 正样本和负样本具有同等约束力。

## 2. 非目标

本规格不做以下事项：

- 不修改 v0.3.0 的顶部背离定义、阈值、可比区、canonical 或 reset 语义；
- 不把 `DIVERGENCE_FORMING` 改成正式 structural peak 或正式背离；
- 不预测顶部、收益率、回撤幅度或卖出价格；
- 不引入加权评分、百分制风险分数、机器学习或个股日期特例；
- 不为“RSI 看起来偏弱”“高位横盘”等描述直接生成事件；
- 不下载、提交或推断新的私有行情数据；
- 不承诺预警直接或间接改变正式仓位；
- 不修改 `config/rsi_exit_v03.yaml` 或 v0.3.0 冻结 ZIP。

## 3. 现状审查与候选输入

### 3.1 已审查的调用链

- `PeakDetector._build_forming_events` 只使用当日与前一交易日的 close/RSI；连续双升时
  产生同一 forming id 的递增版本，不读取后续确认日。
- `DivergenceTracker.preview_forming` 要求价格关系属于 `STRICT_NEW_HIGH` 或
  `FORMAL_NEAR_HIGH_RETEST`，并同时满足相邻结构峰和 momentum anchor 的 RSI 下降
  阈值；函数不修改 tracker。
- pipeline 把 forming 行固定标为 `position_eligible=false`，不安排
  `APPLY_SIGNAL_CAP`，也不调用正式背离计数路径。
- 正式 canonical 的不可变键是 `(canonical_peak_id, canonical_version)`；同版本重放
  忽略，旧 canonical 的迟到更新不能夺回 latest lineage 或 momentum anchor。
- 正式仓位只由两类正式背离经 `divergence_position_rule` 和 `SignalCapQueue` 进入；
  第三次正式背离才可强制 S3。

### 3.2 候选事件评估

| 候选 | 因果可确认 | 稳定性/噪声 | 与正式背离关系 | 明确解除条件 | v0.4 v0.1 决定 |
|---|---|---|---|---|---|
| `DIVERGENCE_FORMING` | 是；当日 close 后即可确定 | 版本化但单个快照稳定，噪声可由失效事件显式记录 | 是正式背离的未确认前置条件，不增加 count | 下一交易日可延伸、升级或失效 | **唯一建立输入** |
| `INTRADAY_POTENTIAL_RETEST` | 是，但需 canonical 确认 | 仅盘中触及、收盘拒绝，价格噪声较高 | 明确不具结构和仓位资格 | 没有天然持续对象 | 仅审计/负样本，不建立预警 |
| `FORMAL_NEAR_HIGH_RETEST` | 是 | 只是价格关系，不包含 RSI 走弱 | 可能对应正式背离或无背离结构峰 | 依赖 RSI 结果 | 只作为 warning evidence |
| `STRICT_NEW_HIGH` | 是 | 强趋势中频繁出现 | 价格创新高本身不是顶部风险 | 价格单独无合理解除语义 | 只作为 warning evidence |
| `STRUCTURAL_PEAK_WITHOUT_DIVERGENCE` | 是 | 含 RSI 走强、持平和单条件失败等异质情况 | 按定义不是正式背离 | 无统一解除条件 | 不建立预警；可用于清除/失效证据 |
| `ANCHOR_RSI_BREAKOUT` | 是 | `+2.0` 闭区间边界明确 | 表示动能锚重建，与顶部风险方向相反 | 自身即为终止事实 | 只作为 `CLEARED` 原因 |
| `NON_COMPARABLE_PEAK` | 是 | 低位小峰可能很多 | 不进入结构链 | 不应单独切断正式链 | 不建立预警；匹配 forming 失败时可作 `INVALIDATED` 证据 |

### 3.3 其他形态评估

| 形态 | 结论 | 原因 |
|---|---|---|
| RSI 从高位回落但未形成结构峰 | 暂不预警 | 缺少可比较的价格结构和自然的对象身份，易把普通回撤当顶部风险 |
| 价格创新高但 RSI 差值未达到 1.0 | 暂不预警 | 等价于改变 v0.3 已冻结阈值；应先作为负样本验证渐弱假设 |
| 价格进入可比区但收盘未站上可比区下沿 | 暂不预警 | 这是 `INTRADAY_POTENTIAL_RETEST`，收盘拒绝使信号不稳定 |
| 连续多个结构峰 RSI 下降但尚未满足双重背离 | 研究候选 | 需要序列长度和累计下降新参数，当前没有无过拟合的硬条件 |
| 高位横盘期间 RSI 逐步走弱 | 研究候选 | “高位”“横盘”“逐步”均需新增窗口，且与 S1/S2 解释空间重叠 |
| 深度 reset 即将发生但尚未完成 | 不预警 | “即将”没有冻结边界；仅在 reset 实际完成时终止现有预警 |

以上决定不表示这些形态永久无价值，只表示它们不能在 v0.4 第一阶段绕过多样本负控
验证成为持仓提示。

## 4. 事件模型

### 4.1 追加式 WarningEvent

`WarningEvent` 是不可变审计记录，不是直接可变的数据库行。一个逻辑 warning chain
可以有多个事件；当前状态由截至分析时点的最后一个合法事件派生。

建议字段如下：

| 字段 | 必需 | 语义 |
|---|---:|---|
| `symbol` | 是 | 标的身份；进入 warning 与 warning event 的确定性身份 |
| `warning_event_id` | 是 | 单个不可变生命周期事件的确定性身份 |
| `warning_id` | 是 | 同一 forming 尝试的逻辑 warning chain 身份 |
| `warning_type` | 是 | 第一阶段固定为 `FORMING_DIVERGENCE_WARNING` |
| `lifecycle_event` | 是 | `OPENED`、`REFRESHED`、`ESCALATED`、`CLEARED`、`INVALIDATED` |
| `warning_status` | 是 | 该事件之后的派生状态 |
| `source_kind` | 是 | 第一阶段固定为 `FORMING_PEAK`，终结事件可引用 `FORMAL_SIGNAL`/`DAILY_RSI` |
| `source_peak_id` | 是 | forming peak id；刷新时保持同一 id |
| `source_version` | 是 | forming version；终结事件保留最后活动版本 |
| `source_canonical_peak_id` | 否 | 正式确认后才可填入，不得事后回写旧事件 |
| `source_canonical_version` | 否 | 与上同 |
| `source_peak_date` | 是 | 当次 forming 快照的峰日 |
| `observation_date` | 是 | 原始事实可见日 |
| `decision_date` | 是 | 系统追加本事件的日期 |
| `available_date` | 是 | 最早可以报告、序列化或展示的日期，不具有交易执行含义 |
| `momentum_anchor_id/version` | 是 | 建立时的不可变 anchor 快照 |
| `last_structural_peak_id/version` | 是 | 建立时的不可变 last structural 快照 |
| `latest_confirmed_canonical_id/version` | 否 | 决策时 lineage 快照，用于拒绝迟到旧组 |
| `divergence_chain_id` | 是 | 只读上下文，不可由 warning 修改 |
| `risk_cycle_id` | 是 | 只读上下文，不可由 warning 修改 |
| `price_relation` | 是 | `STRICT_NEW_HIGH` 或 `FORMAL_NEAR_HIGH_RETEST` |
| `local_rsi_delta` | 是 | 当前 RSI - last structural RSI |
| `anchor_rsi_delta` | 是 | 当前 RSI - momentum anchor RSI |
| `warning_reason` | 是 | 机器可读原因码，不使用自由文本决策 |
| `warning_evidence` | 是 | 用于展示的结构化证据，不参与额外评分 |
| `end_reason` | 否 | 升级、解除或失效原因码 |
| `linked_formal_signal_ref` | 否 | 只在 `ESCALATED` 终结事件中保存的确定性正式信号引用 |
| `position_effect` | 是 | 第一阶段固定为 `NONE` |
| `recommended_position_cap` | 否 | 第一阶段必须为 null |

原候选字段 `warning_level` 不采用；`invalidated_date` 由终结事件的 `decision_date`
表达，避免回写 `OPENED`。`clear_condition` 应在规格/原因码中固定，而不是每行自由文本。

### 4.2 身份与去重

不采用候选键 `(warning_type, canonical_peak_id, canonical_version, decision_date)`，因为
forming 时尚无正式 canonical id，而且该键无法区分同一 warning 的刷新和终结事件。

建议确定性身份：

```text
warning_id = (
  symbol,
  warning_type,
  source_forming_peak_id,
  divergence_chain_id,
  momentum_anchor_id, momentum_anchor_version,
  last_structural_peak_id, last_structural_peak_version
)

warning_event_id = (
  warning_id,
  lifecycle_event,
  source_version,
  decision_date
)
```

同一 `warning_event_id` 重放必须返回已有事件或无操作，不能追加第二行。forming 版本增加
时追加 `REFRESHED`，不能改写 `OPENED`。

prefix/full 一致性的验证边界固定为：相同输入起点、相同配置、相同 `symbol`，仅改变
分析截止日期。不要求改变现有 forming id 生成规则。

### 4.3 输出命名与 AnalysisResult 兼容

现有 `AnalysisResult.warnings: list[str]` 表示系统运行、数据质量和配置类警告，不是交易
预警事件。该字段名称、类型和语义必须保持不变。

未来 Phase 1 可在保持原字段不变的前提下新增：

```python
warning_events: pd.DataFrame
```

正式独立输出文件固定为 `warning_events.csv`。全文中的 `warning_events` 均指 v0.4
`FORMING_DIVERGENCE_WARNING` 生命周期事件；不得使用 `warnings.csv`，也不得把
`AnalysisResult.warnings` 替换为 DataFrame。

## 5. 状态模型

### 5.1 状态和转换

| 当前状态 | 输入 | 下一状态 | 说明 |
|---|---|---|---|
| 无 | 建立条件成立 | `ACTIVE` | 追加 `OPENED` |
| `ACTIVE` | 同一 forming id 的更高版本仍满足条件 | `ACTIVE` | 追加 `REFRESHED` |
| `ACTIVE` | 匹配的正式背离确认 | `ESCALATED` | 终态；保留完整历史 |
| `ACTIVE` | 已确认 anchor breakout | `CLEARED` | 终态；客观动能锚已经重建 |
| `ACTIVE` | deep RSI reset 完成 | `INVALIDATED` | 终态；背离域结束，不表示风险解除或趋势转强 |
| `ACTIVE` | forming 条件中断且未形成匹配正式背离 | `INVALIDATED` | 终态；表示该次尝试未成熟 |
| 任一终态 | 迟到、重放或旧 lineage 输入 | 不变 | 禁止复活 |

`ESCALATED`、`CLEARED`、`INVALIDATED` 都是终态。新预警必须由新的 forming id 和新的
`warning_id` 建立。

### 5.2 不采用等级

- `W0` 可由“无 ACTIVE warning”直接表达，不应写事件。
- `W1 = 动能观察` 目前没有不引入窗口/累计阈值的唯一条件。
- `W2 = 明确预警` 与本规格唯一 warning 等价，额外标签无信息增益。
- `W3 = 等待正式背离确认` 也与 `ACTIVE` 等价；正式确认后应是正式背离而不是更高
  warning level。

因此第一阶段仅显示“活动预警/已升级/已解除/已失效”，不显示数值或级别。多样本验证
若证明渐弱序列有独立价值，再以新 `warning_type` 提案，而不是先增加模糊等级。

## 6. 建立与刷新条件

### 6.1 OPENED 业务触发条件

在交易日 `t` 收盘后，以下条件全部为真时建立：

```python
source.signal_type == "DIVERGENCE_FORMING"
source.signal_status == "FORMING"
source.price_relation in {"STRICT_NEW_HIGH", "FORMAL_NEAR_HIGH_RETEST"}
```

warning 层只消费 v0.3 已产生的 `DIVERGENCE_FORMING` fact，不得重新计算价格关系、
momentum anchor、last structural 或背离阈值，也不得实现第二套背离检测器。

### 6.2 source contract assertions

以下是来源完整性和安全断言，不是新的业务检测规则：

```python
source.local_rsi_delta <= -1.0
source.anchor_rsi_delta <= -1.0
source.structural_eligible is False
source.position_eligible is False
source.pending_action_type is None
```

`local_rsi_delta` 和 `anchor_rsi_delta` 原值作为不可变 evidence 保存。如果现有
`DIVERGENCE_FORMING` 行违反任一断言，不得建立 warning；实现必须抛出明确一致性错误
或记录数据合同失败，不能静默重算或重新分类。同一 `warning_event_id` 是否已输出属于
幂等去重，不属于业务触发条件。

日期固定为：

```text
observation_date = decision_date = available_date = t
position_effect = NONE
```

`WarningEvent` 不包含交易有效日，不进入 `SignalCapQueue` 或 base pending queue，不生成
`effective_date`，也不生成 `earliest_action_date`。若未来 Phase 5 批准仓位建议，必须在
独立规格中新增独立字段；不得回溯修改 Phase 1 历史事件。

### 6.3 REFRESHED

日期 `t+1` 只在以下条件全部为真时刷新同一 warning：

```python
source.forming_peak_id == active.source_peak_id
source.forming_version > active.source_version
source.signal_type == "DIVERGENCE_FORMING"
source.signal_status == "FORMING"
source.price_relation in {"STRICT_NEW_HIGH", "FORMAL_NEAR_HIGH_RETEST"}
all(source_contract_assertions)
```

刷新只更新派生视图中的“最新证据”；旧事件、原 observation date 和原版本保持不变。

## 7. 升级、解除与失效条件

### 7.1 转换优先级

同一决策日若多个条件同时出现，固定优先级为：

```text
ESCALATED > CLEARED_BY_ANCHOR_BREAKOUT > REFRESHED > INVALIDATED
```

每个 warning 在一个决策日最多追加一个生命周期事件。

### 7.2 ESCALATED：正式背离确认

正式信号 `f` 必须满足：

```python
f.symbol == active.symbol
f.signal_type in {
    "NEW_HIGH_BEARISH_DIVERGENCE",
    "NEAR_HIGH_BEARISH_DIVERGENCE",
}
f.signal_status == "FORMAL"
f.structural_eligible is True
f.current_peak_date == active.latest_source_peak_date
f.previous_canonical_peak_id == active.last_structural_peak_id
f.previous_canonical_version == active.last_structural_peak_version
f.momentum_anchor_canonical_id == active.momentum_anchor_id
f.momentum_anchor_canonical_version == active.momentum_anchor_version
f.divergence_chain_id == active.divergence_chain_id
active.latest_decision_date < f.decision_date
```

matcher 必须先取得满足上述谓词的集合：0 个匹配时按其他终止条件处理；1 个匹配时追加
`ESCALATED`；超过 1 个匹配时视为数据合同错误，不得任意选择第一条。当前 v0.3 正式
背离通常 `position_eligible=True`，但该字段不是 warning 升级身份的一部分。

匹配关系必须全局一对一：每个 formal signal reference 最多消费一个 warning chain，
每个 warning chain 最多追加一个 `ESCALATED`。若同一 formal fact 同时匹配多个活动
warning，同样属于数据合同错误，不能按当前行顺序选择。

活动状态必须保存最后一个 forming 版本的 `latest_source_peak_date`、
`latest_source_version` 和 `latest_decision_date`。匹配依赖的不可变上下文为 `symbol`、峰日、
last structural canonical id/version、momentum anchor canonical id/version、divergence chain
以及正式 decision date 晚于最后 forming decision date。本阶段不修改 `FormingPeakEvent`、
`Peak`、`CanonicalPeak` 或 `signals.csv`，也不增加持久化 forming→canonical 映射字段。

满足时追加 `ESCALATED`，仅在该终结事件中填入正式 canonical id/version 和
`linked_formal_signal_ref`；不得回写 `OPENED/REFRESHED`。引用由现有正式字段确定性组成：

```text
{symbol}|{signal_type}|{current_canonical_peak_id}@v{current_canonical_version}|{decision_date}|{divergence_chain_id}
```

也可保存为对应的五个结构化字段：formal signal type、canonical id/version、decision
date 和 divergence chain id。不得使用随机 UUID、DataFrame 行号或运行顺序，不得要求
v0.3 `signals.csv` 新增 `signal_id`。warning 不增加 count；count 只由正式背离原路径
增加。`ESCALATED` 之后不再追加其他终态，历史链保留用于衡量提前量和误报率。

### 7.3 CLEARED：anchor breakout 重建动能锚

只有已确认、属于当前 latest lineage 的 `ANCHOR_RSI_BREAKOUT` 才追加：

```text
lifecycle_event = CLEARED
warning_status = CLEARED
end_reason = MOMENTUM_ANCHOR_REBUILT
```

含义固定为：客观动能锚已经重建，原 forming 顶部风险观察不再成立。

价格与 RSI 同步创新高只有在它已经触发上述 `ANCHOR_RSI_BREAKOUT` 时作为解除原因；
不另设“看起来重新强化”的容差。超过最大观察窗口不采用：forming 生命周期已有自然的
下一日延伸/确认/中断边界，新增任意超时参数没有必要。

### 7.4 INVALIDATED：forming 尝试未成熟

从 warning observation date 之后的每日 RSI 首次满足 v0.3 冻结深度 reset（连续 3 个
真实交易日 RSI 严格小于 50，或任一日 RSI 小于等于 40）时追加：

```text
lifecycle_event = INVALIDATED
warning_status = INVALIDATED
end_reason = DEEP_RSI_RESET_COMPLETED
```

含义固定为：原 forming 尝试未升级为正式背离，但背离域因 RSI 深度重置而结束。这不
表示价格风险消失或趋势转强。用户文案固定为“预警因 RSI 深度重置终止”，不得显示为
“风险已解除”“动能恢复”或“预警解除”。若同日也确认正式背离，`ESCALATED` 优先，
deep reset 只作为同日上下文，不改变 warning 终态。

对最后活动快照 `(close_t, rsi_t)`，下一真实交易日 `u`：

- 若 `close_u > close_t` 且 `rsi_u > rsi_t`，由更高 forming 版本走 `REFRESHED`；
- 若 `close_u < close_t` 且 `rsi_u < rsi_t`，该峰进入 confirmed-candidate 路径：匹配
  正式背离则 `ESCALATED`；否则 `INVALIDATED`，原因记录实际确认结果，如
  `CONFIRMED_WITHOUT_FORMAL_DIVERGENCE`、`INTRADAY_RETEST_ONLY` 或
  `NON_COMPARABLE_CONFIRMATION`；
- 其他组合（含相等）直接 `INVALIDATED`，原因 `FORMING_CONDITION_BROKEN`。

数据区间在活动 warning 当日结束时保持 `ACTIVE_AT_CUTOFF` 派生状态，不可利用完整数据
把前缀输出中的旧事件回写为失效。

## 8. 因果约束

所有事件满足：

```text
observation_date <= decision_date <= available_date
```

第一阶段三者相等且无交易动作。`WarningEvent` 没有 `earliest_action_date` 或
`effective_date`。终结事件的 observation date 是终结事实首次可见日，
不得写成原 warning 的日期。

- forming 建立只读取当日及此前数据；次日是否确认不能出现在 `OPENED` evidence 中。
- 正式背离只在其既有 confirm/decision date 触发 `ESCALATED`。
- 深度 reset 只在第三个 `<50` 日收盘后或 `<=40` 当日收盘后触发。
- 交易日缺失、RSI 缺失或数据尚未到达时不得推测终结结果。
- 报告可计算“最终状态”，但必须同时提供 as-of date；不能把最终标签伪装成当时已知事实。

## 9. 不可变性、lineage 与重放

1. 每个 `WarningEvent` append-only；终结通过新事件表达。
2. 同一 `warning_event_id` 重放不得重复输出。
3. 同一 forming id 的新版本只能 `REFRESHED`，不能重写早期 RSI、价格或日期。
4. canonical 版本更新后，旧 warning 中的 anchor、last structural、latest canonical
   快照保持不变。
5. 已终结 warning 永不重开。迟到的旧 canonical 更新只能进入既有 v0.3 audit，不能
   产生新的 warning 生命周期事件。
6. 任何 canonical 终结输入必须在当时满足 v0.3 的 latest lineage 约束；旧组不能复活。
7. prefix run 在截止日 `T` 生成的 WarningEvent 集合，必须与 full run 中
   `decision_date <= T` 的集合逐字段一致。full run 只能在 `T` 之后追加事件。
8. 排序固定为 `(decision_date, warning_id, lifecycle_event, source_version)`，避免重放
   顺序改变输出哈希。

## 10. 与 v0.3 正式状态隔离

以下是无例外不变量：

```text
warning 不增加 divergence_count
warning 不建立正式 structural peak
warning 不修改 momentum_anchor
warning 不修改 last_structural_peak
warning 不推进 latest_confirmed_canonical
warning 不新建、关闭或重置 divergence_chain_id
warning 不新建、关闭或重置 risk_cycle_id
warning 不触发 APPLY_SIGNAL_CAP
warning 不触发 RESET_SIGNAL_DOMAIN
warning 不修改正式 position cap
warning 不修改 S1 / S2 / S3 或调用 force_exit
warning 不产生正式卖出动作或 ALLOW_REENTRY
```

warning 可以复制上述状态的不可变快照作为 evidence，但不能拥有这些对象的写权限。
实现上 warning 层应消费 v0.3 已产生的只读事件/日线快照，不把 warning type 加入
`FORMAL_DIVERGENCES`、`divergence_position_rule` 或 state-machine trigger。

## 11. 仓位影响方案比较

| 方案 | 优势 | 风险 | 可解释性 | 过拟合风险 | v0.3 兼容性 |
|---|---|---|---|---|---|
| A. 只审计，不改变仓位 | 完全隔离；可先测提前量、升级率和误报；失败可安全撤回 | 用户仍需自行处理提示 | 最高；明确是未确认事实 | 最低 | 完全兼容 |
| B. 输出建议仓位，不进入正式 cap | 可量化用户参考，并保持正式账本不变 | “建议”仍可能被误作自动动作；需要独立评估规则 | 中等；必须同时显示 base/formal/suggested 三套值 | 中等 | 只要不进入 merge/queue 即兼容 |
| C. 直接影响正式仓位 | 自动化程度高 | 未确认峰可能次日失效；会污染 cap、risk cycle、S 状态和冻结回归 | 最低 | 最高 | 与 v0.3 隔离原则冲突 |

**推荐 A。** Phase 1–4 固定 `position_effect=NONE`。只有多样本验证完成、用户单独批准
后，Phase 5 才可评估 B；C 必须作为新的业务版本和独立规格审批，不属于本草案默认路径。

## 12. 推荐方案

推荐的最小闭环是：

1. 从已存在且非变更状态的 `DIVERGENCE_FORMING` 生成 `OPENED/REFRESHED`；
2. 用下一日可见事实追加 `ESCALATED/CLEARED/INVALIDATED`；
3. 单独输出 `warning_events.csv` 和用户去偏摘要；摘要按 `warning_id` 折叠 refresh，
   审计表保留全部 `OPENED/REFRESHED/终结` 事件；
4. 不设置等级，不增加渐弱阈值，不进入仓位；
5. 先以 A–H 多走势矩阵验证事件数量、前缀一致性、升级准确性和负控误报。

该方案没有重新发明顶部判断：它把 v0.3 已有因果 forming 快照变成可结束、可统计、
不污染正式链的独立对象。

## 13. 边界案例

| 案例 | 要求 |
|---|---|
| 尚未建立 momentum anchor 或 last structural | 不生成 warning |
| forming 连续 v1/v2/v3 | 一个 warning_id，三个不可变事件；用户摘要只显示一个活动对象 |
| 同版本重放 | 不增加行数，不改变状态 |
| forming 最终确认正式背离 | 追加一个 `ESCALATED`；正式 count 仅增加一次 |
| forming 确认成无背离结构峰 | `INVALIDATED`，不生成模糊 W1 |
| forming 确认成 intraday/non-comparable | `INVALIDATED`，不进入结构、仓位或 S 状态 |
| 新 anchor breakout | `CLEARED`；warning 不负责重建 anchor |
| 深度 reset 完成 | `INVALIDATED / DEEP_RSI_RESET_COMPLETED`；显示“预警因 RSI 深度重置终止” |
| 深度 reset 当日同时有正式背离 | `ESCALATED` 优先；reset 仅作同日上下文 |
| 第三次正式背离 | warning 先 `ESCALATED`；之后正式路径可进入 S3，两者写权限分离 |
| warning 建立日即为数据末日 | 保持 `ACTIVE_AT_CUTOFF`，不得猜测下一日 |
| warmup 区间 warning | 可审计但必须带 `is_warmup`；展示层默认不当作展示区新提示 |
| 两个旧 canonical 的迟到更新 | 不新建、不刷新、不复活 warning |
| 风险周期在 warning 活动期间变化 | warning 保留建立时 risk_cycle 快照；不跟随回写，也不触发 reset |

## 14. 本轮结论与后续门槛

1. 本轮不增加连续小幅 RSI 下降的第二 warning type。只有 A–H 验证后出现独立、稳定、
   负控良好的证据，才以新 `warning_type` 单独提案。
2. Phase 5 仓位建议暂不批准；Phase 1–4 固定 `position_effect=NONE`。
3. refresh 展示确定折叠：用户摘要每个 `warning_id` 只显示一条当前状态，
   `warning_events.csv` 保留全部生命周期事件。
4. forming→canonical 不修改 v0.3 模型，使用第 7.2 节的确定性匹配谓词和
   `linked_formal_signal_ref`。
5. deep reset 固定为 `INVALIDATED / DEEP_RSI_RESET_COMPLETED`，展示“预警因 RSI
   深度重置终止”，不得表达为风险解除或动能恢复。

Phase 0 已无上述合同歧义。后续尚需由 Phase 4 确定实际 A–H 样本、数据授权和实证结果；
这些事项不得在本轮实现，也不得改变 v0.3.0 冻结语义。
