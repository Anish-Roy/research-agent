"""Compare two experiment runs on the eval dataset: scores, agent cost, loops, and time.

Agent cost sums the run's generations, leaving out the judge's own calls, so a change in
judge tracing doesn't look like a change in the agent.

    uv run python -m evals.compare <experiment-id-a> <experiment-id-b>
"""

import argparse
import json
from datetime import UTC, datetime
from statistics import mean

from research_agent.tracing import get_langfuse

SCORES = ["citation_support", "unresolved_gaps", "citations_valid"]
JUDGE_GENERATIONS = {"judge-citation-support"}
SINCE = datetime(2026, 1, 1, tzinfo=UTC)


def _items(experiment_id: str) -> list:
    api = get_langfuse().api
    items, cursor = [], None
    while True:
        page = api.experiments.list_items(
            experiment_id=experiment_id,
            from_start_time=SINCE,
            fields="core,io,scores",
            score_limit=20,
            cursor=cursor,
        )
        items += page.data
        cursor = page.meta.cursor if page.meta else None
        if not cursor:
            return items


def _agent_cost(trace_id: str) -> float:
    observations = (
        get_langfuse()
        .api.observations.get_many(
            trace_id=trace_id, type="GENERATION", fields="core,basic,usage", limit=1000
        )
        .data
    )
    return sum((o.total_cost or 0) for o in observations if o.name not in JUDGE_GENERATIONS)


def summarize(experiment_id: str) -> dict:
    rows = {}
    for item in _items(experiment_id):
        output = json.loads(item.output) if isinstance(item.output, str) else item.output
        scores = {s.name: s.value for s in (item.scores or []) if s.name in SCORES}
        rows[item.experiment_item_id] = {
            **scores,
            "research_loops": (output or {}).get("research_loops"),
            "agent_cost": _agent_cost(item.trace_id),
            "seconds": (item.end_time - item.start_time).total_seconds(),
        }
    return rows


def _fmt(value) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def compare(a: str, b: str) -> None:
    runs = [summarize(a), summarize(b)]
    keys = [*SCORES, "research_loops", "agent_cost", "seconds"]
    print(f"{'metric':<18}{'A':>10}{'B':>10}")
    for key in keys:
        means = []
        for rows in runs:
            values = [float(r[key]) for r in rows.values() if r.get(key) is not None]
            means.append(mean(values) if values else None)
        print(f"{key:<18}{_fmt(means[0]):>10}{_fmt(means[1]):>10}")
    print("\nper item (A -> B): citation_support, unresolved_gaps, research_loops")
    for item_id in sorted(runs[0]):
        ra, rb = runs[0][item_id], runs[1].get(item_id, {})
        cells = [
            f"{_fmt(ra.get(k))} -> {_fmt(rb.get(k))}"
            for k in ("citation_support", "unresolved_gaps", "research_loops")
        ]
        print(f"{item_id[-2:]}  " + "   ".join(cells))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_a")
    parser.add_argument("experiment_b")
    args = parser.parse_args()
    compare(args.experiment_a, args.experiment_b)
