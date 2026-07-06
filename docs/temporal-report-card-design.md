# Temporal Report Card Design

## Overview

This document specifies how `ben0 report-card` adds temporal and historical comparison
capabilities to the collection biodiversity report card. The existing command produces a
point-in-time snapshot of the current collection. The extensions described here let curators
reconstruct past states, focus metrics on a time window, and compare two periods side by side.

---

## Background: the data model's temporal structure

The item history table (`accession_item_history.csv`, ingested as the Event table) stores
one row per status interval, not one row per item. Each row carries:

- `ItemStatusDateFrom` / `ItemStatusDateTo`: the open interval during which that status held.
  A `DateTo` of `12/31/9999` means "still active."
- `ItemStatusType`: `Existing`, `NotExisting`, `Procedure`, or `Unknown`.
- `ItemStatus`: the human label (e.g. `Planted`, `Dead`, `Removed/Discarded`).

This means the item history is already a complete bitemporal log. Snapshot reconstruction
does not require any new data collection: it requires querying against a date boundary.

Accession-level date anchors live in `accession_history.csv` as `AccYear`, `RecDate`,
`CollDate`, and `RegisterDate`. These are used to determine when an accession entered the
collection.

---

## Design decisions

### 1. Defining "alive at date X"

An item is alive at date X if, across all its history rows, the row whose interval
contains X (i.e. `DateFrom <= X < DateTo`, treating 9999-12-31 as infinity) has
`ItemStatusType = Existing`.

The `ItemStatusType` field is the authoritative alive/not-alive signal. `ItemStatus`
values are used secondarily to classify the nature of the event (planted, observed, dead,
etc.) but are NOT the primary alive filter. The rationale: `ItemStatusType` is the
machine-readable field; `ItemStatus` labels are inconsistently worded across eras.

Edge case: if no interval covers date X for a given item (gaps in the log), the item is
treated as `unknown` at that date and excluded from alive counts. Unknown items are
reported in a separate "undatable items" footnote in snapshot output.

Edge case: items with `ItemStatusType = Procedure` (propagation workflow states) are
excluded from alive/dead classification. Propagation items are counted separately in the
Nursery Pipeline section.

### 2. Snapshot reconstruction

A snapshot at date X is constructed by:

1. Filtering `item_history` rows to those where `DateFrom <= X`.
2. For each item, selecting the row with the highest `DateFrom` that does not exceed X
   (the "last known state before or on X").
3. Classifying that row's `ItemStatusType` as alive or not.
4. Joining to accession and taxon records using the accession history state as of X.
   For accession-level attributes (taxonomy, IUCN status, provenance), the current
   values are used unless a historical override is explicitly stored. The data model
   does not version accession attributes, so taxonomy and conservation status are
   taken from current records with a caveat note in output.

Accession history rows are filtered by `AccYear <= X.year` (or `RecDate <= X` where
present) to exclude accessions not yet acquired at the snapshot date.

Implementation: a reusable `CollectionSnapshot` class wraps the SQLAlchemy session and
applies date filters. All eight report card sections receive a snapshot context object
rather than querying live tables directly.

### 3. Per-section behavior: snapshot-able vs window-only vs both

| Section | Snapshot mode | Window mode | Notes |
|---|---|---|---|
| 1. Taxonomic Diversity | yes | yes | Alive count at snapshot; new taxa in window |
| 2. Conservation Value | yes | yes | Conservation profile at snapshot; threatened taxa gained/lost in window |
| 3. Provenance & Documentation | yes | yes | Snapshot provenance scores; new wild-origin accessions in window |
| 4. Genetic Representation / Collection Security | yes | no | Needs per-accession item counts; not meaningful as a flow |
| 5. Collection Dynamics | window-primary | yes | Acquisitions and losses are inherently a flow metric; snapshot gives a rate proxy |
| 6. Climate Readiness | yes | yes | Score computed from current taxonomy + provenance; window shows taxa acquired from climate-exposed origins |
| 7. Nursery Pipeline | window-primary | yes | Propagation throughput is a flow; snapshot shows pipeline depth at a moment |
| 8. Data Integrity | yes | yes | Issue counts at snapshot; issue creation/resolution rate in window |

