# rsi-exit v0.3 顶部背离实施记录

## 修改前基线

- 起始工作分支：`agent/rsi-exit-v021-version-freeze`。
- 最新 `main` 与实施分支起点：`a5861e334ade85b1d675edefaacf21172a1f1fdf`。
- 修改前完整测试：Python 3.13.14，70 项全部通过。
- 冻结 ZIP：`outputs/v0.2.1_baseline/300308.SZ_v0.2.1_frozen_baseline.zip`。
- SHA-256：`EA026086B71A0A0CD537ADA177D141DC44DD634B4882C53F341A8605EE906FA5`，与冻结值一致。

## 1. 当前实现摘要与调用链

- candidate peak：`rsi_exit/peak_detector.py::PeakDetector.detect` 调用
  `_is_confirmed_candidate`，按相邻真实交易日的收盘价和 RSI 双上升/双下降确认；
  pipeline 在完整计算区间调用 detector。
- canonical peak：同一 `detect` 调用 `_relationship_metrics` 判断 retrace/gap，
  再以 `_prefer_candidate_values` 更新活动 canonical；`canonical_peaks_frame` 输出最终代表。
- canonical 延伸：后续 candidate 可通过 `canonical_updated` 和递增的
  `canonical_version` 回写活动 canonical；当前没有 forming/formal 状态区分。
- 顶部关系：`rsi_exit/divergence.py::DivergenceTracker.process` 调用
  `classify_peak_pair`；价格由前峰收盘价乘百分比容差判断，RSI 只比较相邻 canonical。
- 低价峰/弱反弹：`classify_peak_pair` 把低价且 RSI 显著下降映射为
  `LOWER_HIGH_WEAK_REBOUND`；`position_rules.py::divergence_position_rule` 会给它仓位上限。
- momentum anchor：`DivergenceTracker.anchor`；任何更高 RSI canonical（含同 canonical
  更新）都可抬高锚。
- last peak：`DivergenceTracker.previous`；每个新 canonical 都替换，未区分 structural。
- divergence count：`DivergenceTracker.divergence_count`；背离递增，但趋势强化或
  RSI改善会清零。
- 风险周期/背离状态：`pipeline.py::analyze_bars` 用同一 `tracker.cycle_id` 驱动
  `SignalCapQueue`；信号 reset、第三次背离强制 S3、普通进入 S3 都进入同一 reset 流程。
- forming：当前不存在；峰只在 `confirm_date` 进入 `peak_events`。
- 正式信号到仓位：`analyze_bars` 调用 `divergence_position_rule`，再通过
  `SignalCapQueue.schedule_cap` 安排 `earliest_action_date` 生效。
- 审计/图表：pipeline 构造 `signals`、`peaks`、`canonical_peaks`、`cycle_log`；
  `reporting.py` 写 CSV/Markdown，`plotting.py` 绘 canonical 和旧信号枚举。
- 入口：单股为 `cli.py::main -> analyze_bars -> write_outputs`；批量为
  `pipeline.py::run_batch`；配置由 `config.py::load_config` 进入。

## 2. 与 v0.3 冻结规格的差异

- 缺少 candidate/canonical/structural 三层身份和 forming/formal canonical 状态。
- 使用收盘价百分比容差，而不是 previous-day close/peak close 可比区与最高价优先级。
- 缺少 new-high/near-high 两种正式背离以及相邻峰、动能锚双 RSI 验证。
- anchor 与 previous canonical 职责耦合；不可比峰会替换 previous。
- 可比但未背离峰、不可比峰、forming 峰对计数和链的处理不符合冻结规则。
- 深度 reset 只看单个区间最小 RSI 且边界为 `<50`；缺少连续 3 日、`<=40`、
  gap 28/29 和 anchor +2.0 的独立规则。
- 风险 cycle 与 divergence chain 共用 ID，进入 S3 会重置背离结构。
- 缺少形成中事件的仓位隔离和完整审计字段/图例。

