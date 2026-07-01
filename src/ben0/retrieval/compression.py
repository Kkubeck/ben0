"""RAPTOR-style hierarchical compression for ben0 retrieval."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from ben0.db.models import CompressedSummary, SourceChunk, Document

logger = logging.getLogger(__name__)

TOPIC_AREAS = ("taxonomy", "propagation", "provenance", "conservation", "operations", "general")

# Keyword sets for topic classification
TOPIC_KEYWORDS = {
    "taxonomy": {"species", "genus", "family", "taxon", "botanical", "plant", "cultivar", "variety", "subspecies", "hybrid", "nomenclature", "synonym"},
    "propagation": {"seed", "cutting", "sown", "germinated", "propagat", "nursery", "rooted", "grafted", "division", "spore", "potted", "pricked"},
    "provenance": {"collected", "wild", "origin", "locality", "expedition", "collector", "habitat", "elevation", "coordinate", "source", "donor", "exchange"},
    "conservation": {"endangered", "threatened", "iucn", "cosewic", "conservation", "rare", "vulnerable", "critical", "extinct", "protected", "cites"},
    "operations": {"planted", "relocated", "removed", "dead", "transferred", "location", "bed", "garden", "glasshouse", "assessed", "labeled", "inventory"},
}


@dataclass
class ChunkCluster:
    """A group of related source chunks."""
    cluster_id: str
    topic_area: str
    chunk_ids: list[str] = field(default_factory=list)
    chunk_texts: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    date_hints: list[str] = field(default_factory=list)


@dataclass
class CompressionReport:
    """Summary of a compression run."""
    level1_created: int = 0
    level2_created: int = 0
    stale_regenerated: int = 0
    total_chunks_processed: int = 0
    errors: list[str] = field(default_factory=list)


def classify_topic(text: str) -> str:
    """Classify a chunk's topic area by keyword overlap."""
    text_lower = text.lower()
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        scores[topic] = score
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def cluster_chunks(session: Session, strategy: str = "document") -> list[ChunkCluster]:
    """Group source chunks into clusters for summarization.

    strategy="document": group by parent document (default)
    strategy="topic": group by topic classification
    """
    chunks = session.query(SourceChunk).all()

    if strategy == "document":
        groups: dict[str, list[SourceChunk]] = defaultdict(list)
        for chunk in chunks:
            groups[chunk.document_id].append(chunk)

        clusters = []
        for doc_id, doc_chunks in groups.items():
            combined_text = " ".join(c.chunk_text for c in doc_chunks)
            topic = classify_topic(combined_text)
            cluster = ChunkCluster(
                cluster_id=str(uuid.uuid4()),
                topic_area=topic,
                chunk_ids=[c.id for c in doc_chunks],
                chunk_texts=[c.chunk_text for c in doc_chunks],
                document_ids=[doc_id],
            )
            clusters.append(cluster)
        return clusters

    elif strategy == "topic":
        groups: dict[str, list[SourceChunk]] = defaultdict(list)
        for chunk in chunks:
            topic = classify_topic(chunk.chunk_text)
            groups[topic].append(chunk)

        clusters = []
        for topic, topic_chunks in groups.items():
            # Split large topic groups into sub-clusters of ~20 chunks
            for i in range(0, len(topic_chunks), 20):
                batch = topic_chunks[i:i+20]
                cluster = ChunkCluster(
                    cluster_id=str(uuid.uuid4()),
                    topic_area=topic,
                    chunk_ids=[c.id for c in batch],
                    chunk_texts=[c.chunk_text for c in batch],
                    document_ids=list({c.document_id for c in batch}),
                )
                clusters.append(cluster)
        return clusters

    else:
        raise ValueError(f"Unknown clustering strategy: {strategy}")


def _build_summarize_prompt(cluster: ChunkCluster) -> str:
    """Build the LLM prompt for summarizing a chunk cluster."""
    combined = "\n---\n".join(cluster.chunk_texts[:30])  # cap input size
    return (
        "Summarize the following botanical garden records into a concise 2-3 sentence summary. "
        "Include: what entities are covered, key facts (counts, dates, status), and notable patterns. "
        "Be specific and factual.\n\n"
        f"Topic area: {cluster.topic_area}\n"
        f"Number of records: {len(cluster.chunk_texts)}\n\n"
        f"Records:\n{combined}"
    )


def summarize_cluster(adapter, cluster: ChunkCluster) -> CompressedSummary:
    """Generate a Level 1 compressed summary for a chunk cluster."""
    prompt = _build_summarize_prompt(cluster)
    response = adapter.generate(prompt)
    summary_text = response if isinstance(response, str) else response.get("text", str(response))

    return CompressedSummary(
        compression_level=1,
        topic_area=cluster.topic_area,
        summary_text=summary_text.strip(),
        entity_count=len(cluster.chunk_ids),
        source_chunk_ids=json.dumps(cluster.chunk_ids),
        source_document_ids=json.dumps(cluster.document_ids),
        generated_by=getattr(adapter, "model_name", "unknown"),
        is_stale=False,
    )