Sections marked "window-primary" still produce output in snapshot mode but include a
notice that the metric is more meaningful over a window.

### 4. Window mode mechanics

Window mode (`--period START:END`) counts events and acquisitions that occurred within
the half-open interval `[START, END)`. Specifically:

- An accession is "acquired in window" if `RecDate` (or `AccYear` when `RecDate` is null)
  falls in the window.
- An item is "lost in window" if its terminal event's `DateFrom` falls in the window.
  Terminal statuses: rows where `ItemStatusType = NotExisting` and `ItemStatus` in
  `{Dead, Dead - Natural cause, Dead - Horticultural cause, Not found, Removed/Discarded,
  Removed, Weeded, Stolen, Given away, Reassigned to new accession}`.
- Propagation events: `Prop: Success` and `Prop: Failure (did not germinate or root)`
  rows whose `DateFrom` falls in the window.

The window start date is also used as an implicit "opening snapshot" when computing
deltas. The window end date is used as the "closing snapshot." This allows window mode
to report both flow metrics and endpoint-to-endpoint delta scores.

### 5. Output format

Both modes produce the same Markdown and JSON outputs as the base command. The format
is extended as follows:

**Markdown**: each section gains a "Temporal context" subsection that shows:
- For snapshot mode: the reconstructed date and item/accession counts at that date.
- For window mode: acquisitions, losses, and net change during the window.
- For comparison mode: a side-by-side table with A value, B value, delta, and a
  trend symbol (`+`, `-`, `~`) for each key metric.

**JSON**: the root object gains a `temporal` key:

```json
{
  "mode": "snapshot" | "window" | "compare",
  "snapshot_date": "2020-12-31",          // snapshot mode
  "period_start": "2020-01-01",           // window mode
  "period_end": "2024-12-31",             // window mode
  "compare_a": { ... },                   // compare mode: first context
  "compare_b": { ... },                   // compare mode: second context
  "sections": { ... }                     // same structure as current
}
```

Traffic-light scores in comparison mode carry a second field `trend`:
`"improving"`, `"stable"`, or `"declining"`. Thresholds for trend are
section-specific and defined in `constants.py`. A change below 5% of the
max score for a section is treated as stable.

### 6. Performance

Snapshot reconstruction against the full item history table (141,422 rows) is a single
indexed query. The ingest pipeline should ensure an index on
`(item_label, date_from)` for the event table, and `(accession_number, acc_year)` for
the accession table. With those indexes, a single snapshot runs in under one second on
a laptop with SQLite.

Comparison mode runs two snapshots sequentially, not in parallel, to keep memory
pressure low. Total wall time for a comparison is expected to be under five seconds.

No caching layer is planned at this stage. If a user runs the same snapshot date
repeatedly (e.g. in a pipeline), they can redirect JSON output to disk.

### 7. Edge cases

**Accessions with no date info**: `AccYear` is present on essentially all records.
`RecDate` is often null for pre-1990 data. When both are null, the accession is
included in all snapshots (conservative: assume it was always there) and flagged
in the "undatable items" footnote.

**Status gaps**: if an item has no history row covering date X (gap in the log), it
is classified as `unknown` and excluded from alive/dead counts. It is listed in a
per-snapshot "status gaps" appendix in the JSON output.

**Items with only Procedure rows**: propagation-in-progress items that have never
had an `Existing` or `NotExisting` row are excluded from garden counts and counted
only in the Nursery Pipeline section.

**Accession attribute versioning**: taxonomy and IUCN status are not versioned in
the source data. When generating a historical snapshot, the report card uses current
attribute values and includes a header note: "Conservation status and taxonomy
reflect current records, not necessarily values at the snapshot date."

**Future dates**: if `--snapshot-date` is after today, the command exits with an
error. Window end dates in the future are clamped to today with a warning.

---

## CLI interface

