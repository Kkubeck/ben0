# Sensitive Data Policy

## Sensitivity levels

BEN-0 uses these working levels:

- **public** — safe for ordinary sharing
- **internal** — fine within the institution, not assumed public
- **restricted** — should not be shared without explicit approval
- **culturally_sensitive** — requires special care, context, and often community-led restrictions
- **unknown** — insufficient context; default to caution

## Sharing rules

- Public exports should exclude restricted, culturally sensitive, and review-required records by default
- Precise rare-plant localities should be generalized or withheld
- Permit references, donor details, and unpublished research context should be treated as non-public unless explicitly cleared
- When sensitivity is uncertain, BEN-0 should favor review over disclosure

## Export filtering

The export path is designed to skip records whose flags indicate `not_allowed` or `review_required`, unless the operator explicitly includes sensitive data.

## Curator responsibility

BEN-0 can preserve and surface restriction metadata, but final sharing decisions remain human decisions.
