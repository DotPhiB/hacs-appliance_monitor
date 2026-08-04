# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `button.<name>_unloaded` — acknowledges a finished cycle (POST_CYCLE or FINISHED → IDLE) and is a no-op in every other state, so a stray press cannot cut a running cycle short. Last-cycle duration, energy and start timestamp are preserved.
- **Tuning sensors** — seven diagnostic sensors reporting the energy consumed over a trailing window (30 s, 1/2/5/10 min, plus one for each configured window), updated on every reading whatever state the appliance is in. Disabled by default: enable them, run a cycle, and read the working/post-cycle/standby bands straight off the history graph instead of estimating areas under a power curve. Attributes carry the window length, how many readings the source itself published inside it (poll re-reads excluded, so `0` honestly means a silent source), what triggered the update, and — for the configured windows — the threshold being compared against plus a `headroom_ratio` where 1.0 is the point at which the check fires.
- Optional **post-cycle** phase for appliances that keep drawing power after the programme ends (anti-crease tumbling, drying, cooling). New `post_cycle` state value, `binary_sensor.<name>_post_cycle`, and a config toggle with its own window and threshold. It splits the end of a cycle into two reportable states — programme done, and appliance quiet — which were previously collapsed into one; `binary_sensor.<name>_finished` covers both, so notifications fire when the load is ready. `cycle_duration` freezes when the working phase ends while `cycle_energy` keeps counting to `finished`, and no new cycle can start out of the phase — press Unloaded first. On real washing-machine cycles, detecting the phase moved the end-of-programme signal 40 minutes earlier than 1.0.0 reported it.

### Changed
- `cycle_duration` and `cycle_energy` are no longer diagnostic entities — the current cycle's figures show on the default device card next to the state and the Unloaded button.
- `cycle_duration` and `total_operating_time` default to an hours display (`1 h 32 min`) instead of raw seconds. Values are still stored in seconds; the display unit stays switchable per entity, and existing entities keep whatever unit they are set to.
- **Breaking** — the end of a cycle is judged on **energy consumed within a sliding window** instead of live power against an idle threshold. `idle_threshold` and `idle_timeout` are replaced by `finished_window` + `finished_energy_threshold`; the window is also the shortest cycle that can be detected, and setting it to 0 takes the check at a point instead, reading the threshold as watts. Existing entries migrate automatically: the old pair becomes `idle_threshold × idle_timeout / 3600` Wh over an `idle_timeout` window, and an `idle_timeout` of 0 becomes a window of 0 with the threshold carried over untouched.

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
