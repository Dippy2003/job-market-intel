"""Group jobs into role clusters from their skills and titles.

Each job becomes one binary TF-IDF vector: skill names, plus words from the
title that are not seniority or generic job words. KMeans fits those vectors
with a fixed ``random_state`` so the same jobs always land in the same
groups. A cluster's label is the role its skills and titles point to
(Backend, Frontend, Data/ML, DevOps, QA, Mobile, and the other names below).
When that vote is empty, the label is the cluster's top skills.

Fewer than two jobs, or fewer distinct skill profiles than requested, does
not raise. ``k`` is reduced to the number of distinct profiles, and a single
shared profile becomes one cluster.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

log = logging.getLogger(__name__)

RANDOM_STATE = 42
DEFAULT_K = 6
MIN_JOBS = 2
TOP_SKILLS = 5
TOP_TITLES = 3
SKILL_VOTE = 2
TITLE_VOTE = 1

# Taxonomy categories that name a role. language, database, tools, and
# methodology are shared across roles, so they do not vote.
CATEGORY_TO_ROLE = {
    "frontend": "Frontend",
    "backend": "Backend",
    "mobile": "Mobile",
    "devops": "DevOps",
    "cloud": "DevOps",
    "machine_learning": "Data/ML",
    "data": "Data/ML",
    "analytics": "Analytics",
    "testing": "QA",
    "security": "Security",
    "design": "Design",
    "cms": "CMS",
    "networking": "Networking",
    "enterprise": "Enterprise",
}

# Whole title tokens. Skill names are scored separately.
TITLE_ROLES = {
    "frontend": "Frontend",
    "front-end": "Frontend",
    "ui": "Frontend",
    "backend": "Backend",
    "back-end": "Backend",
    "fullstack": "Full Stack",
    "full-stack": "Full Stack",
    "devops": "DevOps",
    "sre": "DevOps",
    "qa": "QA",
    "sdet": "QA",
    "tester": "QA",
    "mobile": "Mobile",
    "android": "Mobile",
    "ios": "Mobile",
    "data": "Data/ML",
    "ml": "Data/ML",
    "scientist": "Data/ML",
    "analytics": "Analytics",
    "analyst": "Analytics",
    "security": "Security",
    "cyber": "Security",
    "cybersecurity": "Security",
    "ux": "Design",
}

TITLE_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "assistant",
        "associate",
        "at",
        "based",
        "be",
        "by",
        "colombo",
        "consultant",
        "contract",
        "dev",
        "developer",
        "engineer",
        "executive",
        "experience",
        "experienced",
        "for",
        "from",
        "go",
        "hiring",
        "hybrid",
        "i",
        "ii",
        "iii",
        "in",
        "intern",
        "internship",
        "is",
        "iv",
        "job",
        "jr",
        "junior",
        "lanka",
        "lead",
        "level",
        "looking",
        "manager",
        "mid",
        "new",
        "of",
        "officer",
        "on",
        "opening",
        "openings",
        "or",
        "our",
        "part",
        "permanent",
        "plus",
        "principal",
        "remote",
        "required",
        "role",
        "senior",
        "software",
        "specialist",
        "sr",
        "sri",
        "team",
        "that",
        "the",
        "this",
        "time",
        "to",
        "vacancy",
        "wanted",
        "we",
        "with",
        "work",
        "working",
        "year",
        "years",
        "you",
        "your",
    }
)

_TOKEN_RE = re.compile(r"[^a-z0-9_+#./-]")
_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "skills_taxonomy.json"


@dataclass(frozen=True)
class ClusterJob:
    """One non-duplicate job. ``categories`` lines up with ``skills`` when known."""

    job_id: int
    title: str
    skills: tuple[str, ...]
    categories: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class RoleGroup:
    """One cluster after labeling. ``job_ids`` is sorted."""

    label: str
    top_skills: tuple[str, ...]
    top_titles: tuple[str, ...]
    job_ids: tuple[int, ...]

    @property
    def size(self) -> int:
        return len(self.job_ids)


@dataclass(frozen=True)
class ClusterBuild:
    """Clusters computed from the current jobs, before anything is written."""

    clusters: tuple[RoleGroup, ...]
    jobs: int
    profiles: int
    k_requested: int
    k_used: int
    too_few: bool


def normalize_token(value: str) -> str:
    """Lowercase a skill or title word and keep characters that distinguish C#, C++, and .NET."""
    text = value.strip().lower().replace("&", " and ")
    text = re.sub(r"\s+", "_", text)
    text = _TOKEN_RE.sub("", text)
    return text.strip("_")


def title_tokens(title: str) -> list[str]:
    """Words from a title that can separate roles. Seniority and generic job words are dropped."""
    tokens: list[str] = []
    for word in re.split(r"[\s,/|]+", title.strip().lower()):
        token = normalize_token(word)
        if not token or token in TITLE_STOP:
            continue
        tokens.append(token)
    return tokens


@lru_cache(maxsize=1)
def taxonomy_roles() -> dict[str, str]:
    """Map a taxonomy skill name to a role. Skills in shared categories are omitted."""
    try:
        payload = json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Skill taxonomy could not be read at %s", _TAXONOMY_PATH)
        return {}
    roles: dict[str, str] = {}
    for skill in payload.get("skills", []):
        name = skill.get("name")
        category = skill.get("category")
        if not name or not category:
            continue
        role = CATEGORY_TO_ROLE.get(str(category).strip().lower())
        if role:
            roles[str(name).casefold()] = role
    return roles


