"""plan and approve_plan."""

from typing import Literal

from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from research_agent.models import get_model
from research_agent.nodes.research import question_tasks
from research_agent.state import ResearchState

PLAN_PROMPT = """You are planning research for the question below.
Break it into 3 to 5 focused sub-questions that together answer it.
Each sub-question must be answerable with a web search and must not overlap the others.

Question: {question}"""

REVISE_PROMPT = """
Your previous sub-questions were:
{sub_questions}

The reviewer asked for these changes:
{feedback}

Return a revised list of questions."""


class Plan(BaseModel):
    sub_questions: list[str] = Field(description="3 to 5 focused, non-overlapping sub-questions")


async def plan(state: ResearchState) -> dict:
    prompt = PLAN_PROMPT.format(question=state["question"])
    feedback = state.get("plan_feedback")
    if feedback:
        current = "\n".join(f"- {q}" for q in state.get("sub_questions", []))
        prompt += REVISE_PROMPT.format(sub_questions=current, feedback=feedback)

    model = get_model("planner", "generate-plan").with_structured_output(Plan)
    result = await model.ainvoke(prompt)
    return {"sub_questions": result.sub_questions}


def approve_plan(state: ResearchState) -> Command[Literal["plan", "research_one"]]:
    """Pause for the human to review the sub-questions.

    Interrupt payload:
        {"type": "approve_plan", "question": str, "sub_questions": [str]}
    Resume with:
        {"approved": bool, "sub_questions": [str], "feedback": str}
    Edited `sub_questions` are kept either way. If not approved, `plan` revises them
    using `feedback`.
    """
    sub_questions = state.get("sub_questions", [])
    if state.get("auto_approve"):
        decision = {"approved": True}
    else:
        decision = interrupt(
            {"type": "approve_plan", "question": state["question"], "sub_questions": sub_questions}
        )

    sub_questions = decision.get("sub_questions") or sub_questions
    if decision.get("approved"):
        return Command(
            update={"sub_questions": sub_questions, "plan_feedback": ""},
            goto=question_tasks(sub_questions),
        )
    return Command(
        update={"sub_questions": sub_questions, "plan_feedback": decision.get("feedback", "")},
        goto="plan",
    )
