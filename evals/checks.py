"""Code evaluators: free, deterministic checks on a finished run.

Each takes the experiment runner's keyword arguments and reads the task output built
by `evals.run.research_task`.
"""

from langfuse import Evaluation

from research_agent.citations import broken_ids


def citations_valid(*, output: dict, **kwargs) -> Evaluation:
    """Guardrail: every [S#] in the report points to a real source."""
    broken = broken_ids(output["draft"], output["sources"])
    return Evaluation(
        name="citations_valid",
        value=not broken,
        data_type="BOOLEAN",
        comment=f"broken IDs: {', '.join(broken)}" if broken else None,
    )


def unresolved_gaps(*, output: dict, **kwargs) -> Evaluation:
    """Claims the self-check still flagged when the report reached approval."""
    gaps = output["gaps"]
    return Evaluation(
        name="unresolved_gaps",
        value=len(gaps),
        data_type="NUMERIC",
        comment="\n".join(f"- {g['claim']}: {g['reason']}" for g in gaps) or None,
    )
