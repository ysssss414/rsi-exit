# rsi-exit v0.3 顶部背离冻结规格（v0.2）

本文是 v0.3.0 实现所依据的顶部背离业务规格。v0.2.1 的 candidate 识别、canonical
合并框架、初始 momentum anchor 资格、反弹/弱反弹独立模块、仓位比例、S1/S2/S3、
`ALLOW_REENTRY` 和数据源口径不在本次重构范围。

## 1. 峰值层级与因果

峰值分三层：

1. `candidate peak` 只用于审计、图表和 canonical 输入，不更新正式锚、结构峰、背离
   次数或仓位。
2. `canonical peak` 区分 `FORMING_CANONICAL_PEAK` 和
   `CONFIRMED_CANONICAL_PEAK`。形成中代表可以延伸；已发出的正式快照不得被后续数据
   改写。
3. `structural peak` 必须是已确认 canonical，且价格关系只能是
   `STRICT_NEW_HIGH` 或 `FORMAL_NEAR_HIGH_RETEST`。

正式记录必须满足：

```text
peak_date < confirm_date < earliest_action_date
```

确认日只能生成决策，不能同日执行；形成中行没有正式执行日。前缀数据运行已经确认的
正式峰、背离类型和计数必须与完整数据运行一致。

canonical 的正式不可变键是 `(canonical_peak_id, canonical_version)`。同一版本最多处理
一次；同一 canonical 的新版本默认只保留 candidate/canonical 审计，不产生正式背离、
不计数、不进入仓位。唯一正式状态例外是第 5 节的同 canonical anchor breakout。该规则
是版本化 canonical 与动能锚的一般衔接，不是股票或日期特例。

## 2. 可比区和价格关系

设上一结构峰为 `P`，从真实交易日序列取得 `P.peak_date` 前一日的收盘价：

```python
comparable_zone_low = min(P.previous_day_close, P.close)
comparable_zone_high = max(P.previous_day_close, P.close)
```

上沿只用于审计/图表，不是近高重测的排除上限。禁止用开盘价、ATR、波动率、价格
百分比容差或距离前高百分比护栏。`price_epsilon` 只处理浮点/复权/最小报价精度。

分类顺序固定为：

```python
if current.high > previous.high + price_epsilon:
    relation = "STRICT_NEW_HIGH"
elif current.close >= comparable_zone_low:
    relation = "FORMAL_NEAR_HIGH_RETEST"
elif current.high >= comparable_zone_low:
    relation = "INTRADAY_POTENTIAL_RETEST"
else:
    relation = "NON_COMPARABLE_PEAK"
```

- 严格新高只看最高价；即使收盘跌出可比区也仍是严格新高，并审计
  `close_rejected_from_high_zone`。
- 最高价未严格突破、收盘进入可比区即为正式近高重测；收盘超过可比区上沿也不排除。
- 盘中触及但收盘未进入、以及不可比峰，都不是结构峰，不更新正式锚/last structural、
  不计数、不进入仓位。
- 低价峰不得在本轮顶部链中被改称弱反弹或趋势强化。

## 3. RSI 双验证与双基准

配置阈值必须相互独立：

```text
divergence_rsi_tolerance = 1.0
anchor_rsi_tolerance = 1.0
momentum_strengthening_tolerance = 1.0
anchor_reset_tolerance = 2.0
```

相邻结构峰差值为 `current.rsi - last_structural_peak.rsi`：小于等于 -1.0 为显著
下降，大于等于 1.0 为显著提高，中间为持平。正式背离还必须满足：

```python
current.rsi <= momentum_anchor.rsi - anchor_rsi_tolerance
```

`momentum_anchor` 验证同一中期动能衰减链，并判断动能是否重新建立；
`last_structural_peak` 计算下一次可比区并负责相邻峰比较。任何正式结构峰无论是否背离
都更新 last structural；普通结构峰不移动 anchor。

## 4. 正式事件和计数

新高顶部背离：

```python
current.high > last.high + price_epsilon
current.rsi <= last.rsi - 1.0
current.rsi <= anchor.rsi - 1.0
```

事件为 `NEW_HIGH_BEARISH_DIVERGENCE`。

近高顶部背离：

```python
current.high <= last.high + price_epsilon
current.close >= comparable_zone_low(last)
current.rsi <= last.rsi - 1.0
current.rsi <= anchor.rsi - 1.0
```

事件为 `NEAR_HIGH_BEARISH_DIVERGENCE`。两者每次都使 `divergence_count += 1` 并更新
last structural。

`NEW_HIGH_BEARISH_DIVERGENCE` 与 `NEAR_HIGH_BEARISH_DIVERGENCE` 复用 v0.2.1
既有正式背离仓位及状态转换规则，包括一背、二背、三背退出、S1/S2/S3 和
`APPLY_SIGNAL_CAP`；v0.3 不修改仓位比例、状态阈值、决策/生效日或 `ALLOW_REENTRY`。

价格可比但双 RSI 条件未同时满足时，事件为
`STRUCTURAL_PEAK_WITHOUT_DIVERGENCE`：last structural 更新，anchor 和 count 不变。
中间允许多个此类结构峰；下一次只与最近结构峰比较。低位不可比峰不切断链。

