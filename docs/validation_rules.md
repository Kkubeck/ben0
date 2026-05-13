# Validation Rules

BEN-0 currently organizes deterministic validation into fourteen operational checks. Some checks can emit more than one specific issue type in the database, but these are the main stewardship questions they answer.

| Check | Typical severity | What it checks | What it means |
|---|---|---|---|
| Accession number present | critical | Accession records must have a raw accession number | A missing accession number makes the record hard to trust or link |
| Accession number format valid | error | Accession number should match a recognized local pattern | The record may contain a typo, unsupported legacy format, or import problem |
| Duplicate accession number | critical | Multiple accessions normalize to the same accession number | Staff should reconcile whether these are true duplicates or numbering collisions |
| Taxon assignment present | error | Accessions should have a linked taxon or verbatim taxon name | The accession exists, but its biological identity is unresolved |
| Provenance record present | error | Accessions should carry provenance context | Collection history is incomplete or missing |
| Source linkage or provenance specificity | warning | Provenance rows without a linked source, or marked unknown | The collection can only make limited claims about origin |
| Accession has item records | warning | Accessions should usually resolve to one or more items | Material may never have been itemized, or linkage failed |
| Living item has current location | error | Living plants need a current location | Staff cannot reliably find or verify the plant |
| Terminal item not marked current | critical | Dead/removed items should not still be current | The current-state view is misleading |
| Item has event history | warning | Items should have at least one history event | The record lacks audit trail context |
| Current item lacks terminal conflict | error | Current items should not also show dead/removed/transferred events as their latest truth | Historical events and current-state fields disagree |
| Single current location | critical | Items should not appear current in multiple places at once | The location history needs reconciliation |
| Chronology and date plausibility | warning / error | Dates must parse, be plausible, and not precede accessioning improperly | Time-based history is unreliable |
| Sensitive / reconciliation controls | warning / critical | Sensitive records need explicit restrictions, and very similar taxa may need name review | Sharing controls or taxonomic cleanup need curator attention |

## Current rule families in code

The Python implementation groups those checks into these rule families:

- accession number integrity
- required accession fields
- item status consistency
- date integrity
- sensitive data controls
- similar unreconciled taxa
