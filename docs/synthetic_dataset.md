# Synthetic Dataset

BEN-0 includes a built-in fictional dataset generator for demos, testing, and development.

## Fictional institution

The synthetic data represents the **Cascadia Demonstration Botanical Garden (CDBG)**, a made-up garden with a mixed conservation, horticulture, and interpretation mission.

## What gets generated

- taxa
- locations / bed codes
- sources and institutions
- accessions with mixed numbering styles
- items with life-status variety
- events with realistic date ranges and some deliberate anomalies
- conservation status records
- OCR-style accession cards
- policy / reference documents

## Why it exists

The generator gives developers and curators a safe dataset for:

- testing ingest and validation
- exercising retrieval and reports
- demonstrating the assistant without exposing real collection data
- reproducing bugs consistently

## Deliberate data problems

The generator intentionally creates imperfect data, including:

- duplicate accession numbers
- missing or unknown provenance
- living items without locations
- dead items still appearing current
- ambiguous historical status notes
- events dated before accession dates
- legacy accession numbering variants
- mild OCR noise in accession-card text

Those defects are not accidents; they are there so BEN-0 has something meaningful to detect.
