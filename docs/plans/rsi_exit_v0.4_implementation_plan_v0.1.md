# rsi-exit v0.4 预警层后续实施计划（v0.1）

状态：`DRAFT`；本文件只拆分后续工作，不授权本轮实现业务代码。

## 0. 全程边界

- 以 v0.3.0 commit `49c8323218226ee1ec3e14f52fe951b533333315` 和冻结 SHA-256
  `932D0220AAB4A3BDC6BB0EA3A77630A994702E821E1FF72C7A4F3E25B6D1BF52` 为不可变基线。
- warning 第一阶段只消费 `DIVERGENCE_FORMING`，不改变 v0.3 检测条件。
- warning 代码不得写入 divergence tracker、risk cycle、position queue 或 state machine。
- 现有 `AnalysisResult.warnings: list[str]` 固定表示系统运行、数据质量和配置类警告；
  v0.4 生命周期对象统一命名为 `warning_events`，正式输出为 `warning_events.csv`。
- 每个 Phase 单独提交、单独审查；前一 Phase 验收通过后才能进入下一 Phase。
- Phase 5 必须再次获得明确业务批准；Phase 6 不得移动 `v0.3.0` tag 或覆盖冻结 ZIP。
- 新测试行情只能是合成/脱敏 fixture；私有行情不提交。

## Phase 1：warning 数据模型和纯审计事件

### 目标

定义不可变 `WarningEvent`，从现有 `DIVERGENCE_FORMING` 生成 `OPENED/REFRESHED`
审计事件；不实现终结生命周期，不改变任何正式输出语义。

### 预计修改文件

- `rsi_exit/models.py`：新增 warning enum/dataclass；保留 `warnings: list[str]`，新增
  `warning_events: pd.DataFrame`，不改原字段内容和语义；
- `rsi_exit/warning_events.py`（新增）：消费既有 forming fact、验证 source contract、建立
  含 `symbol` 的确定性身份并生成审计事件；不得重算背离条件；
- `rsi_exit/pipeline.py`：以只读方式将既有 forming 结果传入 warning 纯函数；
- `rsi_exit/reporting.py`：新增独立 `warning_events.csv`，不混入正式 `signals.csv`；
- `tests/test_v04_warning_events.py`（新增）：事件条件、身份、日期和隔离测试。

### 新增测试

- `DIVERGENCE_FORMING` 的 type/status 与两个批准 price relation 触发正例；
- RSI delta、structural/position eligibility、pending action 的 source contract 断言；
- source contract 损坏时明确失败、不建立事件、不静默重算；
- intraday、non-comparable、structural-without-divergence 负例；
- forming v1/v2/v3 的一个 warning id 和唯一 event id；
- 两个 symbol 使用相同 forming/chain id 时身份不碰撞；
- 同版本重放无操作；
- `position_effect=NONE`、recommended cap 为 null；
- 事件只含 `available_date`，不含 `earliest_action_date` 或 `effective_date`；
- `AnalysisResult.warnings` 内容、顺序、类型和语义保持不变；
- warning 开关前后 v0.3 正式输出逐字段一致。

### 验收标准

- 只产生 `OPENED/REFRESHED`；每个事件可由源 forming 行复算；
- `observation_date = decision_date = available_date`；prefix/full 在相同起点、配置、symbol
  且仅改变截止日期时前缀一致；
- 未调用 `divergence_position_rule`、`SignalCapQueue` 或 state-machine API；
- v0.3 全量测试和冻结回归不变。

### 禁止越界项

- 不修改 `divergence.py` 的正式条件或 tracker 状态；
- 不新增 warning level、评分、超时或仓位建议；
- 不修改 v0.3 配置、版本号、tag 或冻结 ZIP。

## Phase 2：warning tracker 与生命周期

### 目标

以追加事件实现 `ACTIVE -> ESCALATED/CLEARED/INVALIDATED`；所有终态不可复活。

### 预计修改文件

- `rsi_exit/warning_events.py`：新增独立 `WarningTracker`，仅拥有 warning event 状态；
- `rsi_exit/models.py`：补充生命周期原因码和正式信号引用字段；
- `rsi_exit/pipeline.py`：按固定优先级投递只读 formal/daily facts；
- `rsi_exit/reporting.py`：输出事件历史和 as-of 当前状态；
- `tests/test_v04_warning_lifecycle.py`（新增）。

