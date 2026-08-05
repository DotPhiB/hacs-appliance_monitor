# Measurements

The recordings every number in the README's [Tuning](../../README.md#tuning) section is derived from, and the script that derives them.

```bash
python3 docs/measurements/derive.py
```

It replays each trace through the same rules the integration applies, using the settings the README recommends for that appliance, and prints what those settings would have decided: where each phase began, how quiet the working phase got, and how loud the post-cycle phase got. Every figure quoted in the README appears in that output.

## The traces

| File | Appliance | Cycles | Readings |
|---|---|---|---|
| `washer-2026-05-27.csv` | Washing machine | 2 | 9449 |
| `washer-2026-06-02.csv` | Washing machine | 1 | 935 |
| `dryer-2026-05-27.csv` | Dryer | 3 | 274 |

Both appliances are measured with a **Shelly Plug S Gen3**, reporting live power in watts. Everything about the shape of these files — how often a row appears, how quiet a quiet appliance looks — is a property of that plug and its reporting rules, not of the appliance alone. A plug with a different reporting threshold produces a different trace from the same wash.

The files are Home Assistant history exports, unedited:

```csv
entity_id,state,last_changed
sensor.shelly_plug_sg3_wk_waschmaschine_wk_waschmaschine_leistung,1.1,2026-05-27T08:32:51.341Z
```

## Two things to know before using them

**A trace is a step function, not a series of samples.** The recorder stores state *changes*, so each row means "the power became this, and stayed there until the next row". Averaging the rows as if they were evenly spaced gives the wrong answer, and the error is large: the dryer publishes 274 rows across two days, most of them minutes apart. Weight every reading by how long it was in force. `Trace.average()` in `derive.py` does this by building the cumulative energy curve behind the trace and taking its rise across a window — which is the same quantity the integration compares against a threshold.

**The integration looks at every source update, with a 10 s poll underneath it.** The poll means a source that publishes nothing is read as "unchanged", so the sliding window fills on schedule however quiet the plug is; the event side means a spike shorter than the poll interval is still seen. Both halves matter here: the dryer's third cycle starts on a **one-second** 364 W inrush, which a 10 s poller alone would step straight over — and with it, ten minutes of that cycle. `derive.py` replays on the union of the two, which is why some phase boundaries land on ten-second marks and others on a source reading.

## What is not here

The tuning-sensor recordings from the sandbox and the integration's own `cycle_energy` exports are deliberately left out. They are output, not measurement: they show what the integration did, not what the appliance drew, so nothing in the README rests on them.
