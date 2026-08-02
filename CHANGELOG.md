# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `button.<name>_unloaded` — acknowledges a finished cycle (FINISHED → IDLE) and is a no-op in every other state, so a stray press cannot cut a running cycle short. Last-cycle duration, energy and start timestamp are preserved.

### Changed
- `cycle_duration` and `cycle_energy` are no longer diagnostic entities — the current cycle's figures show on the default device card next to the state and the Unloaded button.
- `cycle_duration` and `total_operating_time` default to an hours display (`1 h 32 min`) instead of raw seconds. Values are still stored in seconds; the display unit stays switchable per entity, and existing entities keep whatever unit they are set to.

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
