# rsi-exit v0.4 warning lifecycle specification

## Scope

v0.4.0 freezes the warning lifecycle as an append-only, read-only audit domain. It
does not change peak confirmation, divergence recognition, the base-state machine,
the formal signal-cap queue, or position-cap values.

## Lifecycle

- `OPENED`: a forming-divergence warning enters observation.
- `REFRESHED`: new evidence updates an existing active warning.
- `ESCALATED`: the warning uniquely links to a formal divergence.
- `INVALIDATED`: the forming evidence no longer qualifies and the warning ends.
- `CLEARED`: lifecycle cleanup ends a warning without escalation.

Every transition is appended as a new event. Historical events are not rewritten.
The state at an as-of date is derived from the latest event known by that date, and
no event may follow a terminal `ESCALATED`, `INVALIDATED`, or `CLEARED` event.

## Causal timing

A warning event's decision date is knowable only after that trading day's close.
The earliest action proxy is the next real trading day. That proxy is used only for
descriptive timing analysis: a warning event itself produces no trading action.

## Position boundary

`WarningPositionEffect` only permits `NONE`.
`recommended_position_cap` must be empty.

- `OPENED` only starts observation.
- `REFRESHED` only updates evidence.
- `ESCALATED` only links a formal divergence. Any position constraint comes from
  the existing formal signal-cap rule.
- `INVALIDATED` ends the warning and does not restore a position.
- `CLEARED` closes the lifecycle and does not restore a position.

These are final v0.4.0 product semantics, not placeholders.

## Domain isolation

The system has three separate concepts:

1. The base-state position domain derives a cap from the S-state machine.
2. The formal signal-cap domain derives a cap from position-eligible formal
   divergence signals.
3. The warning audit domain records forming evidence and lifecycle history.

Only the first two domains determine the final position. The warning audit domain
does not participate in `merge_position_caps`, enter `SignalCapQueue`, or cause a
base-state transition. An `ESCALATED` event therefore cannot apply a second cap on
top of its linked formal signal.

## Validation evidence

[Phase 4](../validation/v04_phase4/validation_report.md) examined 12 samples and
recorded 304 `OPENED` plus 140 `ESCALATED` events.
[Phase 4.1](../validation/v04_phase41_actionability/actionability_report.md)
matched formal divergences to `ESCALATED` warnings 140/140. The unconditional
`OPENED` path did not support a uniform action, while the distribution and sector
differences of `ESCALATED` events did not support a second uniform position rule.

The evidence supports retaining warning lifecycle reporting and auditability while
delegating every position effect to the established base-state and formal
signal-cap domains.

## Frozen decision and change control

All warning lifecycle events have:

```text
position_effect = NONE
recommended_position_cap = null
```

The proposed Phase 5 warning-position feature is cancelled. No warning position
domain will be added under the v0.4.0 identity. A future proposal to change this
boundary requires a new product decision, specification, validation evidence, and
version increment; it must not rewrite the v0.4.0 frozen baseline.