def _skill_pairs(job: ClusterJob) -> list[tuple[str, str | None]]:
    pairs: list[tuple[str, str | None]] = []
    for index, skill in enumerate(job.skills):
        if not skill or not str(skill).strip():
            continue
        category = job.categories[index] if index < len(job.categories) else None
        if category is not None and not str(category).strip():
            category = None
        pairs.append((str(skill).strip(), None if category is None else str(category).strip()))
    return pairs


def _document(job: ClusterJob) -> str:
    skill_tokens = sorted({normalize_token(skill) for skill, _category in _skill_pairs(job)})
    words = sorted(set(title_tokens(job.title or "")))
    return " ".join(token for token in (*skill_tokens, *words) if token)


def _role_scores(jobs: Sequence[ClusterJob], taxonomy: dict[str, str]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for job in jobs:
        for skill, category in _skill_pairs(job):
            role = CATEGORY_TO_ROLE.get(category.lower()) if category else None
            if role is None:
                role = taxonomy.get(skill.casefold())
            if role:
                scores[role] = scores.get(role, 0) + SKILL_VOTE
        title_roles: set[str] = set()
        tokens = set(title_tokens(job.title or ""))
        for token in tokens:
            role = TITLE_ROLES.get(token)
            if role:
                title_roles.add(role)
        if "full" in tokens and "stack" in tokens:
            title_roles.add("Full Stack")
        for role in title_roles:
            scores[role] = scores.get(role, 0) + TITLE_VOTE
    return scores


def _top_skills(jobs: Sequence[ClusterJob]) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for job in jobs:
        seen: set[str] = set()
        for skill, _category in _skill_pairs(job):
            key = skill.casefold()
            if key in seen:
                continue
            seen.add(key)
            counts[skill] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return tuple(name for name, _count in ranked[:TOP_SKILLS])


def _top_titles(jobs: Sequence[ClusterJob]) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for job in jobs:
        title = (job.title or "").strip()
        if title:
            counts[title] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return tuple(name for name, _count in ranked[:TOP_TITLES])


def _label(scores: dict[str, int], top_skills: Sequence[str], top_titles: Sequence[str]) -> str:
    if not scores:
        if top_skills:
            return " / ".join(top_skills[:3])
        if top_titles:
            return top_titles[0]
        return "Unlabeled"
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_role, best_score = ranked[0]
    if len(ranked) > 1:
        second_role, second_score = ranked[1]
        tied = {best_role, second_role}
        third_tied = len(ranked) > 2 and ranked[2][1] == best_score
        if best_score == second_score and tied == {"Frontend", "Backend"} and not third_tied:
            return "Full Stack"
    return best_role


_Draft = tuple[str, tuple[str, ...], tuple[str, ...], tuple[int, ...]]


def _disambiguate(drafts: list[_Draft]) -> list[RoleGroup]:
    """Give clusters that share a role name their top skill, so labels stay unique."""
    counts = Counter(label for label, *_rest in drafts)
    adjusted: list[_Draft] = []
    for label, skills, titles, job_ids in drafts:
        if counts[label] > 1:
            extra = skills[0] if skills else (titles[0] if titles else "mixed")
            label = f"{label} · {extra}"
        adjusted.append((label, skills, titles, job_ids))
    used: set[str] = set()
    groups: list[RoleGroup] = []
    for label, skills, titles, job_ids in adjusted:
        candidate = label
        suffix = 2
        while candidate in used:
            candidate = f"{label} ({suffix})"
            suffix += 1
        used.add(candidate)
        groups.append(RoleGroup(candidate, skills, titles, job_ids))
    return groups


def _empty(jobs: int, k: int, profiles: int = 0) -> ClusterBuild:
    return ClusterBuild(
        clusters=(),
        jobs=jobs,
        profiles=profiles,
        k_requested=k,
        k_used=0,
        too_few=True,
    )


def build_role_clusters(jobs: Sequence[ClusterJob], *, k: int = DEFAULT_K) -> ClusterBuild:
    """Cluster ``jobs``. ``k`` is clamped to the number of distinct skill profiles."""
    if k < 1:
        raise ValueError("k must be a positive integer")
    ordered = tuple(sorted(jobs, key=lambda job: job.job_id))
    if len(ordered) < MIN_JOBS:
        return _empty(len(ordered), k)
    documents = [_document(job) for job in ordered]
    profiles = len(set(documents))
    if profiles < 1 or not any(documents):
        return _empty(len(ordered), k, profiles)
    k_used = min(k, len(ordered), profiles)
    vectorizer = TfidfVectorizer(lowercase=False, token_pattern=r"(?u)\S+", binary=True, norm="l2")
    matrix = vectorizer.fit_transform(documents)
    model = KMeans(
        n_clusters=k_used,
        random_state=RANDOM_STATE,
        n_init=10,
        max_iter=300,
        algorithm="lloyd",
        init="k-means++",
    )
    assignments = model.fit_predict(matrix)
    members: dict[int, list[ClusterJob]] = {}
    for job, assignment in zip(ordered, assignments, strict=True):
        members.setdefault(int(assignment), []).append(job)
    taxonomy = taxonomy_roles()
    drafts: list[_Draft] = []
    for group in members.values():
        skills = _top_skills(group)
        titles = _top_titles(group)
        label = _label(_role_scores(group, taxonomy), skills, titles)
        job_ids = tuple(sorted(job.job_id for job in group))
        drafts.append((label, skills, titles, job_ids))
    clusters = tuple(
        sorted(
            _disambiguate(drafts),
            key=lambda cluster: (-cluster.size, cluster.label.casefold(), cluster.job_ids[0]),
        )
    )
    return ClusterBuild(
        clusters=clusters,
        jobs=len(ordered),
        profiles=profiles,
        k_requested=k,
        k_used=len(clusters),
        too_few=False,
    )
