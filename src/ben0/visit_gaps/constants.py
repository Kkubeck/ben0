"""
Constants for the visit-gaps analysis: event classification, terminal
statuses, and garden area mapping.

All classification logic lives here, not hardcoded inline in analyzer.py.
When Kevin adds more bed mappings or event types, only this file changes.
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
# VISIT_EVENTS is a set of BEN-0 Event.event_type strings.
#
# Interpretation: an event whose event_type is a member of this set means a
# curator was physically in front of the plant when the event was recorded
# (an "eyes on plant" moment). These values are the BEN-0 side of the
# IrisBG ItemStatus -> BEN-0 event_type mapping table in
# docs/visit-gaps-design.md. Multiple IrisBG labels collapse onto the same
# BEN-0 event_type (e.g. "Present" and "Observed" both become "observed"),
# so this set only needs the distinct BEN-0 values.
#
# Example: VISIT_EVENTS contains "observed", so classify_event("observed")
# returns "visit".
# -----------------------------------------------------------------------------
VISIT_EVENTS: frozenset[str] = frozenset(
    {
        "observed",
        "planted",
        "not_found",
        "dead",
        "relocated",
        "removed",
        "transferred",
        "divided",
        "assessed",
    }
)

# -----------------------------------------------------------------------------
# NON_VISIT_EVENTS is a set of BEN-0 Event.event_type strings.
#
# Interpretation: an event whose event_type is a member of this set is an
# administrative or process record (propagation steps, data correction,
# bed reassignment, herbarium handling, etc). No one necessarily stood in
# front of the live plant in the garden bed for this event, so it does not
# count toward visit recency.
#
# The design spec's source data describes these as IrisBG ItemStatus labels
# like "Prop:*", "Data Corr*", "Bed Designation Change", "Seed store",
# "Deposited (Herb.)", "In Process (Herb.)", "Distributed*", "Reassigned",
# "Pending", "Unknown-Deprecated", "Removed (Herb.)". BEN-0's Event model
# does not define a single dedicated event_type for each of these; the
# closest matches among BEN-0's known event_type vocabulary
# (received / sown / germinated / pricked_out / potted / labeled / treated /
# noted / audited / other) are nursery/propagation/process steps, so those
# are treated as non-visit here.
#
# Example: NON_VISIT_EVENTS contains "sown", so classify_event("sown")
# returns "non_visit".
# -----------------------------------------------------------------------------
NON_VISIT_EVENTS: frozenset[str] = frozenset(
    {
        "received",
        "sown",
        "germinated",
        "pricked_out",
        "potted",
        "labeled",
        "treated",
        "noted",
        "audited",
        "other",
    }
)

# -----------------------------------------------------------------------------
# TERMINAL_STATUSES is a set of BEN-0 Event.event_type strings.
#
# Interpretation: if the LAST visit event recorded for an item has an
# event_type in this set, the item is no longer alive in the collection
# (it died, was not found, was removed, or was transferred out). This is
# used instead of Item.life_status because the design explicitly calls for
# terminal detection from the event history, since life_status may not be
# kept in sync.
#
# Example: TERMINAL_STATUSES contains "dead", so is_terminal("dead")
# returns True; is_terminal("observed") returns False.
# -----------------------------------------------------------------------------
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "dead",
        "not_found",
        "removed",
        "transferred",
    }
)

# -----------------------------------------------------------------------------
# AREA_RULES is a list of (prefix_list, area_name, action) tuples.
#
# Interpretation: to classify a Location.location_code into a garden area,
# walk this list in order and return the first rule whose prefix_list
# contains a prefix that the location_code starts with (case-insensitive).
# `action` is either "include" (count toward visit-gap reporting) or
# "exclude" (nursery/seed-store/herbarium areas are working/process areas,
# not display beds, and are excluded from the public-facing gap analysis
# by default). If no rule matches, the code falls into the "Other" bucket
# (see classify_area's docstring for how that bucket is named) with
# action "include", so unmapped codes still surface in reports rather than
# silently vanishing.
#
# Example: AREA_RULES contains (["1A", "L"], "Alpine", "include"), so a
# location_code of "1A2" maps to ("Alpine", "include").
# -----------------------------------------------------------------------------
AREA_RULES: list[tuple[list[str], str, str]] = [
    (["8"], "Nursery", "exclude"),
    (["5"], "Nitobe", "exclude"),
    (["H", "SEED", "SE"], "Herbarium/Seed Store", "exclude"),
    (["1A", "L"], "Alpine", "include"),
    (["3A", "3X", "3"], "Asian", "include"),
    (["1B"], "BC Rainforest", "include"),
    (["1G"], "Garry Oak Meadow", "include"),
    (["1J"], "Pacific Slope Woodland", "include"),
    (["1K"], "Westmost Beds", "include"),
    (["4C"], "Carolinian", "include"),
    (["1P"], "Winter", "include"),
    (["1C"], "Contemporary", "include"),
    (["1F"], "Physic", "include"),
    (["1M"], "Pavilion", "include"),
    (["F"], "Food", "include"),
]
