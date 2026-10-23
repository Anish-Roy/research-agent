"""Export hand-labeling sheets for the two judges from an experiment run.

Writes, under evals/labels/:
- citation_support.md: cited claims with the text of the sources they cite
- subquestion_coverage.md: each report with its approved sub-questions
- manifest.json: the same cases as data, for building the calibration datasets

Fill in each `label:` line in the Markdown files; the manifest stays as generated.

    uv run python -m evals.labeling <experiment-id>
"""

import argparse
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path

from evals.claims import cited_claims
from research_agent.tracing import get_langfuse

LABELS_DIR = Path(__file__).parent / "labels"
CLAIMS_PER_REPORT = 3
# Coverage reports in labeling order: the first five span five question types.
COVERAGE_ORDER = ["01", "03", "05", "07", "09", "02", "04", "06", "08", "10"]


def _fetch_items(experiment_id: str) -> list[dict]:
    """The run's items, each with its dataset item ID, trace ID, and task output."""
    api = get_langfuse().api
    items, cursor = [], None
    while True:
        page = api.experiments.list_items(
            experiment_id=experiment_id,
            from_start_time=datetime(2000, 1, 1, tzinfo=UTC),
            fields="core,io",
            cursor=cursor,
        )
        items += page.data
        cursor = page.meta.cursor if page.meta else None
        if not cursor:
            break
    return sorted(
        (
            {
                "item_id": i.experiment_item_id,
                "trace_id": i.trace_id,
                "question": json.loads(i.input)["question"],
                "output": json.loads(i.output),
            }
            for i in items
        ),
        key=lambda i: i["item_id"],
    )


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", re.sub(r"\[S[\d,\s]+\]", "", text).lower()))


def _flagged(claim: str, gaps: list[dict]) -> bool:
    """Whether the self-check listed this claim as a gap. Gaps quote claims loosely, so
    this matches on word overlap."""
    words = _words(claim)
    return any(len(words & _words(g["claim"])) > 0.6 * len(_words(g["claim"])) for g in gaps)


def _sample_claims(items: list[dict], seed: int = 0) -> list[dict]:
    """Per report, one claim the self-check flagged (if any), then random others."""
    rng = random.Random(seed)
    cases = []
    for item in items:
        out = item["output"]
        claims = [
            {**c, "self_check_flagged": _flagged(c["text"], out["gaps"])}
            for c in cited_claims(out["draft"])
        ]
        flagged = [c for c in claims if c["self_check_flagged"]]
        picked = rng.sample(flagged, min(1, len(flagged)))
        rest = [c for c in claims if c not in picked]
        picked += rng.sample(rest, min(CLAIMS_PER_REPORT - len(picked), len(rest)))
        sources = {s["id"]: s for s in out["sources"]}
        for claim in sorted(picked, key=lambda c: claims.index(c)):
            cases.append(
                {
                    "item_id": item["item_id"],
                    "trace_id": item["trace_id"],
                    "question": item["question"],
                    "claim": claim["text"],
                    "sources": [sources[i] for i in claim["source_ids"] if i in sources],
                    "self_check_flagged": claim["self_check_flagged"],
                }
            )
    for n, case in enumerate(cases, 1):
        case["id"] = f"C{n:02d}"
    return cases


def _coverage_cases(items: list[dict]) -> list[dict]:
    by_suffix = {i["item_id"][-2:]: i for i in items}
    cases = []
    for suffix in COVERAGE_ORDER:
        item = by_suffix[suffix]
        for sub_question in item["output"]["sub_questions"]:
            cases.append(
                {
                    "item_id": item["item_id"],
                    "trace_id": item["trace_id"],
                    "question": item["question"],
                    "draft": item["output"]["draft"],
                    "sub_question": sub_question,
                }
            )
    for n, case in enumerate(cases, 1):
        case["id"] = f"Q{n:02d}"
    return cases


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines())


def _claims_sheet(cases: list[dict]) -> str:
    parts = [
        "# citation_support labels",
        "For each claim, read only the cited source text shown and set `label:` to:\n\n"
        "- `supported`: every factual part of the claim is stated in, or directly follows "
        "from, the cited sources.\n"
        "- `unsupported`: any part is missing from the sources, contradicts them, or "
        "overstates them.\n"
        "- `skip`: you can't decide (say why in `note:`).\n\n"
        "Use `note:` for your reason whenever the call isn't obvious; those notes become "
        "the judge's criteria. Wording, style, and whether the claim is true in the real "
        "world don't matter, only whether the shown sources back it. `self-check` shows "
        "what the agent's own check decided, so you can disagree with it.",
    ]
    for c in cases:
        sources = "\n\n".join(
            f"**[{s['id']}] {s['title']}** ({s['url']})\n\n{_quote(s['content'])}"
            for s in c["sources"]
        )
        flag = "flagged as a gap" if c["self_check_flagged"] else "not flagged"
        parts.append(
            f"## {c['id']}\n\n"
            f"Question: {c['question']}  \nSelf-check: {flag}\n\n"
            f"**Claim:** {c['claim']}\n\n{sources}\n\nlabel: \nnote: "
        )
    return "\n\n".join(parts) + "\n"


def _coverage_sheet(cases: list[dict]) -> str:
    parts = [
        "# subquestion_coverage labels",
        "Read each report, then for each of its approved sub-questions set `label:` to:\n\n"
        "- `answered`: the report gives a direct, substantive answer to the sub-question.\n"
        "- `not_answered`: the report skips it, only touches on it, or answers a "
        "different question.\n"
        "- `skip`: you can't decide (say why in `note:`).\n\n"
        "Judge coverage only, not whether the answer is correct or cited. Labeling the "
        "first five reports (Q01-Q25) is enough to start; more helps.",
    ]
    by_item: dict[str, list[dict]] = {}
    for c in cases:
        by_item.setdefault(c["item_id"], []).append(c)
    for item_cases in by_item.values():
        first = item_cases[0]
        labels = "\n\n".join(
            f"### {c['id']}\n\n**Sub-question:** {c['sub_question']}\n\nlabel: \nnote: "
            for c in item_cases
        )
        parts.append(
            f"## {first['question']}\n\n<details><summary>Report</summary>\n\n"
            f"{first['draft'].strip()}\n\n</details>\n\n{labels}"
        )
    return "\n\n".join(parts) + "\n"


def export(experiment_id: str) -> None:
    items = _fetch_items(experiment_id)
    claims, coverage = _sample_claims(items), _coverage_cases(items)
    LABELS_DIR.mkdir(exist_ok=True)
    (LABELS_DIR / "citation_support.md").write_text(_claims_sheet(claims), encoding="utf-8")
    (LABELS_DIR / "subquestion_coverage.md").write_text(_coverage_sheet(coverage), "utf-8")
    manifest = {"experiment_id": experiment_id, "claims": claims, "coverage": coverage}
    (LABELS_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1), "utf-8")
    flagged = sum(c["self_check_flagged"] for c in claims)
    print(f"{len(claims)} claims ({flagged} flagged by self-check), {len(coverage)} sub-questions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_id")
    export(parser.parse_args().experiment_id)
