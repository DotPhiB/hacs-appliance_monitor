# Appliance Monitor

A Home Assistant custom integration that monitors appliance power consumption and automatically detects when an appliance is running or finished with a cycle.

Designed for washing machines, dishwashers, dryers, and any appliance with a measurable power draw pattern.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Lint](https://github.com/DotPhiB/hacs-appliance_monitor/actions/workflows/lint.yml/badge.svg)](https://github.com/DotPhiB/hacs-appliance_monitor/actions/workflows/lint.yml)
[![Tests](https://github.com/DotPhiB/hacs-appliance_monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/DotPhiB/hacs-appliance_monitor/actions/workflows/tests.yml)
[![Validate](https://github.com/DotPhiB/hacs-appliance_monitor/actions/workflows/validate.yml/badge.svg)](https://github.com/DotPhiB/hacs-appliance_monitor/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/DotPhiB/hacs-appliance_monitor)](LICENSE)

---

> **A note on how this was built:** I'm not a Python developer. This integration was built with AI assistance — not by blindly accepting generated code, but by understanding the decisions and iterating deliberately. I've done my best to follow Home Assistant conventions and Python best practices, but if something doesn't meet your expectations as an experienced developer, I'd genuinely welcome the feedback. Issues and PRs are open.

---

## Features

- Detects **running** and **finished** states from a single power sensor
- Exposes state, cycle duration and cycle energy up front, plus diagnostic sensors — automations work off either
- **Unloaded** button to acknowledge a finished cycle, and a **Reset State** escape hatch for a machine stuck in the wrong state
- Judges the end of a cycle on **energy consumed over a sliding window**, not on live power, so intermediate low-draw phases (spin-pause, dishwasher soaking, oven holding temp) keep the cycle open while brief standby blips no longer delay the finish
- Optional **post-cycle** phase for appliances that idle after the programme ends (anti-crease tumbling, drying, cooling) — keeps "work done" and "appliance quiet" as two distinct states instead of one blurred one
- Optional start delay to ignore brief startup spikes (e.g. inrush current when the appliance is first plugged in)
- Reports a **disconnected** state when the source power sensor goes unavailable, without corrupting energy totals or firing spurious transitions across the gap
- State and lifetime totals survive Home Assistant restarts
- All thresholds and windows are adjustable post-setup via the integration's options, with optional **tuning sensors** that measure your appliance so you can pick them from its own data

---

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** → three-dot menu → **Custom repositories**.
3. Add `https://github.com/DotPhiB/hacs-appliance_monitor` as an **Integration**.
4. Search for **Appliance Monitor** and install it.
5. Restart Home Assistant.

### Manual

Copy `custom_components/appliance_monitor/` into your HA `config/custom_components/` directory and restart Home Assistant.

---

## Configuration

Go to **Settings → Devices & Services → Add Integration** and search for **Appliance Monitor**.

| Field | Description | Default |
|---|---|---|
| Power sensor | HA sensor entity reporting live power in watts | — |
| Start threshold (W) | Power above this level means the appliance has started | 10 W |
| Start delay (s) | Seconds power must stay at or above the start threshold before a cycle begins. Useful for appliances with a brief startup spike that isn't a real cycle start. Leave at 0 unless you actually see false starts — values larger than your sensor's update interval can cause real cycles to be missed. | 0 s |
| Finished window (s) | Length of the sliding window the cycle is judged over. No check runs until a full window of readings exists, so this is also the shortest cycle that can be detected. Set to 0 for an instant verdict on each reading. | 300 s |
| Finished energy threshold (Wh) | The cycle counts as finished once less than this much energy is used within the window. Read as **watts** when the window is 0. | 0.3 Wh |
| Detect post-cycle phase | Enable for appliances that keep drawing power after the programme ends — anti-crease tumbling, drying, cooling | off |
| Post-cycle window (s) | Sliding window for the post-cycle check | 300 s |
| Post-cycle energy threshold (Wh) | The programme counts as done once less than this much energy is used within the post-cycle window | 2.7 Wh |

All fields except the power sensor can be changed at any time via **Settings → Devices & Services → Appliance Monitor → Configure**.

### Why energy instead of power

Live power cannot tell a soaking washing machine from a finished one — mid-cycle both sit near zero. The old idle threshold plus timeout could only paper over that with a long timeout, and any single sample above the threshold re-armed it, so a machine blipping 2–3 W in standby stayed "running" long after the programme had ended.

Energy over a sliding window has no such blind spot: brief blips are absorbed rather than treated as evidence of life, and a genuinely quiet appliance crosses the threshold on schedule. Starting is still judged on live power, because a cycle should be picked up at once.

The two are the same measurement at different scales. Energy over a window is the rise of the cumulative energy curve, and over the window's length that is an average rate — as the window shrinks, the rate converges on the power at that instant. A window of 0 is that limit: the threshold is then read in watts and compared against each reading as it arrives, which is exactly how the old idle threshold behaved.

Windows shorter than the source's update interval are measured too, not rounded up to it: the reading straddling the window's edge counts only for the share of its interval that falls inside. So no window length is invalid — a given window and threshold either suit your appliance and its update rate or they don't, which is what the two fields are for.

On real washing-machine cycles, being able to detect the post-cycle phase moved the end-of-programme signal 40 minutes earlier than the previous release reported it.

That gain comes from the mechanism and from where you put the threshold, though — not from the phase itself. Setting the finished threshold above an appliance's idling draw already ends the cycle as soon as the work stops. What the phase adds is the second half of the picture: it keeps reporting until the appliance actually goes quiet, instead of leaving that indistinguishable from a finished cycle. How long that takes is entirely up to the appliance.

### Tuning

Both thresholds have to sit in the gap between what the appliance draws while working and what it draws when it is done. Measured over three cycles each:

| | Washing machine | Dryer |
|---|---|---|
| Working phase | 2.15–178 Wh / 5 min | 100–170 Wh / 5 min |
| Post-cycle phase | 0.5–0.9 Wh / 5 min (continuous 10–16 W) | ~0.5 Wh per tumble, one every 10 min |
| Standby | 0.05–0.19 Wh / 5 min | ~0 |
| **Post-cycle window / threshold** | 300 s / 2.7 Wh | 60 s / 2.0 Wh |
| **Finished window / threshold** | 300 s / 0.3 Wh | 720 s / 0.2 Wh |

The two appliances want opposite settings, which is why every check has its own window:

- The **washer** soaks mid-cycle, so its post-cycle window must be long enough that a soak never looks like the end of the programme — 5 minutes is the shortest that works. Below that the bands overlap: at 1-minute resolution the working phase drops to ~0.1 Wh, *under* what the machine draws when it is done.
- The **dryer** draws continuously while working, so 60 seconds is already decisive. Its finished window instead has to be long — the anti-crease tumble fires every 10 minutes, and a window shorter than that would call the appliance finished between two tumbles.

Rule of thumb: the post-cycle window must exceed the appliance's longest low-draw phase while working; the finished window must exceed the gap between its post-cycle bursts.

#### Measuring your own appliance

The numbers above came from somewhere, and the **tuning sensors** let you produce the same table for your own machine without doing the arithmetic by hand. A power graph will not tell you this: energy over a window is an area, and areas are close to impossible to compare by eye.

Each one reports the energy consumed over a fixed trailing window, updated on every reading, regardless of what state the appliance is in or whether the post-cycle phase is enabled:

| Entity | Window |
|---|---|
| `sensor.<name>_tuning_30s` | 30 s |
| `sensor.<name>_tuning_1m` | 1 min |
| `sensor.<name>_tuning_2m` | 2 min |
| `sensor.<name>_tuning_5m` | 5 min |
| `sensor.<name>_tuning_10m` | 10 min |
| `sensor.<name>_tuning_finished_window` | whatever `finished_window` is set to |
| `sensor.<name>_tuning_post_cycle_window` | whatever `post_cycle_window` is set to |

They are **disabled by default**. The workflow is: enable them, run a cycle or two, open the history graph, and read off the bands — working, post-cycle, standby — for each window length. The window whose bands are furthest apart is the one to configure, and the threshold goes in the gap. The last two mirror your current settings, so you can watch the exact measure a threshold is judged against and see how much headroom it has. Disable them again afterwards; they record a value on every update, which is a lot of history to keep for a setting you change once.

Each carries attributes for the details the value alone does not show:

| Attribute | Meaning |
|---|---|
| `window_seconds` | Length of the window being measured |
| `source_samples_in_window` | How many readings **the source itself published** inside the window. Poll re-reads are excluded, so `0` honestly means the source said nothing at all — which is normal for a quiet appliance, since a plug that only reports on change has nothing to report. The measure still uses every reading; this counts only how much of it came from the appliance. |
| `trigger` | `source_update` if the source published a new value, `poll` for the 10 s fallback, `command` for a button press |
| `average_power_w` | The same measure as a rate. The Wh value scales with the window, so a 10 min window reads 20× a 30 s one at the same draw; this does not, which makes the windows directly comparable and keeps the number stable if you later change a window's length |
| `measures` | `energy` normally; `power` when the window is 0, where the check is a live reading rather than a window |
| `threshold` / `threshold_unit` | Configured-window sensors only: the value this window is compared against, in `Wh` (or `W` when the window is 0) |
| `headroom_ratio` | Configured-window sensors only: the window divided by its threshold. **1.0 is the crossing point** — above it the appliance still counts as busy, below it the check fires. This is the number to watch while tuning: a working phase that only reaches 1.2 leaves almost no margin, while the measured washer sits around 600 mid-cycle and drops under 1 when it is done. `null` until the window has a verdict. |

A window reports nothing until it has a full span of readings behind it, so after enabling the sensors you wait one window length before the longest ones say anything. They keep measuring across cycle boundaries, though: only *detection* is scoped to the current cycle — a window reaching back past the cycle start would judge the cycle on the quiet that preceded it — while the graph stays continuous.

Windows longer than the appliance's activity all settle on the same value, because they all contain the whole of it. That is the measurement working, not a fault: what distinguishes them is how quickly each one sheds that energy as it ages out, which is exactly what tells you how long a window has to be.

A configured window of 0 is the exception: there is no span to measure, so the check reads live power and the sensor reports nothing rather than a meaningless zero. Your source's own power graph is the tuning view in that case.

---

## Entities

Each configured appliance exposes a small primary set, a set of diagnostic entities, and config controls. Diagnostic and config entities are hidden from the default device card but are fully usable in automations, templates, and other integrations.

### Primary

| Entity | Description |
|---|---|
| `sensor.<name>_state` | Current state: `idle`, `running`, `post_cycle`, `finished`, or `disconnected` |
| `sensor.<name>_cycle_duration` | Wall-clock duration of the current cycle in seconds, displayed as `h min` (frozen when the working phase ends) |
| `sensor.<name>_cycle_energy` | Energy consumed during the current cycle in kWh (frozen at FINISHED) |
| `button.<name>_unloaded` | Acknowledge a finished cycle: POST_CYCLE or FINISHED → IDLE. A no-op in any other state, and the last cycle's duration/energy/start stay readable. This is the one to wire into notifications. |

### Diagnostic

| Entity | Description |
|---|---|
| `binary_sensor.<name>_running` | On while the appliance is actively working (off during the post-cycle phase) |
| `binary_sensor.<name>_finished` | On once the programme is done — including the post-cycle phase, since the load is ready then. Clears when a new cycle starts, or when the cycle is acknowledged with Unloaded or the state is reset. |
| `binary_sensor.<name>_post_cycle` | On only during the post-cycle phase |
| `sensor.<name>_cycle_count` | Number of completed cycles since the counter was last reset |
| `sensor.<name>_cycle_start` | Timestamp when the current/last cycle started |
| `sensor.<name>_total_operating_time` | Lifetime seconds in RUNNING, displayed as `h min` — survives state resets |
| `sensor.<name>_total_energy` | Lifetime energy in kWh (counts all draw, including standby) |
| `sensor.<name>_tuning_*` | Seven windowed-energy sensors for picking windows and thresholds — **disabled by default**, see [Measuring your own appliance](#measuring-your-own-appliance) |

> **Energy Dashboard note**: `total_energy` is exposed as `device_class=ENERGY` so HA will offer it under Settings → Energy → "Add consumption." Prefer your source meter's own energy sensor if it exposes one — those are measured directly by the device, while this one is integrated from power readings (less accurate). Use this one only when your source provides power but no energy.

### Config

| Entity | Action |
|---|---|
| `button.<name>_reset_state` | Force the appliance state to IDLE from *any* state and clear the current cycle's metrics (cycle count and lifetime totals preserved) |
| `button.<name>_reset_cycle_count` | Zero the cycle counter without affecting state |

> **Reset State vs Unloaded**: `reset_state` is the escape hatch for a machine that got stuck in the wrong state — it works from anywhere and discards the current cycle. `unloaded` is the everyday "I emptied it" acknowledgement — it fires on `post_cycle` and `finished`, the two states in which the load is ready, so pressing it mid-wash does nothing.

---

## State machine

```
         power ≥ start_threshold
IDLE ─────────────────────────────► RUNNING
 ▲                                     │
 │                                     │ energy in window < threshold
 │                    ┌────────────────┴────────────────┐
 │                    ▼                                 ▼
 │      POST_CYCLE (if enabled) ────────────────► FINISHED
 │                         energy in window < threshold  │
 └────────── reset button ──────────────────────────────┤
                                                        │
                        power ≥ start_threshold ────────┘──► RUNNING (new cycle)

   POST_CYCLE / FINISHED ──► IDLE
     unloaded button

   (any) ──► DISCONNECTED ──► (resumes prior state on next sample)
     source unavailable
```

(See [Disconnected handling](#disconnected-handling) below for the gap semantics.)

- **IDLE → RUNNING**: power reaches the start threshold (optionally for `start_delay` seconds continuously). Judged on the live reading, so a cycle is picked up at once.
- **RUNNING → RUNNING**: low-draw phases keep the cycle open as long as the window still holds enough energy — common mid-cycle (washer between rinses, dishwasher soaking, etc.).
- **RUNNING → POST_CYCLE**: with the phase enabled, less than the post-cycle threshold is consumed within its window. The cycle is counted here, and `cycle_duration` freezes — the work has stopped.
- **RUNNING → FINISHED**: with the phase disabled, the same check runs against the finished window and threshold instead.
- **POST_CYCLE → FINISHED**: less than the finished threshold is consumed within the finished window. `cycle_energy` keeps counting until here, since the appliance is still drawing.
- **FINISHED → RUNNING**: a new power spike starts a fresh cycle.
- **POST_CYCLE / FINISHED → IDLE**: the Unloaded button acknowledges the cycle. Ignored in every other state, and the last cycle's metrics are kept.
- **Any → IDLE**: the Reset State button forces the machine back to IDLE and clears the current cycle's metrics.

**No cycle can start from POST_CYCLE.** The draw during that phase can sit above `start_threshold` — a washing machine holds 10–16 W — so any live-power check would flap between the two states. Starting a new load before the appliance goes quiet therefore means pressing Unloaded first, which is no imposition: the appliance has to be emptied for that anyway.

No check runs until a full window of readings exists. That single rule covers short cycles, Home Assistant restarts and source outages: an empty window reads as zero energy, which would otherwise finish a cycle instantly.

A sparse source does not delay this. The coordinator samples every 10 seconds regardless of how often the sensor reports — a source that only publishes on change is saying the power is unchanged, and re-reading the same value integrates the consumption correctly. The window therefore fills on schedule whatever the source's update rate, and the guard only applies after a restart or an outage.

### Disconnected handling

When the source power sensor becomes `unavailable` or `unknown` — or starts returning non-numeric values — the state entity reports `disconnected` and the diagnostic binary sensors report `unknown` (their value is undefined while the source is silent). The state machine pauses cleanly: no energy is integrated across the gap, the sample window is dropped, and lifetime totals stay frozen. On reconnect, the previous state is restored and counting resumes once a fresh window has been collected — the same behavior as recovering from a Home Assistant restart.

Note: this only catches sources that explicitly report unavailable. A source that goes silent while still showing its last value (some MQTT setups without LWT, partial device failures) will look like steady power to the integration — that's a limitation of the source, not something this integration tries to second-guess.

---

## Development

```bash
scripts/setup      # install dependencies (incl. pytest)
scripts/develop    # start Home Assistant at localhost:8123
scripts/lint       # ruff format + ruff check --fix
scripts/test       # run the test suite (forwards args, e.g. `scripts/test -k disconnect`)
```

The devcontainer (`.devcontainer.json`) uses Python 3.14 and runs `scripts/setup` automatically on creation.
