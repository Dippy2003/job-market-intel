"""Skill extraction. Fixtures and a fake database. No live network calls."""
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from config import Settings
from extraction.llm import (
    DisabledSkillLLM,
    GeminiSkillLLM,
    build_llm,
    parse_skill_response,
)
from extraction.skills import (
    SPACY_CONFIDENCE,
    SPACY_SHORT_CONFIDENCE,
    Skill,
    SkillHit,
    SkillMatcher,
    build_nlp,
    load_taxonomy,
    merge_hits,
)
from pipeline.extract_skills import build_parser, extract_skills, pg_text_array
from scrapers.itpro import ItproScraper

ROOT = Path(__file__).resolve().parents[1]
POSTINGS = json.loads((ROOT / "tests" / "fixtures" / "skill_postings.json").read_text(encoding="utf-8"))
DETAIL = (ROOT / "tests" / "fixtures" / "itpro_job_detail.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail the test if skill extraction tries to call Gemini."""

    def explode(*args, **kwargs):
        raise AssertionError("live network call")

    monkeypatch.setattr("extraction.llm.requests.post", explode)


@pytest.fixture(scope="module")
def matcher():
    return SkillMatcher(load_taxonomy())


def _names(hits) -> set[str]:
    return {hit.name for hit in hits}


def test_taxonomy_covers_categories_aliases_and_short_names():
    skills = load_taxonomy()
    by_name = {skill.name: skill for skill in skills}
    assert len(skills) >= 150
    assert len(by_name) == len(skills)
    assert len({skill.category for skill in skills}) >= 8
    for name in ("C", "C++", "C#", "R", "Go", ".NET", "Python", "Java", "SQL"):
        assert name in by_name
    aliases = {alias.lower() for alias in by_name["Go"].aliases}
    assert "golang" in aliases
    assert "dotnet" in {alias.lower() for alias in by_name[".NET"].aliases}
    assert all(skill.category and skill.name for skill in skills)


def test_tokenizer_is_blank_english_without_a_model():
    nlp = build_nlp()
    assert nlp.pipe_names == []
    assert [token.text for token in nlp("C# and C++ and .NET.")] == ["C#", "and", "C++", "and", ".NET", "."]
    assert [token.text for token in nlp("written in C.")][-2:] == ["C", "."]
    source = (ROOT / "extraction" / "skills.py").read_text(encoding="utf-8")
    assert "spacy.load" not in source
    assert 'spacy.blank("en")' in source


def test_phrase_matches_are_case_insensitive_and_alias_aware(matcher):
    hits = matcher.extract("Backend", "PYTHON and postgresql. We also want scikit learn.")
    found = {hit.name: hit for hit in hits}
    assert found["Python"].confidence == SPACY_CONFIDENCE
    assert found["Python"].method == "spacy"
    assert "PostgreSQL" in found
    assert "scikit-learn" in found
    assert len(hits) == len(found)


@pytest.mark.parametrize("posting", POSTINGS, ids=lambda posting: posting["title"])
def test_word_boundaries_and_aliases(matcher, posting):
    found = _names(matcher.extract(posting["title"], posting["description"]))
    missing = set(posting["expect"]) - found
    extra = set(posting["reject"]) & found
    assert not missing, f"missing {missing} from {found}"
    assert not extra, f"unexpected {extra} in {found}"


def test_short_skill_confidence_is_lower_than_a_phrase(matcher):
    short = {hit.name: hit.confidence for hit in matcher.extract("Go developer", "")}
    phrase = {hit.name: hit.confidence for hit in matcher.extract("Golang services", "")}
    assert short["Go"] == SPACY_SHORT_CONFIDENCE
    assert phrase["Go"] == SPACY_CONFIDENCE


def test_itpro_fixture_finds_stack_skills_and_skips_short_false_friends(matcher):
    job = ItproScraper.__new__(ItproScraper).parse_job(DETAIL, "https://itpro.lk/job/15802/")
    found = _names(matcher.extract(job["title"], job["description"]))
    for name in (
        "Python",
        "Go",
        "Java",
        "AWS",
        "Azure",
        "GCP",
        "Kubernetes",
        "OAuth",
        "OWASP",
        "ISO 27001",
        "Jenkins",
        "SIEM",
        "CI/CD",
        "DevOps",
    ):
        assert name in found
    assert "C" not in found
    assert "R" not in found
    assert "C++" not in found


def test_merge_hits_prefers_spacy_and_dedupes():
    merged = merge_hits(
        [SkillHit("Python", "spacy", Decimal("0.9500"))],
        [
            SkillHit("Python", "llm", Decimal("0.6500")),
            SkillHit("Go", "llm", Decimal("0.6500")),
        ],
    )
    assert {(hit.name, hit.method) for hit in merged} == {("Python", "spacy"), ("Go", "llm")}


def test_blank_llm_key_disables_fallback(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    monkeypatch.setenv("LLM_API_KEY", "   ")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    settings = Settings(_env_file=None)
    llm = build_llm(settings)
    assert isinstance(llm, DisabledSkillLLM)
    assert llm.enabled is False
    assert llm.extract("Go developer", "Golang", {"go": "Go"}) == []


def test_parse_skill_response_keeps_catalog_names_only():
    allowed = {"python": "Python", "go": "Go", "golang": "Go"}
    hits = parse_skill_response(
        '```json\n{"skills": ["Python", "golang", "COBOL", 3]}\n```',
        allowed,
    )
    assert [(hit.name, hit.method, hit.confidence) for hit in hits] == [
        ("Python", "llm", Decimal("0.6500")),
        ("Go", "llm", Decimal("0.6500")),
    ]


def test_gemini_request_puts_the_key_in_a_header(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"skills": ["Python"]}'}]}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("extraction.llm.requests.post", fake_post)
    llm = GeminiSkillLLM("secret-key", "gemini-1.5-flash")
    hits = llm.extract("Backend", "Python services", {"python": "Python"})
    assert [hit.name for hit in hits] == ["Python"]
    assert captured["headers"]["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in captured["url"]
    assert "gemini-1.5-flash" in captured["url"]
    assert captured["json"]["generationConfig"]["temperature"] == 0
    assert "secret-key" not in captured["json"]["contents"][0]["parts"][0]["text"]
    assert "Python" in captured["json"]["contents"][0]["parts"][0]["text"]


def test_gemini_failure_returns_no_skills():
    def boom(prompt):
        raise TimeoutError("slow")

    llm = GeminiSkillLLM("secret-key", "gemini-1.5-flash", transport=boom)
    assert llm.extract("Backend", "Python", {"python": "Python"}) == []


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Conn:
    def __init__(self, jobs, skill_rows):
        self.jobs = jobs
        self.skill_rows = skill_rows
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if "FROM jobs" in sql:
            return _Result(self.jobs)
        if "SELECT id, name FROM skills" in sql:
            return _Result(self.skill_rows)
        return _Result([])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Engine:
    def __init__(self, conn):
        self.conn = conn
        self.began = 0
        self.connected = 0

    def begin(self):
        self.began += 1
        return self.conn

    def connect(self):
        return self.conn


class _FakeLLM:
    enabled = True

    def __init__(self, names, *, only_allowed=True):
        self.names = names
        self.only_allowed = only_allowed
        self.calls = 0

    def extract(self, title, description, allowed):
        self.calls += 1
        hits = []
        for name in self.names:
            if self.only_allowed and name not in allowed.values():
                continue
            hits.append(SkillHit(name, "llm", Decimal("0.6500")))
        return hits


def _tiny_taxonomy(path: Path) -> Path:
    skills = [
        Skill("Python", "language", ()),
        Skill("SQL", "database", ()),
        Skill("Go", "language", ("golang",)),
    ]
    payload = {
        "skills": [
            {"name": skill.name, "category": skill.category, "aliases": list(skill.aliases)}
            for skill in skills
        ]
    }
    file = path / "skills.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    return file


def _jobs():
    return [
        _Row(id=1, title="Python and SQL developer", description="Build APIs"),
        _Row(id=2, title="Office administrator", description="Welcomes visitors in Kandy"),
        _Row(id=3, title="Golang intern", description="Learn the platform"),
    ]


def _skill_rows():
    return [_Row(id=10, name="Python"), _Row(id=11, name="SQL"), _Row(id=12, name="Go")]


def test_pipeline_upserts_pending_jobs_and_calls_llm_only_when_sparse(tmp_path, monkeypatch):
    conn = _Conn(_jobs(), _skill_rows())
    engine = _Engine(conn)
    monkeypatch.setattr("pipeline.extract_skills.get_engine", lambda: engine)
    llm = _FakeLLM(["Go"])
    summary = extract_skills(
        llm=llm,
        min_skills=2,
        taxonomy_path=_tiny_taxonomy(tmp_path),
    )
    sql = "\n".join(statement for statement, _params in conn.statements)
    assert "ON CONFLICT (name)" in sql
    assert "ON CONFLICT (job_id, skill_id)" in sql
    assert "NOT EXISTS" in sql
    assert "job_skills" in sql
    assert engine.began == 1
    assert summary["jobs"] == 3
    assert summary["skills_seeded"] == 3
    assert summary["links"] == 4
    assert summary["spacy"] == 3
    assert summary["llm"] == 1
    assert summary["llm_calls"] == 2
    assert summary["empty"] == 0
    assert llm.calls == 2
    links = [params for statement, params in conn.statements if "INSERT INTO job_skills" in statement]
    by_job = {}
    for params in links:
        link = (params["skill_id"], params["method"], params["confidence"])
        by_job.setdefault(params["job_id"], []).append(link)
    assert by_job[1] == [
        (10, "spacy", Decimal("0.9500")),
        (11, "spacy", Decimal("0.9500")),
    ]
    assert by_job[2] == [(12, "llm", Decimal("0.6500"))]
    assert by_job[3] == [(12, "spacy", Decimal("0.9500"))]
    seeded = [params for statement, params in conn.statements if "INSERT INTO skills" in statement]
    assert len(seeded) == 3
    go = next(params for params in seeded if params["name"] == "Go")
    assert go["aliases"] == '{"golang"}'
    assert go["category"] == "language"


def test_dry_run_reads_jobs_and_writes_nothing(tmp_path, monkeypatch):
    conn = _Conn(_jobs(), _skill_rows())
    engine = _Engine(conn)
    monkeypatch.setattr("pipeline.extract_skills.get_engine", lambda: engine)
    summary = extract_skills(
        dry_run=True,
        llm=DisabledSkillLLM(),
        min_skills=2,
        taxonomy_path=_tiny_taxonomy(tmp_path),
    )
    assert engine.began == 0
    assert summary["dry_run"] is True
    assert summary["skills_seeded"] == 0
    assert summary["llm_enabled"] is False
    assert summary["llm_calls"] == 0
    assert summary["links"] == 3
    assert summary["empty"] == 1
    assert not any("INSERT" in statement for statement, _params in conn.statements)


def test_rerun_with_no_pending_jobs_only_reseeds(tmp_path, monkeypatch):
    conn = _Conn([], _skill_rows())
    monkeypatch.setattr("pipeline.extract_skills.get_engine", lambda: _Engine(conn))
    summary = extract_skills(
        llm=DisabledSkillLLM(),
        min_skills=2,
        taxonomy_path=_tiny_taxonomy(tmp_path),
    )
    assert summary["jobs"] == 0
    assert summary["links"] == 0
    assert summary["skills_seeded"] == 3
    assert any("ON CONFLICT (name)" in statement for statement, _params in conn.statements)
    assert not any("INSERT INTO job_skills" in statement for statement, _params in conn.statements)


def test_limit_is_a_bound_parameter(tmp_path, monkeypatch):
    conn = _Conn([], _skill_rows())
    monkeypatch.setattr("pipeline.extract_skills.get_engine", lambda: _Engine(conn))
    extract_skills(
        limit=5,
        dry_run=True,
        llm=DisabledSkillLLM(),
        min_skills=2,
        taxonomy_path=_tiny_taxonomy(tmp_path),
    )
    limited = [params for statement, params in conn.statements if "LIMIT :limit" in statement]
    assert limited == [{"limit": 5}]


def test_unknown_llm_skill_is_not_written(tmp_path, monkeypatch):
    conn = _Conn([_Row(id=7, title="Reception", description="Front desk")], _skill_rows())
    monkeypatch.setattr("pipeline.extract_skills.get_engine", lambda: _Engine(conn))
    summary = extract_skills(
        llm=_FakeLLM(["Kotlin"], only_allowed=False),
        min_skills=2,
        taxonomy_path=_tiny_taxonomy(tmp_path),
    )
    assert summary["links"] == 0
    assert summary["empty"] == 1
    assert summary["llm_calls"] == 1
    assert not any("INSERT INTO job_skills" in statement for statement, _params in conn.statements)


def test_pg_text_array_escapes_quotes():
    assert pg_text_array([]) == "{}"
    assert pg_text_array(["dotnet", 'a"b']) == '{"dotnet","a\\"b"}'


def test_cli_help_and_flags():
    parser = build_parser()
    defaults = parser.parse_args([])
    assert defaults.limit is None
    assert defaults.dry_run is False
    selected = parser.parse_args(["--limit", "5", "--dry-run"])
    assert selected.limit == 5
    assert selected.dry_run is True
    with pytest.raises(SystemExit):
        parser.parse_args(["--limit", "0"])
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.extract_skills", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout
    assert "--limit" in result.stdout


def test_extract_skills_rejects_bad_limits():
    with pytest.raises(ValueError):
        extract_skills(limit=0, llm=DisabledSkillLLM(), min_skills=2)
