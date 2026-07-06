# Memory, Dossiers, and Session Continuity

Design spec for ben0's learning and memory system. Covers three linked
capabilities: session continuity (temporal), entity dossiers (knowledge),
and the graph layer (relationships).

**Status:** Design. Nothing below is built yet.
**Date:** 2026-07-05
**Authors:** Kevin Kubeck, Dewey


## Problem

Ben0 currently treats every question as independent. There is no
conversational memory, no accumulated knowledge about specific plants,
and no way to say "tell me more about that." Session turns are stored
in JSON files but never re-injected into the prompt. The system
retrieves facts but does not learn.


## Design Principles

- **Organic over generated.** Dossiers grow through use, not on command.
  Every conversation deposits knowledge. Over time, ben0 develops
  "taste" for each entity: the accumulated side-notes, characteristics,
  and context that a curator carries in their head.
- **Human-readable.** Dossiers are markdown files a curator can read,
  edit, and annotate directly. Not opaque JSON blobs.
- **No extra LLM calls for memory ops.** Entity detection, tag
  assignment, and dossier updates use structured extraction from tool
  results that are already in hand. The LLM answers questions; the
  memory system runs alongside it.
- **Local-first.** All memory lives on disk in the garden directory.
  No cloud dependencies.


## Architecture Overview

```
User question
    |
    v
[1. Entity Detection] --- regex + DB lookup
    |
    v
[2. Context Assembly]
    |-- recent session turns (last N)
    |-- entity dossiers (filtered by tags)
    |-- retrieved evidence (existing RAG)
    |-- matched rules (existing Lane C)
    |
    v
[3. LLM generates answer] --- existing orchestrator loop
    |
    v
[4. Post-Answer Learning]
    |-- save turn to session history (exists)
    |-- extract learnings from tool results (new)
    |-- append to entity dossiers (new)
    |-- update entity graph edges (new)
    |
    v
[5. Display]
    |-- answer text
    |-- context meter (brain fullness gauge)
```


## 1. Session Continuity

### Within a session

Inject the last N user/assistant turn pairs into the prompt so
follow-up questions work ("tell me more", "what about the other ones",
"compare that to last year").

- Default: last 3 turn pairs (tunable via config)
- Injected as a `## Recent conversation` block between the system
  prompt and the current question
- Token budget: cap at ~2,000 tokens. If turns exceed budget, keep
  the most recent ones and summarize older turns into a one-paragraph
  block

### Compaction

When accumulated session context exceeds a threshold (configurable,
default 70% of model context window):

1. Summarize all turns older than the last 3 into a condensed block
2. Replace the raw turns with the summary
3. Continue the session with the summary as "memory"

This mirrors how OpenClaw handles Dewey's context window.

### Context meter

Visual gauge showing how full the context window is:

- **CLI:** `[####------] 38%` printed after each answer
- **Streamlit:** graphical container (brain/jar filling up)
- Calculated from: system prompt + rules + session history + dossier
  context + retrieved chunks + question, as a fraction of the model's
  context window size


## 2. Entity Dossiers

### What they are

A persistent markdown file per entity (taxon, accession, bed, collector,
expedition) that accumulates knowledge through use. The dossier is ben0's
"memory" of that entity.

### Storage

```
data/dossiers/
    taxon/
        acer-macrophyllum.md
        rhododendron-macrophyllum.md
    accession/
        1968-0042.md
    bed/
        d-42.md
    collector/
        john-smith.md
```

One markdown file per entity, keyed by a slugified identifier.

### Dossier structure

```markdown
# Acer macrophyllum

entity_type: taxon
entity_id: acer-macrophyllum
canonical_name: Acer macrophyllum
family: Sapindaceae
first_seen: 2026-07-05
last_updated: 2026-07-10

## Facts (seeded from DB on first encounter)

- Family: Sapindaceae
- 12 accessions in collection
- Oldest accession: 1968-0042 (David C. Lam Asian Garden)
- 3 items currently dead
- Wild-collected: 8 of 12

## Learned (accumulated from conversations)

- [2026-07-05] [status, location] 3 of 12 items dead, all in bed D-42
- [2026-07-05] [provenance] 8 of 12 wild-collected from BC
- [2026-07-05] [curator-note] Kevin concerned about drainage in D-42
- [2026-07-10] [propagation] 2 cuttings taken spring 2024, both failed
- [2026-07-10] [document-ref] Mentioned in "Alpine Garden Plan 2020.pdf"

## Relationships

- bed: D-42, E-15
- collector: J. Smith (expedition BC-2019)
- family-peers: Acer circinatum, Acer glabrum
- conservation: S4 (provincially secure)
```

