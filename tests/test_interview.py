from __future__ import annotations

from pathlib import Path

from ben0.db.models import Accession, Event, Item, Location, Provenance, Taxon
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.interview.answer_parser import parse_answer_to_rule
from ben0.interview.data_gather import gather_db_context
from ben0.interview.questions import DEFAULT_QUESTIONS, InterviewQuestion
from ben0.interview.session import InterviewSession


class _YamlAdapter:
    def __init__(self, response: str):
        self.response = response

    def generate(self, prompt: str, system: str | None = None) -> str:
        del prompt, system
        return self.response


def _make_session(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'interview.db'}"
    reset_singletons()
    init_db(db_url)
    return get_session(db_url), db_url


def _seed_interview_data(session) -> None:
    taxon_a = Taxon(scientific_name="Abies lasiocarpa", genus="Abies", species="lasiocarpa", family="Pinaceae")
    taxon_b = Taxon(scientific_name="Acer macrophyllum", genus="Acer", species="macrophyllum", family="Sapindaceae")
    location_a = Location(location_code="ALP1", location_name="Alpine Garden")
    location_b = Location(location_code="NUR", location_name="Nursery")
    session.add_all([taxon_a, taxon_b, location_a, location_b])
    session.flush()

    accession_a = Accession(
        accession_number="1952-0001",
        accession_date="1952-01-01",
        accession_year=1952,
        taxon_id=taxon_a.id,
    )
    accession_b = Accession(
        accession_number="2005-0234",
        accession_date="2005-03-12",
        accession_year=2005,
        taxon_id=taxon_a.id,
    )
    accession_c = Accession(
        accession_number="2024-0001",
        accession_date="9999-12-31",
        accession_year=2024,
        taxon_id=taxon_b.id,
    )
    session.add_all([accession_a, accession_b, accession_c])
    session.flush()

    session.add_all(
        [
            Provenance(accession_id=accession_a.id, origin_code="G", establishment_means="cultivated"),
            Provenance(accession_id=accession_b.id, origin_code="W", establishment_means="wild"),
            Provenance(accession_id=accession_c.id, origin_code="Z", establishment_means="wildNative"),
            Item(accession_id=accession_a.id, item_label="1952-0001.01", life_status="living", current_location_id=location_a.id),
            Item(accession_id=accession_b.id, item_label="2005-0234.01", life_status="dead", current_location_id=location_b.id),
            Event(accession_id=accession_a.id, event_type="planted", event_date="1952-01-01"),
            Event(accession_id=accession_a.id, event_type="sown", event_date="1951-11-01"),
            Event(accession_id=accession_b.id, event_type="germinated", event_date="2005-04-01"),
            Event(accession_id=accession_b.id, event_type="removed", event_date="2010-06-15"),
        ]
    )
    session.commit()


def test_gather_db_context_returns_formatted_strings(tmp_path: Path):
    session, _ = _make_session(tmp_path)
    try:
        _seed_interview_data(session)

        statuses = gather_db_context(session, "distinct_statuses")
        provenances = gather_db_context(session, "distinct_provenances")
        propagation = gather_db_context(session, "propagation_event_types")
        dates = gather_db_context(session, "date_range_summary")
        locations = gather_db_context(session, "distinct_locations")
        taxonomy = gather_db_context(session, "taxonomic_summary")

        assert "living (1)" in statuses
        assert "planted (1)" in statuses
        assert "origin_code values" in provenances
        assert "wildNative (1)" in provenances
        assert "germinated (1)" in propagation
        assert "1952-01-01 to 2005-03-12" in dates
        assert "sentinel accession dates: 1" in dates
        assert "1950s (1)" in dates and "2000s (1)" in dates and "2020s (1)" in dates
        assert "ALP1 (Alpine Garden): 1" in locations
        assert "2 families, 2 genera, and 2 species" in taxonomy
        assert "Pinaceae (2)" in taxonomy
    finally:
        session.close()
        reset_singletons()