5/14 前一交易日收盘 1049.20，5/20 high=1071、close=1037；按冻结公式，5/20
正式标记为 `INTRADAY_POTENTIAL_RETEST`，且不得进入结构链或仓位系统。实现未增加
股票或日期特例。

## 3. 预计修改文件

- 核心：`models.py`、`divergence.py`、`peak_detector.py`、`pipeline.py`。
- 集成：`position_rules.py`、`plotting.py`、`reporting.py`、`config.py`、`cli.py`。
- 配置/版本：新增 `config/rsi_exit_v03.yaml`，更新默认配置、包版本、项目版本和 README。
- 文档：新增冻结规格与本实施记录。
- 测试：保留已有测试函数并按新冻结语义调整冲突断言；新增独立 v0.3 单元、pipeline
  隔离、因果和真实冻结基线回归测试。

## 4. 数据模型和枚举兼容策略

- 保留现有 `Peak`/`CanonicalPeak` 字段和 v0.1/v0.2 identity aliases；新字段给默认值，
  旧构造调用仍可运行。
- 保留 `BEARISH_DIVERGENCE`、`LOWER_HIGH_WEAK_REBOUND` 等旧枚举用于历史 CSV；
  v0.3 顶部链只发出 new-high/near-high/forming/structural-without-divergence 等新事件。
- 保留 `cycle_id` 输出兼容列，并新增 `risk_cycle_id`、`divergence_chain_id`；两者不再
  共享生命周期。
- 输出采用加列方式，旧 identity、decision/effective 和仓位字段不删除。
- 历史 v0.1/v0.2 配置文件保留；默认单一真源切换至 v0.3 配置。

## 5. 测试计划

- 纯函数参数化测试覆盖可比区、四级价格关系和所有 0.9/1.0、1.9/2.0 边界。
- tracker 测试覆盖双 RSI 验证、last structural 更新、连续计数、不可比峰隔离、三种
  reset 以及 gap 28/29。
- forming 测试覆盖延伸、失效、正式转换和仓位/S 状态隔离。
- pipeline 测试覆盖 risk cycle 与 divergence chain 分离、S3/ALLOW_REENTRY 不清链、
  严格 `peak_date < confirm_date < earliest_action_date` 和正式记录不可回写。
- 峰7—峰8样例必须输出 `NEAR_HIGH_BEARISH_DIVERGENCE`。
- 对 SHA 已校验的 300308 冻结 ZIP 执行真实回归，核对 5/14、5/28、6/04、6/22 主链；
  同时如实记录上述 5/20 分类公式冲突。
- 最后运行完整 pytest、Python 3.10/3.13、项目已有打包检查，并复核未提交缓存/ZIP/输出。

## 6. v0.3.0 冻结前语义补丁

- 根因：`DivergenceTracker.process` 同时让 `canonical_created` 与 `canonical_updated`
  进入正式比较；更新路径既可能在双背离分支重复计数，也可能用任意正 RSI 差抬高 anchor。
- 不可变粒度修正为 `(canonical_peak_id, canonical_version)`；同版本重放直接忽略。同
  canonical 新版本默认 audit-only，不进入仓位或状态机。
- 唯一例外：新版本因果确认、价格结构合格，并较同组上一正式版本 RSI 至少提高 2.0
  时，输出无仓位资格的 `ANCHOR_RSI_BREAKOUT`，重建 momentum anchor、last structural
  与 divergence chain，count 归零。`same_canonical_anchor_breakout` 显式审计来源。
- 300308 冻结链保留：PK0008 v1（4/30）快照不回写；PK0008 v2（5/14）新增 anchor
  breakout；5/20 为 `INTRADAY_POTENTIAL_RETEST`；5/28、6/04、6/22 仍为 count 1/2/3。
- 新增 `rsi_exit.release_check`。普通测试可明确 skip 缺失的私有 ZIP；发布验收缺文件、
  SHA、ZIP 成员、OHLCV 字段、结果或前缀一致性任一不符即失败。
- GitHub Actions 在 Python 3.10、3.11、3.12、3.13 执行普通测试、脱敏 fixture 和
  `compileall`；私有 ZIP 不提交到仓库。