### Entity detection

Runs on each user question before the LLM sees it. No LLM needed:

- **Accession numbers:** regex pattern `\d{4,5}-\d{1,4}(-\d{1,4})?`
- **Taxon names:** match against the taxon table in the DB (exact and
  fuzzy). Cache the taxon list at session start for speed.
- **Bed codes:** match against known bed code patterns (garden-specific,
  loaded from Lane C rules or a config file)
- **Collector names:** match against source/collector fields in DB

Returns a list of `(entity_type, entity_id, canonical_name)` tuples.

### Dossier seeding

On first encounter with an entity, ben0 creates the dossier file and
populates the "Facts" section from the database:

- Taxon: family, accession count, item count, alive/dead, provenance
  breakdown, oldest accession, conservation status
- Accession: taxon, provenance, collector, accession date, item count,
  current status, bed locations
- Bed: all accessions planted there, area, garden section

This is a one-time DB query, not an LLM call.

### Post-answer learning

After each answer, ben0 extracts learnings from `_last_retrieved_chunks`
and the answer text:

1. Identify which entities were involved (from step 1 detection +
   entities found in retrieved chunks)
2. For each entity, extract relevant facts from the tool results
3. Assign 1-2 tags from the tag set
4. Append as a timestamped entry to the "Learned" section
5. Update the "Relationships" section if new connections appeared

### Dossier injection into prompts

When assembling the prompt for a question:

1. Load dossiers for all detected entities
2. Filter "Learned" entries by tags relevant to the question type
   (e.g., mortality question pulls `status` and `location` tags)
