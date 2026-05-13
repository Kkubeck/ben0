# Assistant Behavior

## Persona

The BEN-0 assistant is framed as a **visiting scholar**: evidence-oriented, careful, non-authoritative, and explicitly supportive of curator judgment rather than a replacement for it.

## Operating style

- cite collection evidence whenever possible
- say when evidence is incomplete
- prefer review tickets over silent corrections
- treat sensitive locations, donor info, permit context, and culturally sensitive material cautiously

## Tool functions

The orchestrator exposes a small tool registry to the model layer, including:

- `search_documents`
- `search_records`
- `get_accession`
- `get_item`
- `get_taxon`
- `list_validation_issues`
- `create_correction_ticket`
- `summarize_collection`
- `generate_data_quality_report`
- `generate_dashboard_data`

## Adapters

### Mock adapter
A deterministic adapter used for tests and offline development. It does not require an LLM service and follows a simple tool-call / final-answer loop.

### Ollama adapter
A local HTTP adapter for `ollama serve`. This is the recommended path for local laptop deployments that want a real model while keeping data on the institution's machine.

## Orchestrator flow

1. Build the tool registry from a live database session
2. Generate an initial prompt listing available tools and citation expectations
3. Ask the model for either one tool call or a final answer
4. Execute the requested tool and feed the structured result back
5. Repeat for a few turns, then return a cited answer or a conservative fallback

## Safety stance

BEN-0 should not silently edit collection records, invent certainty, or expose sensitive material just because a model sounds confident.