def _build_topic_prompt(topic: str, level1_summaries: list[CompressedSummary]) -> str:
    """Build prompt for Level 2 topic summary."""
    summaries_text = "\n---\n".join(s.summary_text for s in level1_summaries[:50])
    return (
        f"You are summarizing all '{topic}' information for a botanical garden collection. "
        "Create a comprehensive 3-5 sentence overview that captures the major themes, "
        "quantities, time periods, and notable patterns across all the cluster summaries below. "
        "Be specific and include numbers where available.\n\n"
        f"Cluster summaries ({len(level1_summaries)} clusters):\n{summaries_text}"
    )


def build_topic_summaries(
    adapter, session: Session, level1_summaries: list[CompressedSummary] | None = None
) -> list[CompressedSummary]:
    """Generate Level 2 topic summaries from Level 1 cluster summaries."""
    if level1_summaries is None:
        level1_summaries = (
            session.query(CompressedSummary)
            .filter(CompressedSummary.compression_level == 1, CompressedSummary.is_stale == False)
            .all()
        )

    by_topic: dict[str, list[CompressedSummary]] = defaultdict(list)
    for s in level1_summaries:
        by_topic[s.topic_area or "general"].append(s)

    topic_summaries = []
    for topic, cluster_summaries in by_topic.items():
        if len(cluster_summaries) < 1:
            continue
        prompt = _build_topic_prompt(topic, cluster_summaries)
        response = adapter.generate(prompt)
        summary_text = response if isinstance(response, str) else response.get("text", str(response))

        all_chunk_ids = []
        all_doc_ids = []
        for s in cluster_summaries:
            all_chunk_ids.extend(json.loads(s.source_chunk_ids))
            if s.source_document_ids:
                all_doc_ids.extend(json.loads(s.source_document_ids))

        topic_summary = CompressedSummary(
            compression_level=2,
            topic_area=topic,
            summary_text=summary_text.strip(),
            entity_count=len(all_chunk_ids),
            source_chunk_ids=json.dumps(all_chunk_ids),
            source_document_ids=json.dumps(list(set(all_doc_ids))),
            generated_by=getattr(adapter, "model_name", "unknown"),
            is_stale=False,
        )
        topic_summaries.append(topic_summary)

    return topic_summaries


def mark_stale(session: Session, changed_chunk_ids: list[str]) -> int:
    """Mark summaries as stale when their source chunks have changed."""
    if not changed_chunk_ids:
        return 0

    changed_set = set(changed_chunk_ids)
    summaries = session.query(CompressedSummary).filter(CompressedSummary.is_stale == False).all()
    stale_count = 0

    for summary in summaries:
        chunk_ids = set(json.loads(summary.source_chunk_ids))
        if chunk_ids & changed_set:
            summary.is_stale = True
            stale_count += 1

    if stale_count:
        session.commit()

    return stale_count


def compress_all(
    session: Session,
    adapter,
    *,
    level: int | None = None,
    force: bool = False,
) -> CompressionReport:
    """Run the full compression pipeline."""
    report = CompressionReport()

    if force:
        # Delete existing summaries for levels we're rebuilding
        query = session.query(CompressedSummary)
        if level:
            query = query.filter(CompressedSummary.compression_level == level)
        query.delete()
        session.commit()

    # Level 1: cluster summaries
    if level is None or level == 1:
        # Get stale or missing level 1 summaries
        if not force:
            stale = (
                session.query(CompressedSummary)
                .filter(CompressedSummary.compression_level == 1, CompressedSummary.is_stale == True)
                .all()
            )
            for s in stale:
                session.delete(s)
            session.commit()
            report.stale_regenerated += len(stale)

        clusters = cluster_chunks(session, strategy="document")
        report.total_chunks_processed = sum(len(c.chunk_ids) for c in clusters)

        level1_summaries = []
        for cluster in clusters:
            try:
                summary = summarize_cluster(adapter, cluster)
                session.add(summary)
                level1_summaries.append(summary)
                report.level1_created += 1
            except Exception as e:
                report.errors.append(f"Level 1 cluster {cluster.cluster_id}: {e}")
                logger.error("Failed to summarize cluster %s: %s", cluster.cluster_id, e)

        session.commit()
    else:
        level1_summaries = None

    # Level 2: topic summaries
    if level is None or level == 2:
        if not force:
            stale_l2 = (
                session.query(CompressedSummary)
                .filter(CompressedSummary.compression_level == 2, CompressedSummary.is_stale == True)
                .all()
            )
            for s in stale_l2:
                session.delete(s)
            session.commit()

        if force:
            session.query(CompressedSummary).filter(
                CompressedSummary.compression_level == 2
            ).delete()
            session.commit()

        topic_summaries = build_topic_summaries(adapter, session, level1_summaries)
        for ts in topic_summaries:
            session.add(ts)
            report.level2_created += 1

        session.commit()

    return report