3. Include the "Facts" section in full (it's short)
4. Include filtered "Learned" entries (most recent first, capped by
   token budget)
5. Include "Relationships" section
6. Inject as a `## Entity context` block in the prompt


## 3. Tags

Flat, lightweight tag set for classifying dossier entries. Not a
taxonomy. Each entry gets 1-2 tags.

| Tag | Meaning |
|-----|---------|
| `provenance` | Where the material came from |
| `status` | Alive, dead, condition, vigor |
| `location` | Beds, gardens, moves, transfers |
| `propagation` | Nursery history, germination, cuttings |
| `taxonomy` | Determinations, nomenclature, family |
| `conservation` | IUCN, threat status, rarity, protection |
| `curator-note` | Human-entered observation or annotation |
| `document-ref` | Linked to an ingested document |
| `validation` | Data quality issues, corrections |

Tag assignment is rule-based, not LLM-driven:

- Tool result from `search_records` with life_status fields: `status`
- Tool result with bed/location fields: `location`
- Tool result with provenance/collector fields: `provenance`
- Curator annotation via `ben0 note`: `curator-note`
- etc.


## 4. Entity Graph

### What it is

A lightweight relationship layer connecting entities. Stored as a
JSON adjacency list alongside the dossiers.

```
data/dossiers/graph.json

{
  "acer-macrophyllum": {
    "beds": ["d-42", "e-15"],
    "collectors": ["j-smith"],
    "family": "sapindaceae",
    "expeditions": ["bc-2019"],
    "related_taxa": ["acer-circinatum", "acer-glabrum"]
  },
  "d-42": {
    "taxa": ["acer-macrophyllum", "cornus-nuttallii"],
    "garden_area": "david-c-lam"
  }
}
```

### How edges form

Edges are extracted from tool results during post-answer learning.
When a query reveals that accession 1968-0042 (Acer macrophyllum)
is in bed D-42, that creates edges:

- `acer-macrophyllum` -> `d-42` (bed)
- `d-42` -> `acer-macrophyllum` (taxon)
- `1968-0042` -> `acer-macrophyllum` (taxon)
- `1968-0042` -> `d-42` (bed)

Edges accumulate organically. No bulk graph-building pass needed.

### Graph-aware context

When loading dossiers for a question, ben0 also checks one hop out
in the graph. "Tell me about bed D-42" loads:

1. The bed D-42 dossier
2. Dossiers for taxa planted in D-42 (filtered to top 5 by relevance
   or recency)

This gives ben0 the "everything connects" reasoning that curators
use naturally.

### Streamlit visualization

The dashboard gets a network diagram view: click an entity, see its
connections. Nodes are entities, edges are relationships. Filterable
by entity type and tag.


## 5. Contradiction Detection (future)

When appending a new "Learned" entry, compare against existing entries
for the same entity and tag. If a quantitative fact changed (item
count, status, accession count), flag it:

```markdown
- [2026-08-01] [status] **CHANGED** 2 of 12 items dead (was: 3 of 12
  on 2026-07-05). One item status corrected?
```

Ben0 surfaces these in answers: "Note: the last time I checked this
taxon, there were 3 dead items. Now there are 2. This may reflect a
data correction or a status update."

Not first-build. Requires reliable numeric extraction from tool results.


## 6. Confidence Decay (future)

Dossier entries carry their timestamp. When assembling context, weight
recent entries higher than old ones:

- Last 30 days: full confidence
- 30-90 days: "as of [date]" caveat
- 90+ days: "last verified [date], may be outdated"

Applied during context assembly, not stored as metadata.


## 7. Periodic Consolidation (future)

As dossiers grow, redundant entries accumulate (five queries about the
same taxon each recording "3 dead items"). A consolidation pass merges
redundant entries:

- Rule-based for quantitative facts (keep the most recent)
- LLM-driven for narrative entries (summarize into a paragraph)
- Triggered manually (`ben0 consolidate`) or automatically when a
  dossier exceeds a size threshold


## 8. Curator Annotations

### CLI

```
ben0 note "Acer macrophyllum" "drainage issue in D-42, talk to grounds"
ben0 note --accession 1968-0042 "repotted spring 2026, moved to PH South"
ben0 dossier "Acer macrophyllum"          # view the dossier
ben0 dossier --list                       # list all dossiers
ben0 dossier --search propagation         # find dossiers with tag
```

### Streamlit

- Browse dossiers by entity type
- View timeline of learned entries
- Add notes inline
- Edit/delete entries
- Graph visualization of relationships


## Build Order

1. **Session continuity** -- inject last N turns into prompt. Smallest
   change, biggest UX win. Modify `orchestrator.py` only.
2. **Entity detection** -- regex + DB lookup module. No integration
   yet, just the detector.
3. **Dossier storage** -- create/read/append dossier markdown files.
   Seeding from DB on first encounter.
4. **Post-answer learning** -- wire into orchestrator. After each
   answer, extract and append to dossiers.
5. **Dossier injection** -- load dossiers during context assembly.
   Tag-based filtering.
6. **Context meter** -- token counting and display.
7. **Curator annotations** -- `ben0 note` and `ben0 dossier` CLI
   commands.
8. **Entity graph** -- adjacency list, graph-aware context loading.
9. **Streamlit integration** -- dossier viewer, graph visualization.
10. **Contradiction detection, confidence decay, consolidation** --
    polish features, build when the core is stable.


## Files to create/modify

### New files
- `src/ben0/memory/entity_detect.py` -- entity detection
- `src/ben0/memory/dossier.py` -- dossier CRUD (create, read, append)
- `src/ben0/memory/graph.py` -- entity graph
- `src/ben0/memory/tags.py` -- tag assignment rules
- `src/ben0/memory/context_meter.py` -- token counting and display
- `src/ben0/memory/__init__.py`

### Modified files
- `src/ben0/assistant/orchestrator.py` -- session history injection,
  dossier injection, post-answer learning, context meter display
- `src/ben0/assistant/prompts.py` -- new prompt sections for session
  history and entity context
- `src/ben0/cli.py` -- `ben0 note` and `ben0 dossier` commands
- `src/ben0/dashboard/` -- dossier viewer page, graph visualization
