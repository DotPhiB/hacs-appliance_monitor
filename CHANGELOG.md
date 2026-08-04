# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `button.<name>_unloaded` — acknowledges a finished cycle (POST_CYCLE or FINISHED → IDLE) and is a no-op in every other state, so a stray press cannot cut a running cycle short. Last-cycle duration, energy and start timestamp are preserved.
- Optional **post-cycle** phase for appliances that keep drawing power after the programme ends (anti-crease tumbling, drying, cooling). New `post_cycle` state value, `binary_sensor.<name>_post_cycle`, and a config toggle with its own window and threshold. It splits the end of a cycle into two reportable states — programme done, and appliance quiet — which were previously collapsed into one. On real washing-machine cycles, detecting the phase moved the end-of-programme signal 40 minutes earlier than 1.0.0 reported it.
- `binary_sensor.<name>_finished` covers the post-cycle phase, so notifications fire when the load is ready rather than when the appliance stops drawing.

### Changed
- `cycle_duration` and `cycle_energy` are no longer diagnostic entities — the current cycle's figures show on the default device card next to the state and the Unloaded button.
- `cycle_duration` and `total_operating_time` default to an hours display (`1 h 32 min`) instead of raw seconds. Values are still stored in seconds; the display unit stays switchable per entity, and existing entities keep whatever unit they are set to.
- **Breaking** — the end of a cycle is judged on **energy consumed within a sliding window** instead of live power against an idle threshold. `idle_threshold` and `idle_timeout` are replaced by `finished_window` + `finished_energy_threshold`. Existing entries migrate automatically: the old pair becomes `idle_threshold × idle_timeout / 3600` Wh over an `idle_timeout` window, preserving the previous tuning.
- No detection runs until a full window of readings exists. The window length is therefore also the shortest detectable cycle, and it is what stops a Home Assistant restart or a source outage from reading as zero consumption and finishing a cycle instantly.
- `cycle_duration` freezes when the working phase ends; `cycle_energy` keeps counting through the post-cycle phase and freezes at `finished`.
- A new cycle can no longer start out of the post-cycle phase — that phase's draw can exceed `start_threshold`, which would flap between the two states. Press Unloaded first if a new load is started before the appliance goes quiet.

## [1.0.0] - 2026-05-30

Initial public release.

### Added
- Power-driven appliance state machine: `idle`, `running`, `finished`, `disconnected`
- Per-cycle metrics: duration, energy, start timestamp
- Lifetime metrics: cycle count, operating time, total energy (Energy Dashboard compatible)
- Reset buttons for state and cycle counter
- Persistent state and totals across Home Assistant restarts
- Event-driven updates on every source-sensor change, with 10 s polling fallback
- Configurable start threshold, idle threshold, idle timeout, and optional start delay
- Config-entry diagnostics download

### Notes
- Source-sensor unavailability surfaces as `disconnected`; previous state is preserved and resumed on reconnect.
- `cycle_count` and lifetime totals are persisted immediately on cycle completion (no debounce window where data can be lost on ungraceful shutdown).