## 5. 背离链重置

`divergence_chain_id` 与 `risk_cycle_id` 生命周期分离。进入/退出 S3、仓位归零、
`ALLOW_REENTRY`、`APPLY_SIGNAL_CAP` 或 `RESET_SIGNAL_DOMAIN` 都不能自动重置背离链。

在当前可比峰和旧结构峰正式比较前检查：

- 真实交易日 RSI 严格低于 50 连续至少 3 日；或峰间最小 RSI 小于等于 40：
  `DEEP_RSI_RESET`。
- 结构峰索引差大于 28：`STRUCTURAL_PEAK_GAP`。28 允许比较，29 重置。
- 当前结构峰 RSI 大于等于 anchor RSI + 2.0：`ANCHOR_RSI_BREAKOUT`。

发生重置时，当前峰不得与旧结构峰形成背离；旧链关闭，当前合格峰建立新锚、成为
last structural，count 归零。单日 49、`49/50/49`、40.1、不可比峰、forming 失效、
普通仓位/风险周期事件均不能重置。

同 canonical 新版本先以同组上一正式版本快照验证版本递增、日期因果和 `+2.0` 闭区间
边界，再以当前 last structural 验证价格关系必须为 `STRICT_NEW_HIGH` 或
`FORMAL_NEAR_HIGH_RETEST`。全部满足时，它可以作为唯一更新例外输出
`STRUCTURAL_PEAK_WITHOUT_DIVERGENCE` 和 `ANCHOR_RSI_BREAKOUT`：旧链关闭，当前版本
成为新 momentum anchor 与 last structural，count 归零且新建 chain；该行不具仓位
资格，也不触发一背、二背、三背或 S 状态。`+1.999` 只能审计，`+2.000` 才触发；
同一 `(canonical_peak_id, canonical_version)` 重放不得再次重置。

## 6. DIVERGENCE_FORMING

仍在延伸的潜在 canonical 顶部可发出 `DIVERGENCE_FORMING` 审计行。它可以随新高
更新临时代表，最终确认成正式背离或失效；但必须满足：

- 不增加正式 count；
- 不更新正式 last structural 或 momentum anchor；
- 不触发仓位上限、`APPLY_SIGNAL_CAP`、`RESET_SIGNAL_DOMAIN`、`ALLOW_REENTRY`；
- 不改变 S1/S2/S3；
- `forming_divergence_position_eligible` 固定为 `false`。

## 7. 配置和审计

活动配置显式包含：

```text
comparable_zone_mode = PREVIOUS_CLOSE_TO_PEAK_CLOSE
price_epsilon = 1e-8
divergence_rsi_tolerance = 1.0
anchor_rsi_tolerance = 1.0
momentum_strengthening_tolerance = 1.0
anchor_reset_tolerance = 2.0
deep_reset_rsi_level = 50.0
deep_reset_consecutive_days = 3
extreme_reset_rsi_level = 40.0
max_structural_peak_gap = 28
forming_divergence_position_eligible = false
```

审计至少还原峰层级、canonical 状态、比较的 last structural、momentum anchor、前一
交易日收盘、可比区、价格关系、local/anchor RSI delta、结构资格、背离类型/序号、
forming/formal、链重置原因、最早行动日和仓位资格。图表区分 candidate、confirmed
canonical、structural、两类正式背离、non-comparable 和 forming。

旧 `WEAK_REBOUND` 枚举可为历史 CSV/独立模块保留，但不得参与 v0.3 顶部结构链和
顶部背离仓位约束。

## 8. 冻结回归

冻结文件：`300308.SZ_v0.2.1_frozen_baseline.zip`，SHA-256：

```text
EA026086B71A0A0CD537ADA177D141DC44DD634B4882C53F341A8605EE906FA5
```

正式主链目标：

```text
2026-05-14  P0 momentum anchor
2026-05-28  P1 NEW_HIGH_BEARISH_DIVERGENCE，2026-05-29确认，count=1
2026-06-04  P2 NEW_HIGH_BEARISH_DIVERGENCE，2026-06-05确认，count=2
2026-06-22  P3 NEW_HIGH_BEARISH_DIVERGENCE，2026-06-23确认，count=3
```

6/09、6/25 为 `NON_COMPARABLE_PEAK`；6/18 可为 forming，正式 P3 仍只能是 6/22。

5/20 的实际 high=1071、close=1037，5/14 可比区下沿为 1049.20，因此冻结标签为
`INTRADAY_POTENTIAL_RETEST`。它保持非结构、零仓位资格且不改变链；实现不得硬编码
股票或日期。

峰7—峰8样例在最高价未严格新高、收盘进入可比区且双 RSI 下降时，必须输出
`NEAR_HIGH_BEARISH_DIVERGENCE`，不得输出 `WEAK_REBOUND`。

普通 `pytest` 在私有 ZIP 不存在时会明确报告真实冻结回归未执行。发布验收必须运行：

```powershell
python -m rsi_exit.release_check --frozen-baseline <path-to-frozen-zip>
pytest -m frozen_baseline_required
```

缺文件、SHA、ZIP 结构、关键峰序列、仓位资格或前缀不可回写任一不符都必须失败。
