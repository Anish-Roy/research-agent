"""Run the agent over the eval dataset as a Langfuse experiment.

Each item runs the full graph with `auto_approve`, so the approved sub-questions are the
planner's. Runs go one at a time by default: Tavily rate-limits parallel searches.

    uv run python -m evals.run --name baseline [--judge-version N]

`citation_support` uses the judge prompt labeled `production`, or the version given.
Compare runs only when they were scored by the same judge version.
"""

import argparse
import logging
import subprocess
import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver

from evals.checks import citations_valid, unresolved_gaps
from evals.dataset import DATASET_NAME
from evals.judges import citation_support_evaluator, get_judge_prompt
from evals.preflight import require_openai_key
from research_agent.config import settings
from research_agent.graph import build_graph
from research_agent.tracing import get_langfuse, invoke_traced


async def research_task(*, item, **kwargs) -> dict:
    """Run one question end to end and return what the evaluators need.

    Sources keep their page text, so judges can check claims against what the writer saw.
    """
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    state = await invoke_traced(
        graph,
        {"question": item.input["question"], "auto_approve": True},
        config,
        entrypoint="eval",
    )
    return {
        "draft": state.get("draft", ""),
        "sub_questions": state.get("sub_questions", []),
        "sources": state.get("sources", []),
        "gaps": state.get("gaps", []),
        "research_loops": state.get("research_loops", 0),
    }


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="what this run tests, e.g. baseline")
    parser.add_argument("--description", default=None)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--judge-version", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)  # show tool retries and failures
    require_openai_key()

    try:
        judge_prompt = get_judge_prompt("citation-support", args.judge_version)
    except Exception as e:
        sys.exit(f"no citation-support judge prompt ({e}); pass --judge-version N")

    langfuse = get_langfuse()
    dataset = langfuse.get_dataset(DATASET_NAME)
    result = dataset.run_experiment(
        name=args.name,
        description=args.description,
        task=research_task,
        evaluators=[citations_valid, unresolved_gaps, citation_support_evaluator(judge_prompt)],
        max_concurrency=args.concurrency,
        metadata={
            "git_commit": _git_commit(),
            "planner_model": settings.planner_model,
            "writer_model": settings.writer_model,
            "judge_model": settings.judge_model,
            "judge_prompt_version": str(judge_prompt.version),
        },
    )
    langfuse.flush()
    print(result.format())


if __name__ == "__main__":
    main()
