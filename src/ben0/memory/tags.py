"""Tag vocabulary and rule-based tag assignment for dossier entries."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

# A Tag is a str drawn from TAG_SET.
# Interpretation: a lightweight classifier for a dossier entry indicating
# what aspect of the entity the entry describes.
# Examples: "provenance", "status", "location"

TAG_SET: frozenset[str] = frozenset(
    {
        "provenance",
        "status",
        "location",
        "propagation",
        "taxonomy",
        "conservation",
        "curator-note",
        "document-ref",
        "validation",
    }
)

# A ToolFields is a dict[str, object].
# Interpretation: key-value pairs extracted from a tool result or DB query.
# Examples:
#   {"life_status": "dead", "bed_code": "D-42"}
#   {"collector": "J. Smith", "origin_code": "W"}

# A TagList is a list[str] where each element is in TAG_SET.
# Interpretation: the 1-2 most relevant tags for a dossier entry.
# Examples: ["status", "location"], ["provenance"]

# ---------------------------------------------------------------------------
# Field-to-tag mapping rules
# ---------------------------------------------------------------------------

_FIELD_TAG_RULES: list[tuple[list[str], str]] = [
    (["life_status", "is_current", "condition", "vigor", "death_date"], "status"),
    (["bed_code", "location_code", "current_location", "garden_section"], "location"),
    (
        [
            "collector",
            "origin_code",
            "establishment_means",
            "collection_country",
            "collection_locality",
            "provenance",
        ],
        "provenance",
    ),
    (["propagation", "cutting", "germination", "sowing", "nursery"], "propagation"),
    (
        [
            "scientific_name",
            "family",
            "determination",
            "taxon_rank",
            "synonym",
            "nomenclature",
        ],
        "taxonomy",
    ),
    (["iucn_status", "cosewic_status", "conservation", "threat_status"], "conservation"),
    (["document", "filename", "document_type", "linked_document"], "document-ref"),
    (["validation_issue", "data_quality", "correction"], "validation"),
]


# ---------------------------------------------------------------------------
# assign_tags
# ---------------------------------------------------------------------------


def assign_tags(fields: dict[str, object]) -> list[str]:
    """Return 1-2 tags for a dossier entry based on which tool-result fields are present.

    >>> assign_tags({"life_status": "dead", "bed_code": "D-42"})
    ['status', 'location']
    >>> assign_tags({"collector": "J. Smith"})
    ['provenance']
    >>> assign_tags({})
    []
    """
    field_keys = {k.lower() for k in fields}
    matched: list[str] = []
    for trigger_fields, tag in _FIELD_TAG_RULES:
        if field_keys & {f.lower() for f in trigger_fields}:
            if tag not in matched:
                matched.append(tag)
        if len(matched) >= 2:
            break
    return matched