### 新增测试

- 延伸、正式升级、无背离确认失效、混合涨跌失效；
- anchor breakout 产生 `CLEARED / MOMENTUM_ANCHOR_REBUILT`；
- 两类 deep reset 产生 `INVALIDATED / DEEP_RSI_RESET_COMPLETED`，不得显示风险解除；
- 同日多条件优先级；
- formal matcher 覆盖 last structural id/version、anchor id/version、peak date、chain 和
  `latest_decision_date`，并验证结果不依赖 `position_eligible`；
- formal 匹配基数 0/1/>1 分别走其他终止、唯一升级、数据合同错误；
- `linked_formal_signal_ref` 可从现有正式字段确定性复算，且只写入 `ESCALATED`；
- 活动 warning 在数据截止日保持 `ACTIVE_AT_CUTOFF`；
- canonical v1/v2/v3、同版本重放、旧组迟到和终态复活负例；
- 每个事件日 prefix/full 逐字段比较。

### 验收标准

- 每个活动 warning 在下一个可判定时点只有一个转换；
- `ESCALATED` 与且仅与匹配正式信号链接，不自行增加正式 count；
- 不修改 v0.3 models/signals schema，不新增 forming→canonical 字段或 formal signal id；
- 旧事件不回写，终态不复活；
- v0.3 tracker/cycle/cap/state 对照完全一致。

### 禁止越界项

- WarningTracker 不得持有 v0.3 对象的可变引用；
- 不以 warning 触发 reset、force exit、cap queue 或 ALLOW_REENTRY；
- 不增加第二 warning type。

## Phase 3：报表和图表显示

### 目标

把活动/终结 warning 作为独立去偏信息显示，避免和正式背离、S 状态、正式仓位混淆。

### 预计修改文件

- `rsi_exit/reporting.py`：新增 warning event 摘要、原因、证据表和 `warning_events.csv`；
- `rsi_exit/plotting.py`：使用独立图例和非交易标记；
- `rsi_exit/cli.py`：仅增加输出路径/摘要信息；
- `README.md` 与 v0.4 使用说明；
- `tests/test_v04_warning_reporting.py`（新增）。

### 新增测试

- 同一 warning id 的 refresh 必须在用户摘要折叠，`warning_events.csv` 保留全部事件；
- 活动、升级、解除、失效的标签互斥；
- warning 标记不显示正式 divergence 序号或 position cap；
- CSV 列顺序、空输出、warmup/display-range 和确定性序列化；
- 图表 smoke test 与缺少 warning 时的兼容。

### 验收标准

- 用户能区分“预警”“正式背离”“S 状态”和“正式仓位”；
- 报告显示 as-of date、状态、硬证据和 position effect `NONE`；
- deep reset 固定显示“预警因 RSI 深度重置终止”，不能显示风险解除或动能恢复；
- 同一 forming 连续版本不重复弹窗；
- 输出可确定性重放。

### 禁止越界项

- 不以颜色或文案暗示必然卖出；
- 不把 warning 合并进正式 `signals.csv` 的 formal count；
- 不增加百分制风险分或主观解释文本作为决策输入。

## Phase 4：多样本验证

### 目标

按验证矩阵完成 A–H 类型，证明正例可升级、负例不误报、噪声受控且 v0.3 完全隔离。

### 预计修改文件

- `tests/test_v04_warning_scenarios.py`（新增合成/脱敏参数化测试）；
- `tests/fixtures/` 下经批准的合成或脱敏 fixture；
- `docs/validation/rsi_exit_v0.4_validation_results_v0.1.md`（新增结果记录）；
- 必要时仅修正 `rsi_exit/warning_events.py` 中已批准的确定性规则。

### 新增测试

- A 强趋势多次背离；B 强趋势无背离；C 高位横盘；D 单峰快速回落；
- E 假突破；F canonical 连续更新；G 深度 reset；H 震荡噪声；
- 每类包含 prefix/full、重放和 control/treatment 隔离断言；
- 私有样本仅在本地验证脚本中引用，不加入 git。

