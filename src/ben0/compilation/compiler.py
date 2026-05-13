"""Codex compilation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

from ben0.compilation.codex import CodexEntry
from ben0.compilation.prompts import DEFAULT_TOPICS, ExtractionTopic
from ben0.retrieval.search import search_index


@dataclass
class CompilationResult:
    compiled: list[str]
    skipped_pinned: list[str]
    skipped_no_evidence: list[str]
    errors: list[tuple[str, str]]


class CodexCompiler:
    def __init__(self, adapter, session_factory, codex_dir: Path, *, max_chunks_per_topic: int = 20):
        self.adapter = adapter
        self.session_factory = session_factory
        self.codex_dir = codex_dir
        self.max_chunks_per_topic = max_chunks_per_topic
        self._last_evidence_rows: list[dict[str, str]] = []

    def compile_all(self, topics: list[ExtractionTopic] | None = None, *, force: bool = False) -> CompilationResult:
        selected_topics = topics or DEFAULT_TOPICS
        result = CompilationResult(compiled=[], skipped_pinned=[], skipped_no_evidence=[], errors=[])

        self.codex_dir.mkdir(parents=True, exist_ok=True)
        for topic in selected_topics:
            path = self.codex_dir / f"{topic.topic_id}.md"
            if path.exists() and CodexEntry.is_pinned(path) and not force:
                result.skipped_pinned.append(topic.topic_id)
                continue
            try:
                entry = self.compile_topic(topic, force=force)
            except Exception as exc:
                result.errors.append((topic.topic_id, str(exc)))
                continue
            if entry is None:
                result.skipped_no_evidence.append(topic.topic_id)
                continue
            result.compiled.append(topic.topic_id)
        return result

    def compile_topic(self, topic: ExtractionTopic, *, force: bool = False) -> CodexEntry | None:
        path = self.codex_dir / f"{topic.topic_id}.md"
        if path.exists() and CodexEntry.is_pinned(path) and not force:
            return None

        evidence = self._gather_evidence(topic)
        chunk_ids = [row["chunk_id"] for row in self._last_evidence_rows]
        if not evidence or not chunk_ids:
            return None

        prompt = topic.extraction_prompt.format(evidence=evidence)
        raw = self.adapter.generate(prompt)
        entry = self._parse_model_output(raw, topic, chunk_ids)
        self.codex_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(entry.to_markdown(), encoding="utf-8")
        return entry

    def _gather_evidence(self, topic: ExtractionTopic) -> str:
        deduped: dict[str, dict[str, str]] = {}
        session = self.session_factory()
        try:
            for query in topic.search_queries:
                results = search_index(session, query, limit=self.max_chunks_per_topic, lane="A")
                for row in results:
                    chunk_id = str(row.get("chunk_id") or "")
                    if not chunk_id or chunk_id in deduped:
                        continue
                    text = str(row.get("text") or row.get("snippet") or "").strip()
                    deduped[chunk_id] = {
                        "chunk_id": chunk_id,
                        "document_name": str(row.get("document_name") or ""),
                        "text": text,
                        "summary": _summarize_text(text),
                    }
                    if len(deduped) >= self.max_chunks_per_topic:
                        break
                if len(deduped) >= self.max_chunks_per_topic:
                    break
        finally:
            session.close()

        self._last_evidence_rows = list(deduped.values())
        if not self._last_evidence_rows:
            return ""

        lines = []
        for idx, row in enumerate(self._last_evidence_rows, start=1):
            document_name = f" {row['document_name']}" if row["document_name"] else ""
            lines.append(f"[{idx}] ({row['chunk_id']}){document_name} {row['text']}")
        return "\n\n".join(lines)

    def _parse_model_output(self, raw: str, topic: ExtractionTopic, chunk_ids: list[str]) -> CodexEntry:
        cleaned = (raw or "").strip()
        sections = _extract_sections(cleaned)
        if not sections:
            sections = {
                "Definition": cleaned or "Insufficient evidence",
                "Current Working Rule": "Insufficient evidence",
                "Known Exceptions": "Insufficient evidence",
                "Do Not Infer": "Insufficient evidence",
            }

        evidence_map = {row["chunk_id"]: row["summary"] for row in self._last_evidence_rows}
        source_evidence = [{"chunk_id": chunk_id, "summary": evidence_map.get(chunk_id, "")} for chunk_id in chunk_ids]

        return CodexEntry(
            topic_id=topic.topic_id,
            title=topic.title,
            domain=topic.domain,
            definition=sections.get("Definition", "Insufficient evidence"),
            working_rule=sections.get("Current Working Rule", "Insufficient evidence"),
            known_exceptions=sections.get("Known Exceptions", "Insufficient evidence"),
            do_not_infer=sections.get("Do Not Infer", "Insufficient evidence"),
            source_evidence=source_evidence,
            generated_by=getattr(self.adapter, "model_name", None) or self.adapter.__class__.__name__,
            generated_on=date.today().isoformat(),
            review_status="unreviewed",
            pinned=False,
        )


def _summarize_text(text: str, *, limit: int = 220) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _extract_sections(raw: str) -> dict[str, str]:
    section_names = ["Definition", "Current Working Rule", "Known Exceptions", "Do Not Infer"]
    pattern = re.compile(
        r"(?ims)^\s*(?:##\s*)?(Definition|Current Working Rule|Known Exceptions|Do Not Infer)\s*:?[ \t]*$"
    )
    matches = list(pattern.finditer(raw))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        section_name = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        sections[section_name] = raw[start:end].strip() or "Insufficient evidence"

    for name in section_names:
        sections.setdefault(name, "Insufficient evidence")
    return sections
