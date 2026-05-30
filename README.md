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
- Exposes state as HA binary sensors and sensors — ready for automations and dashboards
- Keeps the cycle in RUNNING through intermediate low-draw phases (spin-pause, dishwasher drying, oven holding temp) — only marks FINISHED when power stays low past the idle timeout
- Configurable start delay (hysteresis) to filter brief power spikes
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
| Start delay (s) | Seconds power must stay at or above the start threshold before a cycle begins. Filters brief spikes. | 0 s |
| Idle threshold (W) | Power below this level signals the appliance is idle or about to finish | 3 W |
| Idle timeout (s) | Seconds power must stay below the idle threshold before the cycle is marked finished. Brief dips above the threshold reset this timer, so mid-cycle low-draw phases keep the appliance RUNNING. Set to 0 for an instant transition. | 30 s |

All fields except the power sensor can be changed at any time via **Settings → Devices & Services → Appliance Monitor → Configure**.

---

## Entities

Each configured appliance exposes the following entities:

### Binary sensors

| Entity | On when |
|---|---|
| `binary_sensor.<name>_running` | Appliance is actively running |
| `binary_sensor.<name>_finished` | Last cycle has finished (resets when a new cycle starts or the Reset button is pressed) |

### Sensors

| Entity | Description |
|---|---|
| `sensor.<name>_state` | Current state: `idle`, `running`, or `finished` |
| `sensor.<name>_cycle_count` | Number of completed cycles since the counter was last reset |
| `sensor.<name>_cycle_duration` | Wall-clock duration of the current cycle in seconds (frozen at FINISHED) |
| `sensor.<name>_cycle_energy` | Energy consumed during the current cycle in kWh (frozen at FINISHED) |
| `sensor.<name>_cycle_start` _(diagnostic)_ | Timestamp when the current/last cycle started |
| `sensor.<name>_total_operating_time` _(diagnostic)_ | Lifetime seconds in RUNNING — survives state resets |
| `sensor.<name>_total_energy` | Lifetime energy in kWh (counts all draw, including standby) — Energy Dashboard compatible |

### Buttons

| Entity | Action |
|---|---|
| `button.<name>_reset_state` _(config)_ | Reset the appliance state to IDLE (clears finished notification; cycle count and totals preserved) |
| `button.<name>_reset_cycle_count` _(config)_ | Zero the cycle counter without affecting state |

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
```

- **IDLE → RUNNING**: power reaches the start threshold (optionally for `start_delay` seconds continuously).
- **RUNNING → RUNNING**: brief dips below the idle threshold keep state RUNNING — common during intermediate phases (washer between rinses, dishwasher soaking, etc.). The idle countdown restarts on each recovery.
- **RUNNING → FINISHED**: power stays below the idle threshold continuously for longer than `idle_timeout`.
- **FINISHED → RUNNING**: a new power spike starts a fresh cycle.
- **Any → IDLE**: the Reset State button forces the machine back to IDLE.

---

## Development

```bash
scripts/setup      # install dependencies
scripts/develop    # start Home Assistant at localhost:8123
scripts/lint       # ruff format + ruff check --fix
```

The devcontainer (`.devcontainer.json`) uses Python 3.14 and runs `scripts/setup` automatically on creation.