### 验收标准

- A–H 每类至少一个样本，B/E/H 有负控；
- 所有正式输出 control/treatment 等价；
- warning 数受 source forming id 和版本去重约束；
- 每项失败均记录具体反例，不以调参掩盖。

### 禁止越界项

- 不针对 symbol/date 写条件；
- 不用 300308.SZ 单样本选择新阈值；
- 不提交私有行情、缓存、运行输出或重生成的 v0.3 ZIP；
- 验证失败时不自动扩大 warning 类型。

## Phase 5：是否接入建议仓位

### 进入条件

只有 Phase 4 完成且用户明确批准后进入。默认仍是方案 A；本 Phase 首先只评估方案 B。

### 预计修改文件

- `docs/specs/rsi_exit_v0.4_warning_position_proposal_v0.1.md`（先新增并批准）；
- 批准后才可能修改 `rsi_exit/warning_events.py`、`rsi_exit/reporting.py`；
- 新增 `config/rsi_exit_v04.yaml` 中独立 warning 建议字段；
- `tests/test_v04_warning_position_advice.py`（新增）。

正式 `position_rules.py`、`SignalCapQueue` 和 `state_machine.py` 默认不修改。若提案要求方案 C，
必须终止本 Phase，另开版本、规格和审批。

Phase 5 目前未获批准。若未来批准方案 B，必须新增独立字段和独立规格，不能向 Phase 1
历史 `WarningEvent` 回填交易有效日、`earliest_action_date` 或 `effective_date`。

### 新增测试

- suggested cap 与 base/formal/effective cap 分列且不参与 merge；
- 建议值为 null/关闭时完全兼容；
- 失效/解除/升级后的建议生命周期；
- 用户显示明确标注“建议、非正式仓位”。

### 验收标准

- 方案 B 不改变正式 cap、动作、risk cycle 或 S 状态；
- 建议规则有独立多样本证据和清晰关闭开关；
- 未批准时代码路径不存在或固定关闭。

### 禁止越界项

- 不直接修改正式 position cap；
- 不触发 `APPLY_SIGNAL_CAP`、S3 或卖出动作；
- 不把建议规则伪装成 v0.3 兼容补丁。

## Phase 6：版本冻结

### 目标

在全部批准项完成后冻结 v0.4，不触碰 v0.3.0 tag、Release、ZIP 或语义。

### 预计修改文件

- `rsi_exit/__init__.py`、`pyproject.toml`：仅在发布批准后更新 v0.4 版本；
- `config/rsi_exit_v04.yaml`：形成 v0.4 单一配置快照；
- `docs/releases/rsi_exit_v0.4.0_freeze_manifest.md`（新增）；
- v0.4 自有冻结/发布检查和测试；
- 如需冻结输出，使用全新 v0.4 文件名，绝不覆盖 v0.3.0 ZIP。

### 新增测试

- 普通 pytest、compileall、build、diff check；
- v0.3.0 冻结 SHA 与语义回归；
- v0.4 输出成员哈希、顺序、时间戳和双次生成确定性；
- 版本/tag/Release commit 一致性检查。

### 验收标准

- 支持的 Python 版本全部通过；
- v0.3.0 SHA 仍为 `932D0220...1BF52`；
- v0.4 双次独立生成字节一致；
- 发布 commit、tag、Release 和 manifest 一致，且经单独批准。

### 禁止越界项

- 不移动或重打 `v0.3.0` tag；
- 不覆盖 v0.3.0 Release 或冻结输出；
- 不在验证未完成时提高版本或宣称业务语义已发布；
- 不自动合并发布 PR。

## 7. 每阶段共同检查

每个 Phase 至少运行：

```powershell
python -m pytest
python -m compileall rsi_exit
git diff --check
Get-FileHash baselines/300308.SZ_v0.3.0_frozen_baseline.zip -Algorithm SHA256
```

涉及正式发布时再运行冻结输入 release check、required frozen tests、build 和双次确定性
生成。任一隔离断言或冻结哈希失败都必须停止，不得继续下一 Phase。
