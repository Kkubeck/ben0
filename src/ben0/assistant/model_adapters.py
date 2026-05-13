"""Model adapter implementations for the BEN-0 assistant."""

from __future__ import annotations

import json
import os
import re
from urllib import error, request

from ben0 import config


class MockModelAdapter:
    """Deterministic local adapter that works without an LLM."""

    @property
    def model_name(self) -> str:
        return "mock"

    def generate(self, prompt: str, system: str | None = None) -> str:
        del system
        if "TOOL_RESULT:" in prompt:
            return self._final_from_tool_result(prompt)

        question = self._extract_question(prompt).lower()
        if "missing provenance" in question:
            return 'TOOL_CALL search_records {"query": "missing provenance"}'
        if "unknown provenance" in question:
            return 'TOOL_CALL list_validation_issues {"issue_type": "unknown_provenance", "limit": 10}'
        if "report" in question:
            return 'TOOL_CALL generate_data_quality_report {}'
        if any(token in question for token in ("summary", "summarize", "how many accessions", "collection overview")):
            return 'TOOL_CALL summarize_collection {}'
        if any(token in question for token in ("accession", "item", "taxon")):
            return f'TOOL_CALL search_records {json.dumps({"query": self._extract_question(prompt)})}'
        return f'TOOL_CALL search_documents {json.dumps({"query": self._extract_question(prompt), "limit": 5})}'

    def _extract_question(self, prompt: str) -> str:
        match = re.search(r"Question:\s*([^\n]+)", prompt)
        return match.group(1).strip() if match else prompt.strip()

    def _final_from_tool_result(self, prompt: str) -> str:
        question = self._extract_question(prompt)
        match = re.search(r"TOOL_RESULT:\s*(\{.*\})\s*(?:Always cite|Respond with FINAL:|$)", prompt, re.DOTALL)
        payload_text = match.group(1).strip() if match else prompt.split("TOOL_RESULT:", 1)[1].strip()
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return "FINAL: I could not parse the tool output confidently, so I cannot answer yet. [assistant:mock]"

        if isinstance(payload, dict) and payload.get("tool") == "search_records":
            accessions = payload.get("accessions", [])
            if accessions:
                accession_text = ", ".join(
                    f"{row['accession_number']} [{row['citation']}]" for row in accessions[:10]
                )
                return f"FINAL: For '{question}', the records currently show these accessions: {accession_text}."
            return f"FINAL: I did not find any matching accessions for '{question}'. [search_records:none]"

        if isinstance(payload, dict) and payload.get("tool") == "list_validation_issues":
            issues = payload.get("issues", [])
            if issues:
                issue_text = ", ".join(
                    f"{row['entity_label']} [{row['citation']}]" for row in issues[:10] if row.get("entity_label")
                )
                return f"FINAL: The relevant validation issues point to: {issue_text}."
            return f"FINAL: I did not find matching validation issues for '{question}'. [validation_issue:none]"

        if isinstance(payload, dict) and payload.get("tool") == "summarize_collection":
            summary = payload.get("summary", {})
            return (
                "FINAL: The collection currently includes "
                f"{summary.get('total_accessions', 0)} accessions, {summary.get('total_items', 0)} items, "
                f"and {summary.get('total_taxa', 0)} taxa [collection_summary:metrics]."
            )

        if isinstance(payload, dict) and payload.get("tool") == "generate_data_quality_report":
            return "FINAL: I generated a data quality report for review [report:markdown]."

        if isinstance(payload, dict) and payload.get("tool") == "search_documents":
            results = payload.get("results", [])
            if results:
                top = results[0]
                return (
                    f"FINAL: The closest indexed document match is {top['document_name']} "
                    f"[{top['citation']}]."
                )
            return "FINAL: I could not find an indexed document that answers that question. [search_documents:none]"

        return "FINAL: I reviewed the available tool output, but I need a human to interpret it further. [assistant:mock]"


class OllamaAdapter:
    """Adapter for Ollama's HTTP API."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or config.OLLAMA_URL or os.environ.get("BEN0_OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        self.model = model or config.OLLAMA_MODEL or config.MODEL_NAME or os.environ.get("BEN0_OLLAMA_MODEL") or "gemma3:12b"

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        return _post_json(f"{self.base_url}/api/generate", payload).get("response", "").strip()


class OpenAICompatibleAdapter:
    """Adapter for OpenAI-compatible chat completion APIs."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or os.environ.get("BEN0_OPENAI_COMPAT_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("BEN0_OPENAI_COMPAT_API_KEY") or ""
        self.model = model or config.MODEL_NAME or os.environ.get("BEN0_OPENAI_COMPAT_MODEL") or "gpt-4o-mini"
        if not self.base_url:
            raise ValueError("BEN0_OPENAI_COMPAT_BASE_URL is required for the OpenAI-compatible adapter.")

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = _post_json(
            f"{self.base_url}/chat/completions",
            {"model": self.model, "messages": messages, "temperature": 0.1},
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else None,
        )
        choices = response.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = request.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:  # pragma: no cover - depends on external services
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model adapter request failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:  # pragma: no cover - depends on external services
        raise RuntimeError(f"Could not reach model adapter endpoint {url}: {exc.reason}") from exc
