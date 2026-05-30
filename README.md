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
- Exposes a single primary state entity plus diagnostic sensors — automations work off either
- Keeps the cycle in RUNNING through intermediate low-draw phases (spin-pause, dishwasher drying, oven holding temp) — only marks FINISHED when power stays low past the idle timeout
- Optional start delay to ignore brief startup spikes (e.g. inrush current when the appliance is first plugged in)
- Reports a **disconnected** state when the source power sensor goes unavailable, without corrupting energy totals or firing spurious transitions across the gap
- State and lifetime totals survive Home Assistant restarts
- All thresholds and timeouts are adjustable post-setup via the integration's options

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
| Idle threshold (W) | Power below this level signals the appliance is idle or about to finish | 3 W |
| Idle timeout (s) | Seconds power must stay below the idle threshold before the cycle is marked finished. Brief dips above the threshold reset this timer, so mid-cycle low-draw phases keep the appliance RUNNING. Set to 0 for an instant transition. | 30 s |

All fields except the power sensor can be changed at any time via **Settings → Devices & Services → Appliance Monitor → Configure**.

---

## Entities

Each configured appliance exposes one primary entity, a set of diagnostic entities, and config controls. Diagnostic and config entities are hidden from the default device card but are fully usable in automations, templates, and other integrations.

### Primary

| Entity | Description |
|---|---|
| `sensor.<name>_state` | Current state: `idle`, `running`, `finished`, or `disconnected` |

### Diagnostic

| Entity | Description |
|---|---|
| `binary_sensor.<name>_running` | On while the appliance is actively running |
| `binary_sensor.<name>_finished` | On after a cycle finishes; clears when a new cycle starts or the state is reset |
| `sensor.<name>_cycle_count` | Number of completed cycles since the counter was last reset |
| `sensor.<name>_cycle_duration` | Wall-clock duration of the current cycle in seconds (frozen at FINISHED) |
| `sensor.<name>_cycle_energy` | Energy consumed during the current cycle in kWh (frozen at FINISHED) |
| `sensor.<name>_cycle_start` | Timestamp when the current/last cycle started |
| `sensor.<name>_total_operating_time` | Lifetime seconds in RUNNING — survives state resets |
| `sensor.<name>_total_energy` | Lifetime energy in kWh (counts all draw, including standby) |

> **Energy Dashboard note**: `total_energy` is exposed as `device_class=ENERGY` so HA will offer it under Settings → Energy → "Add consumption." Prefer your source meter's own energy sensor if it exposes one — those are measured directly by the device, while this one is integrated from power readings (less accurate). Use this one only when your source provides power but no energy.

### Config

| Entity | Action |
|---|---|
| `button.<name>_reset_state` | Reset the appliance state to IDLE (clears finished notification; cycle count and totals preserved) |
| `button.<name>_reset_cycle_count` | Zero the cycle counter without affecting state |

---

## State machine

```
         power > start_threshold
IDLE ─────────────────────────────► RUNNING ◄──── (brief dips reset timer)
 ▲                                     │
 │                                     │ power < idle_threshold
 │                                     │ for idle_timeout seconds continuously
 │                                     ▼
 └────────── reset button ───────── FINISHED
                                       │
                                       └── power > start_threshold ──► RUNNING (new cycle)

   (any) ──► DISCONNECTED ──► (resumes prior state on next sample)
     source unavailable
```

(See [Disconnected handling](#disconnected-handling) below for the gap semantics.)

- **IDLE → RUNNING**: power reaches the start threshold (optionally for `start_delay` seconds continuously).
- **RUNNING → RUNNING**: brief dips below the idle threshold keep state RUNNING — common during intermediate phases (washer between rinses, dishwasher soaking, etc.). The idle countdown restarts on each recovery.
- **RUNNING → FINISHED**: power stays below the idle threshold continuously for at least `idle_timeout` seconds.
- **FINISHED → RUNNING**: a new power spike starts a fresh cycle.
- **Any → IDLE**: the Reset State button forces the machine back to IDLE.

### Disconnected handling

When the source power sensor becomes `unavailable` or `unknown` — or starts returning non-numeric values — the state entity reports `disconnected` and the diagnostic binary sensors (`running`, `finished`) report `unknown` (their value is undefined while the source is silent). The state machine pauses cleanly: no energy is integrated across the gap, the idle countdown is cleared, and lifetime totals stay frozen. On reconnect, the previous state (IDLE/RUNNING/FINISHED) is restored and counting resumes from the next fresh sample — the same behavior as recovering from a Home Assistant restart.

Note: this only catches sources that explicitly report unavailable. A source that goes silent while still showing its last value (some MQTT setups without LWT, partial device failures) will look like steady power to the integration — that's a limitation of the source, not something this integration tries to second-guess.

---

## Development

```bash
scripts/setup      # install dependencies
scripts/develop    # start Home Assistant at localhost:8123
scripts/lint       # ruff format + ruff check --fix
```

The devcontainer (`.devcontainer.json`) uses Python 3.14 and runs `scripts/setup` automatically on creation.
