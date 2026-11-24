"""Skill-extraction accuracy. A three-posting fixture. No live network calls."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from config import get_settings
from extraction.evaluate import (
    Metrics,
    build_parser,
    error_lists,
    evaluate_file,
    extract_names,
    load_labelled,
    render_report,
    score,
)
from extraction.skills import Skill, SkillHit, SkillMatcher, load_taxonomy

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "eval_postings.jsonl"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail the test if evaluation tries to call Gemini."""

    def explode(*args, **kwargs):
        raise AssertionError("live network call")

    monkeypatch.setattr("extraction.llm.requests.post", explode)


@pytest.fixture(scope="module")
def matcher():
    return SkillMatcher(load_taxonomy())


def _tiny_matcher() -> SkillMatcher:
    return SkillMatcher(
        (
            Skill("Python", "language", ()),
            Skill("SQL", "language", ()),
            Skill("Go", "language", ("golang",)),
            Skill("Java", "language", ()),
        )
    )


def test_score_micro_and_per_skill_on_perfect_miss_and_extra():
    predicted = [{"Python", "SQL"}, {"Python"}, {"Python", "Java"}]
    gold = [{"Python", "SQL"}, {"Python", "Go"}, {"Python"}]
    result = score(predicted, gold)
    assert result.precision == pytest.approx(0.8)
    assert result.recall == pytest.approx(0.8)
    assert result.f1 == pytest.approx(0.8)
    assert (result.tp, result.fp, result.fn) == (4, 1, 1)
    assert result.per_skill["Python"] == Metrics(1.0, 1.0, 1.0, 3, 0, 0)
    assert result.per_skill["SQL"] == Metrics(1.0, 1.0, 1.0, 1, 0, 0)
    assert result.per_skill["Go"] == Metrics(0.0, 0.0, 0.0, 0, 0, 1)
    assert result.per_skill["Java"] == Metrics(0.0, 0.0, 0.0, 0, 1, 0)
    negatives, positives = error_lists(result)
    assert negatives == (("Go", 1),)
    assert positives == (("Java", 1),)


def test_score_matches_case_and_ignores_padding_and_duplicates():
    result = score([[" Python ", "Python"]], [["python"]])
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)
    assert result.f1 == 1.0
    assert set(result.per_skill) == {"Python"}


def test_score_with_no_postings_is_zero():
    result = score([], [])
    assert (result.precision, result.recall, result.f1) == (0.0, 0.0, 0.0)
    assert result.per_skill == {}


def test_score_rejects_a_string_and_a_length_mismatch():
    with pytest.raises(TypeError):
        score("Python", [["Python"]])
    with pytest.raises(ValueError):
        score([["Python"]], [])


def test_fixture_is_a_perfect_match_a_miss_and_an_extra(matcher):
    postings, skipped = load_labelled(FIXTURE)
    assert skipped == 0
    assert [posting.id for posting in postings] == [1, 2, 3]
    predicted = [
        extract_names(matcher, posting.title, posting.description, None, 2)[0] for posting in postings
    ]
    gold = [list(posting.gold_skills) for posting in postings]
    assert set(predicted[0]) == set(gold[0])
    assert set(gold[1]) - set(predicted[1]) == {"Go"}
    assert set(predicted[1]) <= set(gold[1])
    assert set(predicted[2]) - set(gold[2]) == {"Java"}
    assert set(gold[2]) <= set(predicted[2])
    result = score(predicted, gold)
    assert result.f1 == pytest.approx(0.8)
    assert (result.tp, result.fp, result.fn) == (4, 1, 1)

    report = evaluate_file(FIXTURE, matcher=matcher)
    assert report.evaluated == 3
    assert report.skipped == 0
    assert report.llm_requested is False
    assert report.llm_calls == 0
    assert report.score is not None
    assert report.score.f1 == pytest.approx(result.f1)
    text = render_report(report)
    assert "Evaluated 3 postings. Skipped 0 postings with empty gold_skills." in text
    assert "precision=0.8000" in text
    assert "recall=0.8000" in text
    assert "f1=0.8000" in text
    assert "Top false negatives" in text
    assert "Go" in text
    assert "Top false positives" in text
    assert "Java" in text
    assert "LLM fallback: off." in text


def test_empty_gold_rows_are_skipped(tmp_path):
    path = tmp_path / "labels.jsonl"
    rows = [
        {
            "id": 1,
            "source": "itpro",
            "title": "Python developer",
            "description": "Work with Python.",
            "gold_skills": ["Python"],
        },
        {
            "id": 2,
            "source": "topjobs",
            "title": "Unlabelled",
            "description": "No gold list yet.",
            "gold_skills": [],
        },
        {
            "id": 3,
            "source": "ikman",
            "title": "Blank names",
            "description": "Also unlabelled.",
            "gold_skills": ["  "],
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + "\n", encoding="utf-8")
    report = evaluate_file(path, matcher=_tiny_matcher())
    assert report.evaluated == 1
    assert report.skipped == 2
    assert report.score is not None
    assert report.score.f1 == 1.0
    assert "Skipped 2 postings with empty gold_skills." in render_report(report)


def test_llm_fallback_runs_only_when_requested(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": 9,
                "source": "itpro",
                "title": "Office administrator",
                "description": "Welcomes visitors.",
                "gold_skills": ["Python"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class _FakeLLM:
        enabled = True

        def __init__(self):
            self.calls = 0

        def extract(self, title, description, allowed):
            self.calls += 1
            assert "Python" in allowed.values()
            return [SkillHit("Python", "llm", Decimal("0.6500"))]

    fake = _FakeLLM()
    matcher = _tiny_matcher()
    quiet = evaluate_file(path, use_llm=False, matcher=matcher, llm=fake, min_skills=2)
    assert fake.calls == 0
    assert quiet.llm_enabled is False
    assert quiet.score is not None
    assert quiet.score.fn == 1

    found = evaluate_file(path, use_llm=True, matcher=matcher, llm=fake, min_skills=2)
    assert fake.calls == 1
    assert found.llm_calls == 1
    assert found.score is not None
    assert found.score.f1 == 1.0
    assert "LLM fallback: on (1 call)." in render_report(found)


def test_llm_flag_without_a_key_stays_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("LLM_API_KEY", "   ")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    get_settings.cache_clear()
    path = tmp_path / "labels.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": 4,
                "source": "itpro",
                "title": "Python developer",
                "description": "Work with Python.",
                "gold_skills": ["Python"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        report = evaluate_file(path, use_llm=True, matcher=_tiny_matcher())
    finally:
        get_settings.cache_clear()
    assert report.llm_requested is True
    assert report.llm_enabled is False
    assert report.llm_calls == 0
    assert "LLM_API_KEY is unset" in render_report(report)


def test_cli_help_and_flags():
    parser = build_parser()
    selected = parser.parse_args(["--file", "data/eval/labelled_postings.jsonl", "--llm", "--top", "3"])
    assert selected.file == "data/eval/labelled_postings.jsonl"
    assert selected.llm is True
    assert selected.top == 3
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--file", "x.jsonl", "--top", "0"])
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite://"
    env["LLM_API_KEY"] = ""
    result = subprocess.run(
        [sys.executable, "-m", "extraction.evaluate", "--file", str(FIXTURE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Evaluated 3 postings" in result.stdout
    assert "Skipped 0 postings" in result.stdout
    assert "precision=0.8000" in result.stdout
    assert "LLM fallback: off." in result.stdout
    help_result = subprocess.run(
        [sys.executable, "-m", "extraction.evaluate", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--file" in help_result.stdout
    assert "--llm" in help_result.stdout
