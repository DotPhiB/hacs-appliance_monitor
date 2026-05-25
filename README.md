# Appliance Monitor

A Home Assistant custom integration that monitors appliance power consumption and automatically detects when an appliance is running, paused, or finished with a cycle.

Designed for washing machines, dishwashers, dryers, and any appliance with a measurable power draw pattern.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

---

> **A note on how this was built:** I'm not a Python developer. This integration was built with AI assistance — not by blindly accepting generated code, but by understanding the decisions and iterating deliberately. I've done my best to follow Home Assistant conventions and Python best practices, but if something doesn't meet your expectations as an experienced developer, I'd genuinely welcome the feedback. Issues and PRs are open.

---

## Features

- Detects **running**, **paused**, and **finished** states from a single power sensor
- Exposes state as HA binary sensors and sensors — ready for automations and dashboards
- Handles temporary idle periods mid-cycle (spin-pause, dishwasher drying phase, etc.)
- Configurable start and pause delays (hysteresis) to filter brief power spikes and mid-cycle dips
- All thresholds and timeouts are adjustable post-setup via the integration's options

---

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** → three-dot menu → **Custom repositories**.
3. Add `https://github.com/dotphib/appliance_monitor` as an **Integration**.
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
| Start delay (s) | Seconds power must stay above the start threshold before a cycle begins. Filters brief spikes. | 0 s |
| Idle threshold (W) | Power below this level means the appliance is idle or paused | 3 W |
| Pause delay (s) | Seconds power must stay below the idle threshold before the appliance is considered paused. Filters mid-cycle dips. | 0 s |
| Idle timeout (min) | Minutes of sustained low power (after the pause delay) before a cycle is marked finished | 5 min |

All fields except the power sensor can be changed at any time via **Settings → Devices & Services → Appliance Monitor → Configure**.

---

## Entities

Each configured appliance exposes the following entities:

### Binary sensors

| Entity | On when |
|---|---|
| `binary_sensor.<name>_running` | Appliance is actively running |
| `binary_sensor.<name>_finished` | Last cycle has finished (resets when a new cycle starts) |

### Sensors

| Entity | Description |
|---|---|
| `sensor.<name>_state` | Current state: `idle`, `running`, `paused`, or `finished` |
| `sensor.<name>_runtime` | Accumulated runtime of the current cycle in seconds |

---

## State machine

```
         power > start_threshold
IDLE ─────────────────────────────► RUNNING
 ▲                                   │    ▲
 │                          power <  │    │ power >
 │                       idle_thresh │    │ start_thresh
 │                                   ▼    │
 │              timeout          PAUSED ──┘
 │           exceeded
FINISHED ◄──────────────────────────┘
   │
   └── power > start_threshold ──► RUNNING (new cycle)
```

- **IDLE → RUNNING**: power exceeds the start threshold (optionally for `start_delay` seconds continuously).
- **RUNNING → PAUSED**: power stays below the idle threshold for `pause_delay` seconds continuously.
- **PAUSED → RUNNING**: power recovers above the start threshold before the timeout expires.
- **PAUSED → FINISHED**: power stays low for longer than the idle timeout.
- **FINISHED → RUNNING**: a new power spike starts a fresh cycle.

---

## Development

```bash
scripts/setup      # install dependencies
scripts/develop    # start Home Assistant at localhost:8123
scripts/lint       # ruff format + ruff check --fix
```

The devcontainer (`.devcontainer.json`) uses Python 3.14 and runs `scripts/setup` automatically on creation.
