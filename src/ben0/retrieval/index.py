"""SQLite FTS5 retrieval index for BEN-0."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ben0 import config
from ben0.compilation.codex import CodexEntry
from ben0.db.models import Accession, Document, Event, Item, Source
from .chunking import chunk_text

FTS_TABLE = "retrieval_fts"


@dataclass(slots=True)
class IndexEntry:
    source_type: str
    source_record_id: str
    chunk_id: str
    document_name: str
    text: str
    accession_id: str | None = None
    item_id: str | None = None
    taxon_id: str | None = None
    document_type: str | None = None
    reliability_tier: str | None = None
    source_file_path: str | None = None
    date: str | None = None
    lane: str | None = None


def build_index(session: Session, *, reset: bool = True) -> int:
    """Rebuild the SQLite FTS5 retrieval index and return row count."""
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("The prototype retrieval index currently requires SQLite/FTS5.")

    with bind.begin() as conn:
        if reset:
            conn.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
        conn.execute(
            text(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
                    text,
                    source_type UNINDEXED,
                    source_record_id UNINDEXED,
                    chunk_id UNINDEXED,
                    document_name UNINDEXED,
                    accession_id UNINDEXED,
                    item_id UNINDEXED,
                    taxon_id UNINDEXED,
                    document_type UNINDEXED,
                    reliability_tier UNINDEXED,
                    source_file_path UNINDEXED,
                    date UNINDEXED,
                    lane UNINDEXED,
                    tokenize='porter unicode61'
                )
                """
            )
        )
        conn.execute(text(f"DELETE FROM {FTS_TABLE}"))

        rows = [asdict(entry) for entry in _iter_entries(session)]
        if rows:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {FTS_TABLE}
                    (
                        text,
                        source_type,
                        source_record_id,
                        chunk_id,
                        document_name,
                        accession_id,
                        item_id,
                        taxon_id,
                        document_type,
                        reliability_tier,
                        source_file_path,
                        date,
                        lane
                    )
                    VALUES
                    (
                        :text,
                        :source_type,
                        :source_record_id,
                        :chunk_id,
                        :document_name,
                        :accession_id,
                        :item_id,
                        :taxon_id,
                        :document_type,
                        :reliability_tier,
                        :source_file_path,
                        :date,
                        :lane
                    )
                    """
                ),
                rows,
            )
    return len(rows)


def _format_date(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value or None


def _reliability_tier(source_type: str) -> str:
    if source_type in {"accession_note", "item_note"}:
        return "official"
    if source_type == "event_note":
        return "professional"
    if source_type in {"document", "document_chunk", "source_note"}:
        return "informal"
    raise ValueError(f"Unsupported source_type for reliability mapping: {source_type}")


def _iter_entries(session: Session) -> Iterator[IndexEntry]:
    documents = session.scalars(
        select(Document).options(selectinload(Document.chunks)).order_by(Document.filename)
    ).all()
    for document in documents:
        document_type = document.document_type or "document"
        source_file_path = document.source_file
        entry_date = _format_date(document.import_timestamp)
        if document.chunks:
            for chunk in sorted(document.chunks, key=lambda value: value.chunk_index):
                yield IndexEntry(
                    source_type="document_chunk",
                    source_record_id=document.id,
                    chunk_id=f"doc:{document.id}:{chunk.chunk_index}",
                    document_name=document.filename,
                    text=chunk.chunk_text,
                    accession_id=chunk.linked_accession_id,
                    taxon_id=chunk.linked_taxon_id,
                    document_type=document_type,
                    reliability_tier=_reliability_tier("document_chunk"),
                    source_file_path=source_file_path,
                    date=entry_date,
                    lane="A",
                )
        elif document.full_text:
            for chunk in chunk_text(document.full_text):
                yield IndexEntry(
                    source_type="document",
                    source_record_id=document.id,
                    chunk_id=f"doc:{document.id}:{chunk.chunk_index}",
                    document_name=document.filename,
                    text=chunk.text,
                    document_type=document_type,
                    reliability_tier=_reliability_tier("document"),
                    source_file_path=source_file_path,
                    date=entry_date,
                    lane="A",
                )

    accessions = session.scalars(select(Accession).order_by(Accession.accession_number)).all()
    for accession in accessions:
        note_parts = [part for part in (accession.notes, accession.occurrence_remarks) if part]
        if not note_parts:
            continue
        text_blob = "\n".join(note_parts)
        for chunk in chunk_text(text_blob):
            yield IndexEntry(
                source_type="accession_note",
                source_record_id=accession.id,
                chunk_id=f"acc:{accession.id}:{chunk.chunk_index}",
                document_name=f"accession:{accession.accession_number}",
                text=chunk.text,
                accession_id=accession.id,
                taxon_id=accession.taxon_id,
                document_type="accession_record",
                reliability_tier=_reliability_tier("accession_note"),
                source_file_path=accession.source_file,
                date=accession.accession_date or _format_date(accession.import_timestamp),
                lane="A",
            )

    items = session.scalars(select(Item).options(selectinload(Item.accession))).all()
    for item in items:
        note_parts = [part for part in (item.notes, item.occurrence_remarks) if part]
        if not note_parts:
            continue
        accession = item.accession.accession_number if item.accession else item.accession_id
        for chunk in chunk_text("\n".join(note_parts)):
            yield IndexEntry(
                source_type="item_note",
                source_record_id=item.id,
                chunk_id=f"item:{item.id}:{chunk.chunk_index}",
                document_name=f"item:{item.item_label or accession}",
                text=chunk.text,
                accession_id=item.accession_id,
                item_id=item.id,
                taxon_id=item.accession.taxon_id if item.accession else None,
                document_type="item_record",
                reliability_tier=_reliability_tier("item_note"),
                source_file_path=item.source_file,
                date=item.planting_date or _format_date(item.import_timestamp) or item.death_date,
                lane="A",
            )

    events = session.scalars(select(Event).options(selectinload(Event.item), selectinload(Event.accession))).all()
    for event in events:
        if not event.notes:
            continue
        accession_id = event.accession_id or (event.item.accession_id if event.item else None)
        taxon_id = None
        if event.accession:
            taxon_id = event.accession.taxon_id
        elif event.item and event.item.accession:
            taxon_id = event.item.accession.taxon_id
        for chunk in chunk_text(event.notes):
            yield IndexEntry(
                source_type="event_note",
                source_record_id=event.id,
                chunk_id=f"event:{event.id}:{chunk.chunk_index}",
                document_name=f"event:{event.event_type or 'note'}",
                text=chunk.text,
                accession_id=accession_id,
                item_id=event.item_id,
                taxon_id=taxon_id,
                document_type="event_record",
                reliability_tier=_reliability_tier("event_note"),
                source_file_path=event.source_file,
                date=event.event_date or event.event_date_verbatim,
                lane="A",
            )

    sources = session.scalars(select(Source).order_by(Source.source_name)).all()
    for source in sources:
        if not source.notes:
            continue
        for chunk in chunk_text(source.notes):
            yield IndexEntry(
                source_type="source_note",
                source_record_id=source.id,
                chunk_id=f"source:{source.id}:{chunk.chunk_index}",
                document_name=f"source:{source.source_name or source.id}",
                text=chunk.text,
                document_type="source_record",
                reliability_tier=_reliability_tier("source_note"),
                source_file_path=source.source_file,
                date=None,
                lane="A",
            )

    yield from _iter_codex_entries(config._GARDEN_ROOT / "data" / "codex")


def _iter_codex_entries(codex_dir: Path) -> Iterator[IndexEntry]:
    if not codex_dir.exists() or not codex_dir.is_dir():
        return

    for file_path in sorted(codex_dir.glob("*.md")):
        try:
            entry = CodexEntry.from_markdown(file_path)
        except Exception:
            continue

        body_text = "\n\n".join(
            [
                f"Definition: {entry.definition}",
                f"Current Working Rule: {entry.working_rule}",
                f"Known Exceptions: {entry.known_exceptions}",
                f"Do Not Infer: {entry.do_not_infer}",
            ]
        )

        for chunk in chunk_text(body_text):
            yield IndexEntry(
                source_type="codex_entry",
                source_record_id=entry.topic_id,
                chunk_id=f"codex:{entry.topic_id}:{chunk.chunk_index}",
                document_name=f"codex:{entry.topic_id}",
                text=chunk.text,
                document_type="codex",
                reliability_tier="generated",
                source_file_path=str(file_path),
                date=entry.generated_on,
                lane="B",
            )
