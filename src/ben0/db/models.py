"""
SQLAlchemy ORM models for BEN-0.

All tables use string PKs (UUIDs) for portability. The schema is designed
to be SQLite-native now and PostgreSQL-ready later.

Standard-alignment notes (Darwin Core / ABCD / LivingCollectionStandard):
  - Accession → collectionCode + catalogNumber + occurrenceID
  - Taxon      → scientificName + taxonRank + nameAccordingTo
  - Item       → materialEntityID + lifeStage + establishmentMeans
  - Event      → eventType + eventDate + locationID
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Taxon
# ---------------------------------------------------------------------------

class Taxon(Base):
    """Taxonomic name record. One row per distinct scientific name used."""

    __tablename__ = "taxon"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Core name fields
    scientific_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    genus: Mapped[str | None] = mapped_column(String(100))
    species: Mapped[str | None] = mapped_column(String(100))
    infraspecific_rank: Mapped[str | None] = mapped_column(String(50))
    infraspecific_epithet: Mapped[str | None] = mapped_column(String(100))
    cultivar_name: Mapped[str | None] = mapped_column(String(100))
    family: Mapped[str | None] = mapped_column(String(100))
    taxon_rank: Mapped[str | None] = mapped_column(String(50))

    # Synonym / nomenclatural handling
    is_synonym: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_taxon_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("taxon.id"), nullable=True
    )
    name_according_to: Mapped[str | None] = mapped_column(String(200))

    # Conservation / sensitivity
    iucn_status: Mapped[str | None] = mapped_column(String(20))
    cosewic_status: Mapped[str | None] = mapped_column(String(20))
    native_range: Mapped[str | None] = mapped_column(String(300))

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    accessions: Mapped[list[Accession]] = relationship("Accession", back_populates="taxon")
    conservation_statuses: Mapped[list[ConservationStatus]] = relationship(
        "ConservationStatus", back_populates="taxon"
    )
    synonyms: Mapped[list[Taxon]] = relationship(
        "Taxon", foreign_keys=[accepted_taxon_id], back_populates="accepted_taxon"
    )
    accepted_taxon: Mapped[Taxon | None] = relationship(
        "Taxon", foreign_keys=[accepted_taxon_id], back_populates="synonyms", remote_side=[id]
    )

    def __repr__(self) -> str:
        return f"<Taxon {self.scientific_name!r}>"


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

class Location(Base):
    """A garden bed, section, glasshouse bay, or nursery zone."""

    __tablename__ = "location"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    location_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    location_name: Mapped[str | None] = mapped_column(String(200))
    location_type: Mapped[str | None] = mapped_column(String(50))  # bed / nursery / glasshouse / etc.
    parent_location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("location.id"), nullable=True
    )

    # Legacy / alias codes that map to this location
    aliases: Mapped[str | None] = mapped_column(Text)  # JSON array of strings

    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    decommissioned_date: Mapped[str | None] = mapped_column(String(20))

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    items: Mapped[list[Item]] = relationship("Item", back_populates="current_location")
    events: Mapped[list[Event]] = relationship("Event", back_populates="location")

    def __repr__(self) -> str:
        return f"<Location {self.location_code!r}>"


# ---------------------------------------------------------------------------
# Source (provenance source institution / collector / exchange)
# ---------------------------------------------------------------------------

class Source(Base):
    """An originating institution, collector, exchange programme, or unknown source."""

    __tablename__ = "source"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    source_code: Mapped[str | None] = mapped_column(String(50), index=True)
    source_name: Mapped[str | None] = mapped_column(String(300))
    source_type: Mapped[str | None] = mapped_column(String(50))  # institution / individual / exchange / unknown
    country: Mapped[str | None] = mapped_column(String(100))
    contact: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    provenances: Mapped[list[Provenance]] = relationship("Provenance", back_populates="source")

    def __repr__(self) -> str:
        return f"<Source {self.source_name!r}>"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class Provenance(Base):
    """
    Provenance record linking an accession to its source.
    Captures Darwin Core-aligned origin/establishment fields.
    """

    __tablename__ = "provenance"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    accession_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accession.id"), nullable=False, index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source.id"), nullable=True
    )

    # Origin coding (W=wild, Z=wild-derived, G=garden, U=unknown)
    origin_code: Mapped[str | None] = mapped_column(String(10))
    # establishment_means: wild / wildNative / introduced / cultivated / unknown
    establishment_means: Mapped[str | None] = mapped_column(String(50))

    collection_country: Mapped[str | None] = mapped_column(String(100))
    collection_locality: Mapped[str | None] = mapped_column(String(300))
    collection_date: Mapped[str | None] = mapped_column(String(20))
    collector: Mapped[str | None] = mapped_column(String(200))
    collection_notes: Mapped[str | None] = mapped_column(Text)

    permit_reference: Mapped[str | None] = mapped_column(String(200))
    data_generalizations: Mapped[str | None] = mapped_column(Text)
    information_withheld: Mapped[str | None] = mapped_column(Text)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    accession: Mapped[Accession] = relationship("Accession", back_populates="provenances")
    source: Mapped[Source | None] = relationship("Source", back_populates="provenances")

    def __repr__(self) -> str:
        return f"<Provenance accession={self.accession_id!r} origin={self.origin_code!r}>"


# ---------------------------------------------------------------------------
# Accession
# ---------------------------------------------------------------------------

class Accession(Base):
    """
    A garden accession — the fundamental acquisition unit.
    Maps to Darwin Core collectionCode + catalogNumber.
    """

    __tablename__ = "accession"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Accession number as received (raw / original)
    accession_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    accession_number_normalized: Mapped[str | None] = mapped_column(String(100), index=True)

    taxon_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("taxon.id"), nullable=True
    )

    # Taxon name as recorded at time of accession (may differ from current Taxon.scientific_name)
    taxon_name_verbatim: Mapped[str | None] = mapped_column(String(300))

    accession_date: Mapped[str | None] = mapped_column(String(20))
    accession_year: Mapped[int | None] = mapped_column(Integer)

    # Material type
    material_type: Mapped[str | None] = mapped_column(String(50))  # seed / cutting / plant / division / etc.
    quantity_received: Mapped[int | None] = mapped_column(Integer)

    # Acquisition channel
    acquisition_type: Mapped[str | None] = mapped_column(String(100))  # exchange / donation / purchase / wild / etc.
    donor_reference: Mapped[str | None] = mapped_column(String(200))

    notes: Mapped[str | None] = mapped_column(Text)
    occurrence_remarks: Mapped[str | None] = mapped_column(Text)

    # Sensitive data flag shortcut
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    import_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    taxon: Mapped[Taxon | None] = relationship("Taxon", back_populates="accessions")
    items: Mapped[list[Item]] = relationship("Item", back_populates="accession")
    provenances: Mapped[list[Provenance]] = relationship("Provenance", back_populates="accession")
    events: Mapped[list[Event]] = relationship("Event", back_populates="accession")
    sensitive_flags: Mapped[list[SensitiveDataFlag]] = relationship(
        "SensitiveDataFlag", back_populates="accession"
    )
    validation_issues: Mapped[list[ValidationIssue]] = relationship(
        "ValidationIssue",
        primaryjoin="and_(ValidationIssue.entity_type=='accession', "
                    "foreign(ValidationIssue.entity_id)==Accession.id)",
        overlaps="validation_issues",
    )

    def __repr__(self) -> str:
        return f"<Accession {self.accession_number!r}>"


# ---------------------------------------------------------------------------
# Item (individual plant / material entity)
# ---------------------------------------------------------------------------

class Item(Base):
    """
    An individual plant or material entity derived from an accession.
    Maps to Darwin Core materialEntityID / occurrence.
    """

    __tablename__ = "item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    accession_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accession.id"), nullable=False, index=True
    )

    # Item number within accession (e.g. the ".01" suffix)
    item_number: Mapped[str | None] = mapped_column(String(20))
    # Full qualified label: accession_number + item_number
    item_label: Mapped[str | None] = mapped_column(String(150), index=True)

    current_location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("location.id"), nullable=True
    )

    # Life status
    life_status: Mapped[str | None] = mapped_column(String(30))  # living / dead / removed / transferred / unknown
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    # Phenology / horticultural
    planting_date: Mapped[str | None] = mapped_column(String(20))
    death_date: Mapped[str | None] = mapped_column(String(20))
    life_stage: Mapped[str | None] = mapped_column(String(50))  # seedling / juvenile / mature / etc.

    notes: Mapped[str | None] = mapped_column(Text)
    occurrence_remarks: Mapped[str | None] = mapped_column(Text)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    import_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    accession: Mapped[Accession] = relationship("Accession", back_populates="items")
    current_location: Mapped[Location | None] = relationship("Location", back_populates="items")
    events: Mapped[list[Event]] = relationship("Event", back_populates="item")

    def __repr__(self) -> str:
        return f"<Item {self.item_label or self.id!r}>"


# ---------------------------------------------------------------------------
# Event (history record)
# ---------------------------------------------------------------------------

class Event(Base):
    """
    A history event for an accession or item.
    event_type covers: received / sown / germinated / pricked_out / potted /
    planted / relocated / labeled / assessed / treated / removed / dead /
    transferred / noted / audited / other
    """

    __tablename__ = "event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    accession_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accession.id"), nullable=True, index=True
    )
    item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("item.id"), nullable=True, index=True
    )

    event_type: Mapped[str | None] = mapped_column(String(50), index=True)
    event_date: Mapped[str | None] = mapped_column(String(20), index=True)
    event_date_verbatim: Mapped[str | None] = mapped_column(String(50))

    location_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("location.id"), nullable=True
    )
    location_verbatim: Mapped[str | None] = mapped_column(String(200))

    operator: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    accession: Mapped[Accession | None] = relationship("Accession", back_populates="events")
    item: Mapped[Item | None] = relationship("Item", back_populates="events")
    location: Mapped[Location | None] = relationship("Location", back_populates="events")

    def __repr__(self) -> str:
        return f"<Event {self.event_type!r} {self.event_date!r}>"


# ---------------------------------------------------------------------------
# ConservationStatus
# ---------------------------------------------------------------------------

class ConservationStatus(Base):
    """Conservation assessment for a taxon under a specific authority."""

    __tablename__ = "conservation_status"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    taxon_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("taxon.id"), nullable=False, index=True
    )

    authority: Mapped[str | None] = mapped_column(String(100))  # IUCN / COSEWIC / NatureServe / provincial
    status_code: Mapped[str | None] = mapped_column(String(20))  # LC / NT / VU / EN / CR / DD / NE / etc.
    status_label: Mapped[str | None] = mapped_column(String(100))
    assessment_year: Mapped[int | None] = mapped_column(Integer)
    assessment_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_file: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    taxon: Mapped[Taxon] = relationship("Taxon", back_populates="conservation_statuses")

    def __repr__(self) -> str:
        return f"<ConservationStatus {self.authority!r} {self.status_code!r}>"


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class Document(Base):
    """An ingested text document (OCR accession card, policy doc, data dictionary, etc.)."""

    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    filename: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    document_type: Mapped[str | None] = mapped_column(String(50))  # accession_card / policy / data_dictionary / notes / other
    title: Mapped[str | None] = mapped_column(String(300))
    full_text: Mapped[str | None] = mapped_column(Text)
    character_count: Mapped[int | None] = mapped_column(Integer)

    # Linked accession (if document is an accession card)
    linked_accession_number: Mapped[str | None] = mapped_column(String(100))

    # Sensitivity
    sensitivity_level: Mapped[str] = mapped_column(String(30), default="internal")

    # Audit
    import_timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_file: Mapped[str | None] = mapped_column(String(500))

    # Relationships
    chunks: Mapped[list[SourceChunk]] = relationship("SourceChunk", back_populates="document")

    def __repr__(self) -> str:
        return f"<Document {self.filename!r}>"


# ---------------------------------------------------------------------------
# SourceChunk (retrieval unit)
# ---------------------------------------------------------------------------

class SourceChunk(Base):
    """A chunked passage from a Document, ready for retrieval indexing."""

    __tablename__ = "source_chunk"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document.id"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)

    # Optional links to structured records
    linked_accession_id: Mapped[str | None] = mapped_column(String(36))
    linked_taxon_id: Mapped[str | None] = mapped_column(String(36))

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # Relationships
    document: Mapped[Document] = relationship("Document", back_populates="chunks")

    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    def __repr__(self) -> str:
        return f"<SourceChunk doc={self.document_id!r} idx={self.chunk_index}>"


# ---------------------------------------------------------------------------
# ValidationIssue
# ---------------------------------------------------------------------------

_SEVERITY = ("info", "warning", "error", "critical")
_ISSUE_STATUS = ("open", "acknowledged", "resolved", "wont_fix")


class ValidationIssue(Base):
    """A data quality issue identified by the deterministic validation engine."""

    __tablename__ = "validation_issue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    issue_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(
        Enum(*_SEVERITY, name="severity_enum"), nullable=False, default="warning"
    )

    entity_type: Mapped[str | None] = mapped_column(String(50))  # accession / item / taxon / etc.
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    entity_label: Mapped[str | None] = mapped_column(String(200))

    explanation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True)

    status: Mapped[str] = mapped_column(
        Enum(*_ISSUE_STATUS, name="issue_status_enum"), default="open"
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text)

    # Audit
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"<ValidationIssue {self.issue_type!r} [{self.severity}]>"


# ---------------------------------------------------------------------------
# CorrectionTicket
# ---------------------------------------------------------------------------

_TICKET_STATUS = ("proposed", "accepted", "rejected", "deferred")
_CONFIDENCE = ("low", "medium", "high")


class CorrectionTicket(Base):
    """A proposed correction queued for curator review."""

    __tablename__ = "correction_ticket"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    proposed_correction: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)

    # Affected records (JSON array of entity references)
    affected_entity_type: Mapped[str | None] = mapped_column(String(50))
    affected_entity_id: Mapped[str | None] = mapped_column(String(36))
    affected_records_json: Mapped[str | None] = mapped_column(Text)

    confidence: Mapped[str] = mapped_column(
        Enum(*_CONFIDENCE, name="confidence_enum"), default="medium"
    )
    status: Mapped[str] = mapped_column(
        Enum(*_TICKET_STATUS, name="ticket_status_enum"), default="proposed"
    )

    linked_validation_issue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("validation_issue.id"), nullable=True
    )

    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(100), default="ben0")

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<CorrectionTicket {self.title!r} [{self.status}]>"


# ---------------------------------------------------------------------------
# SensitiveDataFlag
# ---------------------------------------------------------------------------

_SENSITIVITY = ("public", "internal", "restricted", "culturally_sensitive", "unknown")
_SHARING = ("allowed", "not_allowed", "review_required")


class SensitiveDataFlag(Base):
    """Marks a record as having restricted sharing requirements."""

    __tablename__ = "sensitive_data_flag"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Polymorphic entity reference
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    accession_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accession.id"), nullable=True
    )

    sensitivity_level: Mapped[str] = mapped_column(
        Enum(*_SENSITIVITY, name="sensitivity_enum"), nullable=False, default="internal"
    )
    sharing_allowed: Mapped[str] = mapped_column(
        Enum(*_SHARING, name="sharing_enum"), nullable=False, default="review_required"
    )
    reason_for_restriction: Mapped[str | None] = mapped_column(Text)
    reviewer_notes: Mapped[str | None] = mapped_column(Text)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    created_by: Mapped[str] = mapped_column(String(100), default="ben0")

    # Relationships
    accession: Mapped[Accession | None] = relationship(
        "Accession", back_populates="sensitive_flags"
    )

    def __repr__(self) -> str:
        return (
            f"<SensitiveDataFlag {self.entity_type!r}/{self.entity_id!r} "
            f"level={self.sensitivity_level!r}>"
        )
