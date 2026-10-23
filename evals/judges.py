"""LLM judges, with prompts versioned in Langfuse Prompt Management.

Each judge's prompt lives in evals/prompts/<judge>.txt and is synced to Langfuse as
`judge-calibration/<judge>`. Calibration runs a specific version; experiments use the
version labeled `production`, which is set only after the judge is approved.

Push a changed prompt as a new version:
    uv run python -m evals.judges sync citation-support
Label an approved version for experiments:
    uv run python -m evals.judges promote citation-support <version>
"""

import argparse
import asyncio
from pathlib import Path
from typing import Literal

from langfuse import Evaluation
from langfuse.model import TextPromptClient
from pydantic import BaseModel, Field

from evals.claims import cited_claims
from research_agent.citations import format_sources
from research_agent.config import settings
from research_agent.models import get_model
from research_agent.state import Source
from research_agent.tracing import get_langfuse

PROMPTS_DIR = Path(__file__).parent / "prompts"
MAX_PARALLEL_JUDGE_CALLS = 5

Verdict = Literal["supported", "unsupported", "unknown"]


def prompt_name(judge: str) -> str:
    return f"judge-calibration/{judge}"


def get_judge_prompt(judge: str, version: int | None = None) -> TextPromptClient:
    """A specific version, or the `production` one when no version is given."""
    if version is not None:
        return get_langfuse().get_prompt(prompt_name(judge), version=version)
    return get_langfuse().get_prompt(prompt_name(judge), label="production")


class ClaimVerdict(BaseModel):
    reasoning: str = Field(description="Each assertion in the claim and whether it is backed")
    verdict: Verdict


async def judge_claim(
    prompt: TextPromptClient, question: str, claim: str, sources: list[Source]
) -> ClaimVerdict:
    text = prompt.compile(question=question, claim=claim, sources=format_sources(sources))
    model = get_model("judge", "judge-citation-support").with_structured_output(ClaimVerdict)
    return await model.ainvoke(text)


def citation_support_evaluator(prompt: TextPromptClient):
    """Experiment evaluator: the share of a report's cited claims its sources support.

    `unknown` verdicts are left out of the share and counted in the comment.
    """
    limit = asyncio.Semaphore(MAX_PARALLEL_JUDGE_CALLS)

    async def citation_support(*, input: dict, output: dict, **kwargs) -> Evaluation:
        by_id = {s["id"]: s for s in output["sources"]}
        claims = cited_claims(output["draft"])

        async def judge(c):
            async with limit:
                sources = [by_id[i] for i in c["source_ids"] if i in by_id]
                return await judge_claim(prompt, input["question"], c["text"], sources)

        verdicts = await asyncio.gather(*(judge(c) for c in claims))
        decided = [v for v in verdicts if v.verdict != "unknown"]
        supported = sum(v.verdict == "supported" for v in decided)
        unsupported = [
            c["text"] for c, v in zip(claims, verdicts, strict=True) if v.verdict == "unsupported"
        ]
        comment = f"{supported}/{len(decided)} claims supported"
        if unknown := len(verdicts) - len(decided):
            comment += f", {unknown} unknown"
        if unsupported:
            comment += "\nUnsupported:\n" + "\n".join(f"- {t}" for t in unsupported)
        return Evaluation(
            name="citation_support",
            value=supported / len(decided) if decided else 0.0,
            data_type="NUMERIC",
            comment=comment,
            metadata={
                "prompt_version": prompt.version,
                "judge_model": settings.judge_model,
                "verdicts": [
                    {"claim": c["text"], "verdict": v.verdict, "reasoning": v.reasoning}
                    for c, v in zip(claims, verdicts, strict=True)
                ],
            },
        )

    return citation_support


def sync(judge: str) -> None:
    """Create a new prompt version if the local file differs from the latest one."""
    langfuse = get_langfuse()
    text = (PROMPTS_DIR / f"{judge}.txt").read_text(encoding="utf-8")
    try:
        latest = langfuse.get_prompt(prompt_name(judge), label="latest", cache_ttl_seconds=0)
        if latest.prompt == text:
            print(f"{prompt_name(judge)} v{latest.version} is up to date")
            return
    except Exception:  # not created yet
        pass
    created = langfuse.create_prompt(
        name=prompt_name(judge),
        prompt=text,
        type="text",
        config={"model": settings.judge_model},
    )
    print(f"created {prompt_name(judge)} v{created.version}")


def promote(judge: str, version: int) -> None:
    get_langfuse().api.prompt_version.update(
        name=prompt_name(judge), version=version, new_labels=["production"]
    )
    print(f"{prompt_name(judge)} v{version} is now production")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["sync", "promote"])
    parser.add_argument("judge")
    parser.add_argument("version", nargs="?", type=int)
    args = parser.parse_args()
    if args.action == "sync":
        sync(args.judge)
    else:
        promote(args.judge, args.version)
