# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