def test_parse_answer_to_rule_produces_rulefile():
    question = DEFAULT_QUESTIONS[0]
    adapter = _YamlAdapter(
        "status_groups:\n  living: [Living, Active]\n  dead: [Dead, Removed]\n"
    )

    rule = parse_answer_to_rule(
        question,
        "Living and Active mean alive; Dead and Removed mean gone.",
        adapter,
        context="Item life_status values: living (5), dead (2)",
    )

    assert rule.id == "interview_status_groups"
    assert rule.name == question.title
    assert rule.domain == "schema"
    assert rule.pinned is False
    assert rule.content["status_groups"]["living"] == ["Living", "Active"]


def test_parse_answer_to_rule_falls_back_to_raw_answer_on_yaml_failure():
    question = DEFAULT_QUESTIONS[0]
    adapter = _YamlAdapter("status_groups: [unterminated")

    rule = parse_answer_to_rule(question, "Statuses are messy.", adapter)

    assert rule.content == {"raw_answer": "Statuses are messy."}


def test_interview_session_round_trip(tmp_path: Path):
    state_path = tmp_path / "interview_state.json"
    manager = InterviewSession(state_path)

    state = manager.load_or_create("Test Garden")
    manager.mark_completed(state, DEFAULT_QUESTIONS[0].question_id, "Answer one")
    manager.mark_skipped(state, DEFAULT_QUESTIONS[1].question_id)
    manager.save(state)

    loaded = manager.load_or_create("Ignored Garden")

    assert loaded.garden_name == "Test Garden"
    assert loaded.completed_questions == [DEFAULT_QUESTIONS[0].question_id]
    assert loaded.skipped_questions == [DEFAULT_QUESTIONS[1].question_id]
    assert loaded.answers[DEFAULT_QUESTIONS[0].question_id] == "Answer one"


def test_interview_session_next_question_skips_completed_and_skipped(tmp_path: Path):
    state_path = tmp_path / "interview_state.json"
    manager = InterviewSession(state_path)
    state = manager.load_or_create("Test Garden")
    manager.mark_completed(state, DEFAULT_QUESTIONS[0].question_id, "done")
    manager.mark_skipped(state, DEFAULT_QUESTIONS[1].question_id)

    next_question = manager.next_question(state)

    assert next_question is not None
    assert next_question.question_id == DEFAULT_QUESTIONS[2].question_id
    assert state.current_question == DEFAULT_QUESTIONS[2].question_id


def test_interview_session_is_complete_when_all_questions_handled(tmp_path: Path):
    state_path = tmp_path / "interview_state.json"
    manager = InterviewSession(state_path)
    state = manager.load_or_create("Test Garden")

    for idx, question in enumerate(DEFAULT_QUESTIONS):
        if idx % 2 == 0:
            manager.mark_completed(state, question.question_id, f"answer {idx}")
        else:
            manager.mark_skipped(state, question.question_id)

    assert manager.is_complete(state) is True


def test_interview_session_mark_completed_and_skipped(tmp_path: Path):
    state_path = tmp_path / "interview_state.json"
    manager = InterviewSession(state_path)
    state = manager.load_or_create("Test Garden")
    question_id = DEFAULT_QUESTIONS[0].question_id

    manager.mark_skipped(state, question_id)
    assert question_id in state.skipped_questions

    manager.mark_completed(state, question_id, "final answer")
    assert question_id in state.completed_questions
    assert question_id not in state.skipped_questions
    assert state.answers[question_id] == "final answer"


def test_interview_session_reset_clears_state(tmp_path: Path):
    state_path = tmp_path / "interview_state.json"
    manager = InterviewSession(state_path)
    state = manager.load_or_create("Test Garden")
    manager.mark_completed(state, DEFAULT_QUESTIONS[0].question_id, "answer")
    manager.mark_skipped(state, DEFAULT_QUESTIONS[1].question_id)

    manager.reset(state)

    assert state.completed_questions == []
    assert state.skipped_questions == []
    assert state.answers == {}
    assert state.current_question is None


def test_default_questions_have_required_unique_fields():
    question_ids = [question.question_id for question in DEFAULT_QUESTIONS]
    rule_ids = [question.rule_id for question in DEFAULT_QUESTIONS]

    assert len(question_ids) == len(set(question_ids))
    assert len(rule_ids) == len(set(rule_ids))

    for question in DEFAULT_QUESTIONS:
        assert isinstance(question, InterviewQuestion)
        assert question.question_id
        assert question.domain
        assert question.title
        assert question.prompt_template
        assert question.rule_id
        assert question.rule_tags
