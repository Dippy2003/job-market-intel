"""Match taxonomy skills in a job title and description.

The matcher is spaCy's PhraseMatcher on a blank English tokenizer. Matching
uses the lowercased token text, so it does not depend on lemma tags and does
not download a model. Aliases carry the surface forms that differ (plurals,
abbreviations, and symbols). Short names such as C, R, and Go match only as
whole tokens in a skill context, so they do not fire inside C++, Google, or R&D.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import spacy
from spacy.language import Language
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc
from spacy.util import compile_suffix_regex

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "skills_taxonomy.json"
MAX_CHARS = 100_000
SPACY_CONFIDENCE = Decimal("0.9500")
SPACY_SHORT_CONFIDENCE = Decimal("0.8500")
AMBIGUOUS_TOKENS = frozenset({"c", "r", "go"})

_CUE_BEFORE = frozenset({
    "in", "with", "using", "use", "uses", "used", "via", "including", "include",
    "includes", "of", "know", "knowledge", "proficient", "proficiency",
    "experience", "experienced", "strong", "solid", "good", "expert", "expertise",
    "skills", "skill", "plus", "like", "fluency", "fluent", "written", "write",
    "writing", "coding", "programming", "language", "languages", "stack",
    "tech", "technology", "technologies", "tools", "tool", "have", "has",
    "having", "knowing", "on", "from", "as", "familiar", "familiarity",
})
_CUE_AFTER = frozenset({
    "programming", "language", "languages", "developer", "developers",
    "engineer", "engineers", "development", "programmer", "programmers",
    "lang", "stack", "skills", "skill", "dev", "coder", "coders", "code", "coding",
})
_REJECT_BEFORE = frozenset({
    "let", "lets", "please", "just", "can", "could", "should", "will",
    "would", "shall", "may", "might", "gonna",
})
_GO_REJECT_AFTER = frozenset({
    "to", "through", "ahead", "back", "out", "into", "away", "home",
    "there", "further", "beyond", "wrong", "for", "on", "live",
})
_LIST_WORDS = frozenset({"and", "or"})
_DASHES = ("\u00a0", "\u2010", "\u2011", "\u2013", "\u2014")


@dataclass(frozen=True)
class Skill:
    """One taxonomy row: canonical name, category, and alternate phrases."""

    name: str
    category: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SkillHit:
    """One skill found in a job. method is 'spacy' or 'llm'. confidence is 0 to 1."""

    name: str
    method: str
    confidence: Decimal
    start: int = -1
    end: int = -1


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    name: str
    confidence: Decimal


def build_nlp() -> Language:
    """Blank English pipeline. No model download.

    '#' is not a suffix, so C# and F# stay one token. A period after a letter
    is split off, so a sentence ending in 'C.' still matches C.
    """
    nlp = spacy.blank("en")
    suffixes = [suffix for suffix in nlp.Defaults.suffixes if suffix != "#"]
    suffixes.append(r"(?<=[A-Za-z])\.")
    nlp.tokenizer.suffix_search = compile_suffix_regex(suffixes).search
    return nlp


def _clean_phrase(phrase: str) -> str:
    text = phrase
    for dash in _DASHES[1:]:
        text = text.replace(dash, "-")
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _phrase_key(phrase: str) -> str:
    return _clean_phrase(phrase).lower()


def load_taxonomy(path: Path | None = None) -> tuple[Skill, ...]:
    """Load the seed taxonomy. Phrase strings must map to one skill."""
    file = path or TAXONOMY_PATH
    payload = json.loads(file.read_text(encoding="utf-8"))
    raw = payload["skills"] if isinstance(payload, dict) else payload
    skills: list[Skill] = []
    seen: dict[str, str] = {}
    for item in raw:
        name = _clean_phrase(str(item["name"]))
        category = _clean_phrase(str(item.get("category") or ""))
        if not name or not category:
            raise ValueError(f"Skill entries need a name and a category ({item!r})")
        aliases: list[str] = []
        for alias in item.get("aliases") or []:
            cleaned = _clean_phrase(str(alias))
            if cleaned and _phrase_key(cleaned) != _phrase_key(name):
                aliases.append(cleaned)
        for phrase in (name, *aliases):
            key = _phrase_key(phrase)
            owner = seen.get(key)
            if owner and owner != name:
                raise ValueError(f"Phrase {phrase!r} belongs to both {owner} and {name}")
            seen[key] = name
        skills.append(Skill(name=name, category=category, aliases=tuple(aliases)))
    return tuple(skills)


def _document_text(title: str, description: str | None) -> str:
    parts = [_clean_phrase(title or ""), _clean_phrase(description or "")]
    text = "\n".join(part for part in parts if part)
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS]
    return text


def _content_index(doc: Doc, index: int, direction: int) -> int | None:
    """Neighbor token, skipping punctuation and a single and/or."""
    i = index + direction
    while 0 <= i < len(doc) and doc[i].is_punct:
        i += direction
    if 0 <= i < len(doc) and doc[i].lower_ in _LIST_WORDS:
        i += direction
        while 0 <= i < len(doc) and doc[i].is_punct:
            i += direction
    if 0 <= i < len(doc):
        return i
    return None


def _looks_like_rnd(doc: Doc, index: int) -> bool:
    j = index + 1
    if j < len(doc) and (doc[j].lower_ == "and" or doc[j].text in {"&", "/"}):
        j += 1
    return j < len(doc) and doc[j].lower_ in {"d", "development"}


def _looks_like_go_live(doc: Doc, index: int) -> bool:
    j = index + 1
    if j < len(doc) and doc[j].text in {"-", "/", "–"}:
        j += 1
    return j < len(doc) and doc[j].lower_ in {"live", "lives"}


def _looks_like_c_level(doc: Doc, index: int) -> bool:
    j = index + 1
    if j < len(doc) and doc[j].text in {"-", "–"}:
        j += 1
    return j < len(doc) and doc[j].lower_ in {"level", "suite", "class"}


def _hard_reject(doc: Doc, index: int) -> bool:
    token = doc[index].lower_
    if token == "r" and _looks_like_rnd(doc, index):
        return True
    if token == "c" and _looks_like_c_level(doc, index):
        return True
    if token == "go" and _looks_like_go_live(doc, index):
        return True
    left = doc[index - 1].lower_ if index else ""
    right = doc[index + 1].lower_ if index + 1 < len(doc) else ""
    if left in _REJECT_BEFORE:
        return True
    return token == "go" and right in _GO_REJECT_AFTER


def _context_ok(doc: Doc, index: int, covered: set[int]) -> bool:
    """True when a one-letter or 'go' token sits in a skill list or skill phrase."""
    if _hard_reject(doc, index):
        return False
    for direction in (-1, 1):
        neighbor = _content_index(doc, index, direction)
        if neighbor is None:
            continue
        if neighbor in covered:
            return True
        word = doc[neighbor].lower_
        if direction < 0 and word in _CUE_BEFORE:
            return True
        if direction > 0 and word in _CUE_AFTER:
            return True
    return False


def _resolve(spans: list[_Span]) -> list[_Span]:
    """Keep the longest non-overlapping span for each skill."""
    ordered = sorted(
        spans,
        key=lambda item: (item.end - item.start, item.confidence, -item.start),
        reverse=True,
    )
    chosen: list[_Span] = []
    occupied: list[tuple[int, int]] = []
    seen: set[str] = set()
    for span in ordered:
        if span.name in seen:
            continue
        if any(span.start < stop and span.end > begin for begin, stop in occupied):
            continue
        chosen.append(span)
        occupied.append((span.start, span.end))
        seen.add(span.name)
    return chosen


class SkillMatcher:
    """PhraseMatcher over the taxonomy. Safe to reuse across jobs."""

    def __init__(self, skills: Sequence[Skill]):
        self.skills = tuple(skills)
        self.nlp = build_nlp()
        self._matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        self.allowed: dict[str, str] = {}
        seen_tokens: dict[tuple[str, ...], str] = {}
        for skill in self.skills:
            patterns: list[Doc] = []
            for phrase in (skill.name, *skill.aliases):
                cleaned = _clean_phrase(phrase)
                if not cleaned:
                    continue
                self.allowed[_phrase_key(cleaned)] = skill.name
                doc = self.nlp.make_doc(cleaned)
                if not doc:
                    continue
                token_key = tuple(token.lower_ for token in doc)
                owner = seen_tokens.get(token_key)
                if owner is None:
                    seen_tokens[token_key] = skill.name
                elif owner != skill.name:
                    raise ValueError(f"Phrase {cleaned!r} matches both {owner} and {skill.name}")
                else:
                    continue
                patterns.append(doc)
            if patterns:
                self._matcher.add(skill.name, patterns)

    def extract(self, title: str, description: str | None = None) -> list[SkillHit]:
        """Return unique skills in title + description. Longer overlapping phrases win."""
        text = _document_text(title, description)
        if not text:
            return []
        doc = self.nlp(text)
        clear: list[_Span] = []
        ambiguous: list[_Span] = []
        for match_id, start, end in self._matcher(doc):
            name = self.nlp.vocab.strings[match_id]
            span = _Span(start, end, name, SPACY_CONFIDENCE)
            if end - start == 1 and doc[start].lower_ in AMBIGUOUS_TOKENS:
                ambiguous.append(_Span(start, end, name, SPACY_SHORT_CONFIDENCE))
            else:
                clear.append(span)
        chosen = _resolve(clear)
        occupied = [(span.start, span.end) for span in chosen]
        seen = {span.name for span in chosen}
        covered = {index for span in chosen for index in range(span.start, span.end)}
        for span in sorted(ambiguous, key=lambda item: item.start):
            if span.name in seen:
                continue
            overlaps = any(span.start < stop and span.end > begin for begin, stop in occupied)
            if overlaps or not _context_ok(doc, span.start, covered):
                continue
            chosen.append(span)
            occupied.append((span.start, span.end))
            seen.add(span.name)
            covered.update(range(span.start, span.end))
        hits = [
            SkillHit(
                name=span.name,
                method="spacy",
                confidence=span.confidence,
                start=span.start,
                end=span.end,
            )
            for span in chosen
        ]
        hits.sort(key=lambda hit: (hit.start, hit.name))
        return hits


def merge_hits(primary: list[SkillHit], extra: list[SkillHit]) -> list[SkillHit]:
    """One hit per skill. The higher confidence wins; spaCy wins a tie."""
    by_name: dict[str, SkillHit] = {}
    for hit in (*primary, *extra):
        current = by_name.get(hit.name)
        if current is None or _prefer(hit, current):
            by_name[hit.name] = hit
    return list(by_name.values())


def _prefer(candidate: SkillHit, current: SkillHit) -> bool:
    if candidate.confidence != current.confidence:
        return candidate.confidence > current.confidence
    return candidate.method == "spacy" and current.method != "spacy"
