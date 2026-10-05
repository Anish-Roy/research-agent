"""Graph state.

Only `question` is required on input. Every other key is absent until a node writes
it, so nodes read them with `state.get(key, default)`.

`sources` is the only key with a reducer. Parallel `research_one` tasks (fanned out
with `Send`) must write only `sources`: two tasks writing any other key in the same
step raises `InvalidUpdateError`.
"""

from typing import Annotated, NotRequired, TypedDict


class FoundSource(TypedDict):
    """A source as returned by `research_one`, before it has an ID."""

    url: str
    title: str
    content: str  # trimmed page text
    sub_question: str  # the sub-question this source answers


class Source(FoundSource):
    id: str  # "S1", "S2", ... cited in the draft as [S1]; assigned by `add_sources`


class Gap(TypedDict):
    """A claim the self-check found unsupported: for this sub-question, the draft made
    this claim citing these sources, and it fails for this reason."""

    sub_question: str  # the sub-question the claim answers
    claim: str
    source_ids: list[str]  # IDs the claim cites; empty if it cites none
    reason: str


class ResearchTask(TypedDict):
    """Input for one `research_one` task, sent by `approve_plan` or `self_check`."""

    sub_question: str
    gap: NotRequired[Gap]  # set when re-researching a gap from the self-check
    cited_urls: NotRequired[list[str]]  # URLs of the gap's cited sources


def _normalize_url(url: str) -> str:
    return url.strip().split("#", 1)[0].rstrip("/")


def add_sources(
    existing: list[Source] | None, new: list[FoundSource] | list[Source] | None
) -> list[Source]:
    """Append new sources, dropping URLs already seen and assigning sequential IDs.

    IDs are assigned here, not in `research_one`, so parallel tasks can't collide.
    LangGraph applies a step's writes in a fixed order, so IDs are stable on resume.
    """
    merged = list(existing or [])
    seen = {_normalize_url(s["url"]) for s in merged}
    for found in new or []:
        url = _normalize_url(found["url"])
        if url in seen:
            continue
        seen.add(url)
        merged.append(
            Source(
                id=f"S{len(merged) + 1}",
                url=found["url"],
                title=found["title"],
                content=found["content"],
                sub_question=found["sub_question"],
            )
        )
    return merged


class ResearchState(TypedDict):
    question: str
    sub_questions: NotRequired[list[str]]
    sources: NotRequired[Annotated[list[Source], add_sources]]
    gaps: NotRequired[list[Gap]]  # replaced by each self-check, not appended
    draft: NotRequired[str]
    research_loops: NotRequired[int]  # self-check loops, capped at 2
    revision_loops: NotRequired[int]  # human change requests on the report
    auto_approve: NotRequired[bool]  # approval nodes return "approve" without interrupting
    plan_feedback: NotRequired[str]  # from approve_plan, read by plan
    report_feedback: NotRequired[str]  # from approve_report, read by write