```
ben0 report-card [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--snapshot-date DATE` | (none) | Reconstruct collection state at YYYY-MM-DD |
| `--period START:END` | (none) | Window mode: focus metrics on YYYY-MM-DD:YYYY-MM-DD |
| `--compare A B` | (none) | Run two contexts and diff them. Each arg is a date or START:END range |
| `--format` | markdown | Output format: markdown, json |
| `--output FILE` | (stdout) | Write to file |
| `--garden` | (active) | Garden slug (passed through from base command) |

With no temporal flags, the command runs against current state as before.

`--compare` takes exactly two positional arguments after the flag. Each can be either
a bare date (`2015-12-31`) for snapshot mode or a range (`2010:2015`) for window mode.
Mixing modes (one date, one range) is allowed: the date argument is treated as a
single-day window for delta purposes.

Examples:

```bash
ben0 report-card
ben0 report-card --snapshot-date 2020-12-31
ben0 report-card --period 2020:2024
ben0 report-card --compare 2015-12-31 2025-12-31
ben0 report-card --compare 2010:2015 2020:2025
ben0 report-card --snapshot-date 2015-01-01 --format json --output card-2015.json
```

---

## Module structure

The temporal layer lives inside `src/ben0/report_card/` alongside existing report card
modules. No new top-level package is created.

```
src/ben0/report_card/
    __init__.py
    constants.py          # traffic-light thresholds, terminal status list, trend thresholds
    snapshot.py           # CollectionSnapshot: date-filtered session wrapper
    sections/
        taxonomic.py
        conservation.py
        provenance.py
        genetic.py
        dynamics.py
        climate.py
        nursery.py
        integrity.py
    formatters.py         # markdown + json serialization, comparison table renderer
    cli.py                # click command wiring
```

`snapshot.py` is the central addition. All section modules receive a
`CollectionSnapshot` (or a pair of them in comparison mode) instead of a raw session.

```python
@dataclass
class CollectionSnapshot:
    session: Session
    as_of: date | None          # None = current (no filter applied)
    period_start: date | None   # set in window mode
    period_end: date | None     # set in window mode

    def alive_items(self) -> Query:
        """Items with Existing status at as_of date."""

    def acquired_accessions(self) -> Query:
        """Accessions with RecDate in [period_start, period_end)."""

    def lost_items(self) -> Query:
        """Items with terminal NotExisting event in [period_start, period_end)."""

    def propagation_events(self, outcome: str) -> Query:
        """Prop: Success or Prop: Failure events in window."""
```

Section modules import `CollectionSnapshot` and call its methods. They do not write
raw date filter SQL. This keeps temporal logic centralized.

---

## Integration with existing modules

The `visit-gaps` analyzer already has a classification of terminal statuses and
visit event types. `report_card/constants.py` should import `TERMINAL_STATUSES`
from `visit_gaps/constants.py` rather than redeclare them. Do not duplicate.

The `constants.py` additions for report card are:

```python
# Trend threshold: fraction of section max_score below which delta is "stable"
TREND_STABLE_FRACTION = 0.05

# Section-specific max scores (for trend normalization)
SECTION_MAX_SCORES = {
    "taxonomic": 25,
    "conservation": 20,
    "provenance": 15,
    "genetic": 15,
    "dynamics": 10,
    "climate": 5,
    "nursery": 5,
    "integrity": 5,
}
```

---

## Implementation order

1. `snapshot.py`: `CollectionSnapshot` with `alive_items`, `acquired_accessions`,
   `lost_items`, `propagation_events`. Write tests against a small fixture DB.
2. Refactor existing section modules to accept `CollectionSnapshot` instead of a
   raw session (no behavioral change yet, just thread the object through).
3. Add snapshot filter to `alive_items` and verify Taxonomic Diversity and
   Genetic Representation sections produce correct counts for a known historical date.
4. Implement window-mode queries (`acquired_accessions`, `lost_items`) and wire into
   Collection Dynamics and Nursery Pipeline sections.
5. Implement comparison mode in `formatters.py`: side-by-side table, trend arrows.
6. Add `--snapshot-date`, `--period`, `--compare` flags to `cli.py`.
7. Integration test: run `--compare 2010:2015 2020:2025` against the UBCBG garden
   and verify JSON output is structurally valid.
8. Update `garden_bible.md` with a note on the temporal caveat for taxonomy/IUCN.
