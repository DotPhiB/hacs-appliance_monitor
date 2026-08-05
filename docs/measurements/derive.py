"""
Reproduce the numbers the README's tuning tables are built from.

    python3 docs/measurements/derive.py

It replays each trace through the same rules the integration applies, using
the settings the README recommends for that appliance, and prints what those
settings would have decided and how much headroom they had.

Two properties of the data drive everything here, both explained in the
README next to these files: a trace is a step function, and the integration
looks at every source update with a 10 s poll underneath it, rather than at
either one alone.
"""

from __future__ import annotations

import bisect
import csv
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

POLL_SECONDS = 10.0

# The windows quoted in the README's bands table, in seconds.
BAND_WINDOWS = (30.0, 60.0, 300.0, 720.0)


class Settings(NamedTuple):
    """The four numbers the README recommends for one appliance."""

    start_w: float
    post_cycle_window: float
    post_cycle_w: float
    finished_window: float
    finished_w: float


SETTINGS = {
    "washer": Settings(40.0, 300.0, 20.0, 300.0, 2.0),
    "dryer": Settings(100.0, 60.0, 50.0, 720.0, 1.0),
}

# Start thresholds to time at every cycle start, alongside the configured one.
# A start threshold is judged on the live reading, so the only thing worth
# knowing about a candidate is how long it takes to clear and how long it
# stays cleared — a start delay longer than the hold rejects the start.
START_CANDIDATES = (10.0, 40.0, 100.0, 200.0, 500.0)


class Trace:
    """
    A recorded power history, averaged the way the integration averages it.

    Each reading holds until the next one, so the energy behind the trace is
    a running sum of `watts × seconds held`. An average over a window is the
    rise of that sum across the window divided by its length — the same
    quantity the integration compares against its thresholds.
    """

    def __init__(self, rows: list[tuple[datetime, float]]) -> None:
        """Build the cumulative-energy curve behind *rows*."""
        self.stamps = [stamp for stamp, _ in rows]
        self.watts = [watts for _, watts in rows]
        self.energy = [0.0]
        for index in range(1, len(rows)):
            held = (self.stamps[index] - self.stamps[index - 1]).total_seconds()
            self.energy.append(self.energy[-1] + self.watts[index - 1] * held)

    def __len__(self) -> int:
        """Return the number of readings."""
        return len(self.stamps)

    def index_at(self, when: datetime) -> int:
        """Return the index of the reading in force at *when*."""
        return max(bisect.bisect_right(self.stamps, when) - 1, 0)

    def power_at(self, when: datetime) -> float:
        """Return the live reading in force at *when*."""
        return self.watts[self.index_at(when)]

    def _energy_at(self, when: datetime) -> float:
        """Return the cumulative energy in watt-seconds at *when*."""
        index = self.index_at(when)
        held = (when - self.stamps[index]).total_seconds()
        return self.energy[index] + self.watts[index] * held

    def average(self, when: datetime, window: float) -> float:
        """Return the average power over the *window* seconds ending at *when*."""
        rise = self._energy_at(when) - self._energy_at(when - timedelta(seconds=window))
        return rise / window


def load(path: Path) -> Trace:
    """Read a Home Assistant history export into a trace."""
    rows: list[tuple[datetime, float]] = []
    with path.open(newline="") as handle:
        for record in csv.DictReader(handle):
            try:
                watts = float(record["state"])
            except ValueError:
                continue  # unavailable / unknown
            stamp = record["last_changed"].replace("Z", "+00:00")
            rows.append((datetime.fromisoformat(stamp), watts))
    rows.sort(key=lambda row: row[0])
    return Trace(rows)


class Phase(NamedTuple):
    """One detected phase of a cycle."""

    name: str
    start: datetime
    end: datetime | None


def evaluation_points(trace: Trace) -> list[datetime]:
    """
    Return every moment the integration would have run its checks.

    It is event-driven with a poll as a floor: every source update is looked
    at, and a 10 s tick covers the stretches where the source says nothing.
    The difference is not academic — a one-second spike between two ticks is
    a cycle start the poller alone would never see.
    """
    grid = []
    cursor, last = trace.stamps[0], trace.stamps[-1]
    while cursor <= last:
        grid.append(cursor)
        cursor += timedelta(seconds=POLL_SECONDS)
    return sorted({*trace.stamps, *grid})


