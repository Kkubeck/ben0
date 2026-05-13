# Data Schema

## Core entities

### Taxon
A distinct scientific name used in the collection. Stores genus, species, family, infraspecific fields, cultivar name, conservation status shortcuts, and synonym relationships.

### Accession
The core acquisition record. Stores accession number, normalized accession number, accession date/year, linked taxon, material type, notes, and a sensitivity shortcut.

### Item
An individual plant or material entity derived from an accession. Stores item suffix/label, life status, current location, planting/death dates, and notes.

### Location
A garden bed, nursery zone, glasshouse bay, or other physical collection location. Stores code, name, type, parent relationships, aliases, and status.

### Event
A dated history record attached to an accession and/or item. Used for planting, relocation, removal, death, propagation, and note events.

### Source
A provenance source such as an institution, collector, exchange program, or explicit unknown source placeholder.

### Provenance
Links an accession to its origin/source context. Stores origin code, establishment means, collector, collection place/date, and provenance notes.

### ConservationStatus
Authority-specific conservation assessments linked to a taxon.

## Stewardship and review entities

### ValidationIssue
A persisted result from deterministic validation. Stores issue type, severity, entity linkage, explanation, evidence, and recommended action.

### CorrectionTicket
A proposed change or review item derived from validation findings or assistant actions. Tracks confidence and workflow status.

### SensitiveDataFlag
A structured restriction marker for records that should not be fully shared. Stores sensitivity level, sharing rules, and rationale.

## Retrieval entities

### Document
An ingested text source such as an accession card, policy, or note file.

### SourceChunk
A retrieval-sized text chunk derived from a document and optionally linked to structured records.

## High-level relationships

- One **Taxon** can have many **Accessions**
- One **Accession** can have many **Items**
- One **Accession** can have many **Provenance** rows, **Events**, **ValidationIssues**, and **SensitiveDataFlags**
- One **Item** can have many **Events**
- One **Location** can be the current location for many **Items** and many **Events** can reference it
- One **Source** can be linked to many **Provenance** rows
- One **Document** can have many **SourceChunks**
- One **ValidationIssue** can optionally spawn one or more **CorrectionTickets** over time

## Key operational fields

- `accession.accession_number`
- `accession.accession_number_normalized`
- `item.item_label`
- `item.life_status`
- `location.location_code`
- `provenance.origin_code`
- `validation_issue.issue_type`
- `validation_issue.severity`
- `correction_ticket.status`
- `sensitive_data_flag.sensitivity_level`
- `document.filename`
- `source_chunk.chunk_text`
