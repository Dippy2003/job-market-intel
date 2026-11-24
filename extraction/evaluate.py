"""Score skill extraction against hand-labelled postings.

``score`` reports micro-averaged precision, recall, and F1, plus the same
figures for each skill. Names match case-insensitively after whitespace is
collapsed, and a skill counts once per posting.

The CLI runs ``extraction.skills.SkillMatcher``. The Gemini fallback is used
only with ``--llm`` and only when ``LLM_API_KEY`` is set in the environment
or in ``.env`` (read through ``config``). The key is never printed.

    python -m extraction.evaluate --file data/eval/labelled_postings.jsonl
    python -m extraction.evaluate --file data/eval/labelled_postings.jsonl --llm

Rows whose ``gold_skills`` list is empty are skipped, and the summary says
how many were skipped.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from extraction.skills import SkillHit, SkillMatcher, load_taxonomy, merge_hits


class _SkillLLM(Protocol):
    """The slice of the LLM client this scorer calls. The key stays in config."""

    enabled: bool

    def extract(
        self,
        title: str,
        description: str | None,
        allowed: dict[str, str],
    ) -> list[SkillHit]:
        """Return catalog skills for one posting."""


DEFAULT_TOP = 10


@dataclass(frozen=True)
class Metrics:
    """Precision, recall, and F1 for one skill or for the micro average."""

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int


@dataclass(frozen=True)
class Score:
    """Micro-averaged precision, recall, and F1, plus one ``Metrics`` per skill.

    The top-level figures are the micro average: true positives, false
    positives, and false negatives summed across postings and skills.
    ``per_skill`` omits skills that never appear in a prediction or a label.
    """

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    per_skill: dict[str, Metrics]


@dataclass(frozen=True)
class Posting:
    """One labelled posting loaded from JSONL."""

    id: object
    source: str
    title: str
    description: str
    gold_skills: tuple[str, ...]


@dataclass(frozen=True)
class EvalReport:
    """Counts, scores, and the ranked mistakes the CLI prints."""

    evaluated: int
    skipped: int
    score: Score | None
    false_negatives: tuple[tuple[str, int], ...]
    false_positives: tuple[tuple[str, int], ...]
    llm_requested: bool
    llm_enabled: bool
    llm_calls: int
    top: int


def _clean_names(skills: Iterable[str]) -> tuple[str, ...]:
    """Strip and collapse whitespace. Drop blanks. Keep the first spelling."""
    if isinstance(skills, str):
        raise TypeError("skills must be a collection of names, not a string")
    ordered: dict[str, None] = {}
    for skill in skills:
        if not isinstance(skill, str):
            raise TypeError(f"skill names must be strings, got {type(skill).__name__}")
        name = " ".join(skill.split())
        if name:
            ordered.setdefault(name, None)
    return tuple(ordered)


def _name_map(skills: Iterable[str]) -> dict[str, str]:
    """Map a case-folded name to the first display spelling."""
    found: dict[str, str] = {}
    for name in _clean_names(skills):
        found.setdefault(name.casefold(), name)
    return found


def _metrics(tp: int, fp: int, fn: int) -> Metrics:
    """Precision, recall, and F1. No decisions at all scores 1. A zero denominator scores 0."""
    if tp == 0 and fp == 0 and fn == 0:
        return Metrics(1.0, 1.0, 1.0, 0, 0, 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    if precision + recall == 0.0:
        f1 = 0.0
    else:
        f1 = 2.0 * precision * recall / (precision + recall)
    return Metrics(precision, recall, f1, tp, fp, fn)


def score(pred: Sequence[Iterable[str]], gold: Sequence[Iterable[str]]) -> Score:
    """Return micro-averaged precision, recall, and F1, plus the same metrics per skill.

    ``pred`` and ``gold`` are parallel sequences of skill-name collections.
    With no postings, every figure is 0. A posting where both sides are empty
    matches perfectly and does not change the counts.
    """
    if isinstance(pred, str) or isinstance(gold, str):
        raise TypeError("pred and gold must be sequences of skill collections, not strings")
    if len(pred) != len(gold):
        raise ValueError(f"pred and gold must have the same length ({len(pred)} != {len(gold)})")
    if not pred:
        return Score(0.0, 0.0, 0.0, 0, 0, 0, {})

    predicted = [_name_map(item) for item in pred]
    labelled = [_name_map(item) for item in gold]
    display: dict[str, str] = {}
    for mapping in (*predicted, *labelled):
        for key, name in mapping.items():
            display.setdefault(key, name)

    tp = fp = fn = 0
    per_tp: dict[str, int] = {}
    per_fp: dict[str, int] = {}
    per_fn: dict[str, int] = {}
    for guess, truth in zip(predicted, labelled, strict=True):
        hit = set(guess) & set(truth)
        extra = set(guess) - set(truth)
        missed = set(truth) - set(guess)
        tp += len(hit)
        fp += len(extra)
        fn += len(missed)
        for key in hit:
            per_tp[key] = per_tp.get(key, 0) + 1
        for key in extra:
            per_fp[key] = per_fp.get(key, 0) + 1
        for key in missed:
            per_fn[key] = per_fn.get(key, 0) + 1

    per_skill = {
        display[key]: _metrics(per_tp.get(key, 0), per_fp.get(key, 0), per_fn.get(key, 0))
        for key in sorted(display, key=lambda item: display[item].casefold())
    }
    micro = _metrics(tp, fp, fn)
    return Score(micro.precision, micro.recall, micro.f1, micro.tp, micro.fp, micro.fn, per_skill)


def error_lists(result: Score) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]:
    """False negatives, then false positives, most frequent first and then by name."""
    negatives = tuple(
        sorted(
            ((name, metrics.fn) for name, metrics in result.per_skill.items() if metrics.fn),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    )
    positives = tuple(
        sorted(
            ((name, metrics.fp) for name, metrics in result.per_skill.items() if metrics.fp),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    )
    return negatives, positives


def load_labelled(path: Path) -> tuple[tuple[Posting, ...], int]:
    """Load JSONL rows. The second value is how many rows had an empty gold list.

    Blank lines are ignored. ``gold_skills`` must be a list. A row is skipped
    when that list is missing, null, or has no skill names after cleaning.
    """
    postings: list[Posting] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: each row must be a JSON object")
            gold = payload.get("gold_skills", [])
            if gold is None:
                gold = []
            if not isinstance(gold, list):
                raise ValueError(f"{path}:{line_no}: gold_skills must be a list")
            try:
                names = _clean_names(gold)
            except TypeError as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
            if not names:
                skipped += 1
                continue
            postings.append(
                Posting(
                    id=payload.get("id"),
                    source=str(payload.get("source") or ""),
                    title=str(payload.get("title") or ""),
                    description=str(payload.get("description") or ""),
                    gold_skills=names,
                )
            )
    return tuple(postings), skipped


def extract_names(
    matcher: SkillMatcher,
    title: str,
    description: str | None,
    llm: _SkillLLM | None,
    min_skills: int,
) -> tuple[list[str], bool]:
    """Skill names from the matcher, and whether the LLM fallback was called.

    The LLM runs only when it is enabled and the matcher found fewer than
    ``min_skills`` hits.
    """
    hits: list[SkillHit] = matcher.extract(title, description)
    called = False
    if llm is not None and llm.enabled and len(hits) < min_skills:
        hits = merge_hits(hits, llm.extract(title, description, matcher.allowed))
        called = True
    return sorted({hit.name for hit in hits}), called


def _resolve_llm(
    use_llm: bool,
    llm: _SkillLLM | None,
    min_skills: int | None,
) -> tuple[_SkillLLM | None, bool, int]:
    """Return the client, whether it is enabled, and the sparse-hit threshold.

    Without ``use_llm`` the client is ignored, so a key in ``.env`` cannot
    turn the fallback on. With ``use_llm`` and no injected client, the key
    and the threshold come from ``config``.
    """
    if not use_llm:
        return None, False, 0 if min_skills is None else min_skills
    if llm is None or min_skills is None:
        from config import get_settings

        settings = get_settings()
        if llm is None:
            from extraction.llm import build_llm

            llm = build_llm(settings)
        if min_skills is None:
            min_skills = settings.llm_min_skills
    if min_skills < 0:
        raise ValueError("min_skills must be >= 0")
    return llm, bool(llm.enabled), min_skills


def evaluate_file(
    path: Path,
    *,
    use_llm: bool = False,
    matcher: SkillMatcher | None = None,
    llm: _SkillLLM | None = None,
    min_skills: int | None = None,
    taxonomy_path: Path | None = None,
    top: int = DEFAULT_TOP,
) -> EvalReport:
    """Score one JSONL file. Empty gold lists are skipped and counted."""
    if top < 1:
        raise ValueError("top must be a positive integer")
    postings, skipped = load_labelled(path)
    if matcher is None:
        matcher = SkillMatcher(load_taxonomy(taxonomy_path))
    client, enabled, threshold = _resolve_llm(use_llm, llm, min_skills)
    calls = 0
    predicted: list[list[str]] = []
    for posting in postings:
        names, called = extract_names(matcher, posting.title, posting.description, client, threshold)
        if called:
            calls += 1
        predicted.append(names)
    scored = score(predicted, [list(posting.gold_skills) for posting in postings]) if postings else None
    negatives: tuple[tuple[str, int], ...] = ()
    positives: tuple[tuple[str, int], ...] = ()
    if scored is not None:
        negatives, positives = error_lists(scored)
    return EvalReport(
        evaluated=len(postings),
        skipped=skipped,
        score=scored,
        false_negatives=negatives,
        false_positives=positives,
        llm_requested=use_llm,
        llm_enabled=enabled,
        llm_calls=calls,
        top=top,
    )


def _noun(count: int) -> str:
    return "posting" if count == 1 else "postings"


def _rank_lines(rows: Sequence[tuple[str, int]], top: int) -> list[str]:
    shown = list(rows)[:top]
    if not shown:
        return ["  (none)"]
    return [f"  {index}. {name}  {count}" for index, (name, count) in enumerate(shown, start=1)]


def render_report(report: EvalReport) -> str:
    """Summary table, then the most common false negatives and false positives."""
    lines = [
        f"Evaluated {report.evaluated} {_noun(report.evaluated)}. "
        f"Skipped {report.skipped} {_noun(report.skipped)} with empty gold_skills."
    ]
    if report.score is None:
        lines.append("No labelled postings to score.")
    else:
        metrics = report.score
        lines.append(
            f"Micro  precision={metrics.precision:.4f}  recall={metrics.recall:.4f}  "
            f"f1={metrics.f1:.4f}  tp={metrics.tp}  fp={metrics.fp}  fn={metrics.fn}"
        )
        lines.append("")
        lines.append("Per skill")
        ranked = sorted(
            report.score.per_skill.items(),
            key=lambda item: (item[1].f1, -item[1].fn, item[0].casefold()),
        )
        name_width = max([len("skill"), *(len(name) for name, _metrics_row in ranked)])
        lines.append(
            f"{'skill':<{name_width}}  {'precision':>9}  {'recall':>9}  "
            f"{'f1':>9}  {'tp':>3}  {'fp':>2}  {'fn':>2}"
        )
        for name, row in ranked:
            lines.append(
                f"{name:<{name_width}}  {row.precision:9.4f}  {row.recall:9.4f}  "
                f"{row.f1:9.4f}  {row.tp:3d}  {row.fp:2d}  {row.fn:2d}"
            )
        lines.append("")
        lines.append("Top false negatives")
        lines.extend(_rank_lines(report.false_negatives, report.top))
        lines.append("")
        lines.append("Top false positives")
        lines.extend(_rank_lines(report.false_positives, report.top))
    if report.llm_requested and report.llm_enabled:
        call_word = "call" if report.llm_calls == 1 else "calls"
        lines.append(f"LLM fallback: on ({report.llm_calls} {call_word}).")
    elif report.llm_requested:
        lines.append("LLM fallback: requested, but LLM_API_KEY is unset. Scored with SkillMatcher only.")
    else:
        lines.append("LLM fallback: off.")
    return "\n".join(lines)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score skill extraction against hand-labelled postings.")
    parser.add_argument(
        "--file",
        required=True,
        help="JSONL file with id, source, title, description, and gold_skills",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Use the Gemini fallback when the matcher is sparse. Requires LLM_API_KEY in .env",
    )
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=DEFAULT_TOP,
        help=f"How many false negatives and false positives to print (default: {DEFAULT_TOP})",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    from config import setup_logging

    args = build_parser().parse_args(argv)
    setup_logging()
    report = evaluate_file(Path(args.file), use_llm=args.llm, top=args.top)
    print(render_report(report))


if __name__ == "__main__":
    main()