def replay(trace: Trace, settings: Settings) -> list[Phase]:
    """
    Run the detection rules over the trace the way the integration runs them.

    Checks are scoped to the phase being judged: a window is only evaluated
    once it lies entirely inside the current phase, so no phase is ended on
    evidence from the one before it.
    """
    phases: list[Phase] = []
    state, floor = "idle", trace.stamps[0]
    for cursor in evaluation_points(trace):
        elapsed = (cursor - floor).total_seconds()
        if state in {"idle", "finished"}:
            if trace.power_at(cursor) >= settings.start_w:
                if phases:
                    phases[-1] = phases[-1]._replace(end=cursor)
                phases.append(Phase("running", cursor, None))
                state, floor = "running", cursor
        elif state == "running":
            if (
                elapsed >= settings.post_cycle_window
                and trace.average(cursor, settings.post_cycle_window) < settings.post_cycle_w
            ):
                phases[-1] = phases[-1]._replace(end=cursor)
                phases.append(Phase("post_cycle", cursor, None))
                state, floor = "post_cycle", cursor
        elif (
            elapsed >= settings.finished_window
            and trace.average(cursor, settings.finished_window) < settings.finished_w
        ):
            phases[-1] = phases[-1]._replace(end=cursor)
            phases.append(Phase("finished", cursor, None))
            state, floor = "finished", cursor
    return phases


def band(trace: Trace, phase: Phase, window: float, *, quietest: bool) -> float | None:
    """
    Return the extreme average this phase reached over *window*.

    Only positions whose window lies inside the phase are considered — the
    same scoping the checks use, and the reason a short phase reports nothing
    for a long window.

    A working phase also drops its final window: that stretch is the appliance
    winding down, and its minimum is by construction the value that ended the
    phase, which says nothing about how quiet the phase got while working.
    """
    end = phase.end or trace.stamps[-1]
    if quietest and phase.end is not None:
        end -= timedelta(seconds=window)
    first = phase.start + timedelta(seconds=window)
    if first > end:
        return None
    values = []
    cursor = first
    while cursor <= end:
        values.append(trace.average(cursor, window))
        cursor += timedelta(seconds=POLL_SECONDS)
    return min(values) if quietest else max(values)


def bursts(trace: Trace, phase: Phase, level: float = 40.0) -> list[tuple[datetime, float, float]]:
    """
    Return the (start, seconds, peak) of every burst above *level* in a phase.

    Anti-crease tumbling shows up here and nowhere else: a burst is far too
    short to lift any window average, so its length and spacing are the only
    way to see it — and the spacing is what a finished window has to outlast.
    """
    end = phase.end or trace.stamps[-1]
    found: list[tuple[datetime, float, float]] = []
    start: datetime | None = None
    peak = 0.0
    for stamp, watts in zip(trace.stamps, trace.watts, strict=True):
        if not phase.start <= stamp <= end:
            continue
        if watts >= level and start is None:
            start, peak = stamp, watts
        elif watts >= level:
            peak = max(peak, watts)
        elif start is not None:
            found.append((start, (stamp - start).total_seconds(), peak))
            start, peak = None, 0.0
    return found


def peak_reading(trace: Trace, phase: Phase, trim: float = 0.0) -> float:
    """
    Return the highest single reading recorded inside a phase.

    *trim* drops that many seconds from the end, which is what makes the
    reading meaningful for a finished phase: its final minutes are the next
    cycle winding up, and standby is the question being asked.
    """
    end = (phase.end or trace.stamps[-1]) - timedelta(seconds=trim)
    inside = [w for s, w in zip(trace.stamps, trace.watts, strict=True) if phase.start <= s <= end]
    return max(inside, default=0.0)


def time_to_start(trace: Trace, start: datetime, threshold: float) -> tuple[float, float]:
    """
    Return how long the start threshold took to clear, and how long it held.

    Measured from the moment the draw left standby, which is the last reading
    at or below 1 W before the cycle. The hold matters because a start delay
    longer than it would reject the start.
    """
    index = trace.index_at(start)
    while index > 0 and trace.watts[index - 1] > 1.0:
        index -= 1
    onset = trace.stamps[index]
    reached = next(
        (s for s, w in zip(trace.stamps, trace.watts, strict=True) if s >= onset and w >= threshold),
        None,
    )
    if reached is None:
        return (float("nan"), 0.0)
    held, cursor = 0.0, reached
    while trace.power_at(cursor) >= threshold and held < 600:
        held += POLL_SECONDS / 2
        cursor += timedelta(seconds=POLL_SECONDS / 2)
    return ((reached - onset).total_seconds(), held)


def minutes(span: timedelta) -> str:
    """Format a duration the way the README quotes them."""
    total = int(span.total_seconds() // 60)
    return f"{total // 60} h {total % 60:02d} min" if total >= 60 else f"{total} min"


def report(path: Path) -> None:
    """Replay one trace and print what the recommended settings decided."""
    kind = "dryer" if "dryer" in path.name else "washer"
    settings = SETTINGS[kind]
    trace = load(path)
    phases = replay(trace, settings)
    cycles = sum(1 for phase in phases if phase.name == "running")
    print(f"\n=== {path.name} — {len(trace)} readings, {cycles} cycles, as a {kind}")
    print(
        f"    start {settings.start_w:g} W | post-cycle {settings.post_cycle_window:g} s"
        f" / {settings.post_cycle_w:g} W | finished {settings.finished_window:g} s"
        f" / {settings.finished_w:g} W"
    )
    for position, phase in enumerate(phases):
        end = phase.end
        span = minutes(end - phase.start) if end else "still open at end of trace"
        print(f"\n  {phase.name:<11} {phase.start:%m-%d %H:%M:%S}  ({span})")
        if phase.name == "running":
            previous = phases[position - 1] if position else None
            if previous is not None and previous.name == "post_cycle":
                print("    starts out of the previous cycle's post-cycle phase")
            else:
                print("    from the moment the draw left standby, a start threshold of")
                for candidate in sorted({*START_CANDIDATES, settings.start_w}):
                    delay, held = time_to_start(trace, phase.start, candidate)
                    if math.isnan(delay):
                        continue  # never reached in this trace
                    mark = "*" if candidate == settings.start_w else " "
                    holds = ">=600" if held >= 600 else f"{held:.0f}"
                    print(
                        f"     {mark} {candidate:5.0f} W is cleared after {delay:5.0f} s, "
                        f"then holds {holds:>5} s"
                    )
        if phase.name == "finished":
            idle = peak_reading(trace, phase, trim=300.0)
            print(f"    highest single reading while idle {idle:.1f} W")
            continue
        for window in BAND_WINDOWS:
            value = band(trace, phase, window, quietest=phase.name == "running")
            if value is None:
                continue
            edge = "falls to" if phase.name == "running" else "rises to"
            print(f"    {window:5.0f} s window {edge} {value:8.1f} W")
        print(f"    highest single reading {peak_reading(trace, phase):.1f} W")
        found = bursts(trace, phase)
        if phase.name == "post_cycle" and found:
            gaps = [
                (later[0] - earlier[0]).total_seconds()
                for earlier, later in zip(found, found[1:], strict=False)
            ]
            spacing = f", {min(gaps):.0f}-{max(gaps):.0f} s apart" if gaps else ""
            print(
                f"    {len(found)} bursts above 40 W: "
                f"{min(b[1] for b in found):.0f}-{max(b[1] for b in found):.0f} s long"
                f"{spacing}"
            )


def main(names: list[str]) -> None:
    """Report every trace given on the command line, or all of them."""
    paths = [Path(name) for name in names] or sorted(Path(__file__).parent.glob("*.csv"))
    for path in paths:
        report(path)


if __name__ == "__main__":
    main(sys.argv[1:])
