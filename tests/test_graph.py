"""Graph wiring tests with fake models and Tavily calls, so they run offline."""

from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from research_agent.config import settings
from research_agent.graph import build_graph
from research_agent.nodes import planning, research, review, writing
from research_agent.nodes.planning import Plan
from research_agent.nodes.review import SelfCheck

SUB_QUESTIONS = ["q1", "q2", "q3"]


class FakeModel:
    def __init__(self, calls: dict, self_check_gaps: list[list[dict]]):
        self.calls = calls
        self.self_check_gaps = self_check_gaps

    def with_structured_output(self, schema):
        async def ainvoke(prompt):
            self.calls[schema.__name__] = self.calls.get(schema.__name__, 0) + 1
            if schema is Plan:
                return Plan(sub_questions=SUB_QUESTIONS)
            gaps = self.self_check_gaps.pop(0) if self.self_check_gaps else []
            return SelfCheck(gaps=gaps)

        return SimpleNamespace(ainvoke=ainvoke)

    async def ainvoke(self, prompt):
        if prompt.startswith("Write a research report"):
            self.calls["write"] = self.calls.get("write", 0) + 1
            return SimpleNamespace(text="Answer [S1].")
        return SimpleNamespace(text=prompt.rsplit(": ", 1)[-1])  # search query


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    calls: dict = {}
    gaps: list[list[dict]] = []
    model = FakeModel(calls, gaps)
    for module in (planning, research, review, writing):
        monkeypatch.setattr(module, "get_model", lambda role: model)

    async def get_tools():
        return {"tavily_search": "tavily_search", "tavily_extract": "tavily_extract"}

    async def call(tool, args):
        if tool == "tavily_search":
            q = args["query"]
            return {"results": [{"url": f"https://example.com/{q}", "title": q, "content": q}]}
        return {"results": [{"url": u, "raw_content": f"page {u}"} for u in args["urls"]]}

    monkeypatch.setattr(research, "_get_tools", get_tools)
    monkeypatch.setattr(research, "_call", call)
    return SimpleNamespace(calls=calls, gaps=gaps)


async def test_human_approval_flow(fakes, tmp_path):
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await graph.ainvoke({"question": "Q?"}, config)
    [plan_interrupt] = result["__interrupt__"]
    assert plan_interrupt.value == {
        "type": "approve_plan",
        "question": "Q?",
        "sub_questions": SUB_QUESTIONS,
    }

    result = await graph.ainvoke(Command(resume={"approved": True}), config)
    [report_interrupt] = result["__interrupt__"]
    assert report_interrupt.value["type"] == "approve_report"
    assert fakes.calls["write"] == 1  # one write after all parallel research tasks

    sources = result["sources"]
    assert [s["id"] for s in sources] == ["S1", "S2", "S3"]
    assert sorted(s["sub_question"] for s in sources) == SUB_QUESTIONS

    result = await graph.ainvoke(Command(resume={"approved": False, "feedback": "x"}), config)
    assert result["__interrupt__"][0].value["type"] == "approve_report"
    assert result["revision_loops"] == 1
    assert fakes.calls["write"] == 2

    result = await graph.ainvoke(Command(resume={"approved": True}), config)
    assert "__interrupt__" not in result
    assert result["draft"] == "Answer [S1]."

    report = (tmp_path / "t1.md").read_text()
    assert report.startswith("# Q?\n\nAnswer [S1].\n\n## Sources\n")
    assert "- [S1] [" in report
    assert "## Unresolved gaps" not in report
    assert "- Revision loops: 1" in report


async def test_plan_feedback_loops_back_to_plan(fakes):
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    await graph.ainvoke({"question": "Q?"}, config)
    result = await graph.ainvoke(
        Command(resume={"approved": False, "feedback": "narrower"}), config
    )
    assert result["__interrupt__"][0].value["type"] == "approve_plan"
    assert fakes.calls["Plan"] == 2


async def test_auto_approve_with_gap_reresearch(fakes, tmp_path):
    gap = {"sub_question": "q1", "claim": "c", "source_ids": ["S1"], "reason": "r"}
    fakes.gaps.extend([[gap], []])
    graph = build_graph(MemorySaver())

    result = await graph.ainvoke(
        {"question": "Q?", "auto_approve": True}, {"configurable": {"thread_id": "t3"}}
    )

    assert "__interrupt__" not in result
    assert result["research_loops"] == 1
    assert result["gaps"] == []
    assert fakes.calls["write"] == 2
    assert fakes.calls["SelfCheck"] == 2
    assert len(result["sources"]) == 4  # one new source from the gap task
    assert "- Research loops: 1" in (tmp_path / "t3.md").read_text()


async def test_unresolved_gaps_are_saved(fakes, tmp_path):
    gap = {"sub_question": "q1", "claim": "c", "source_ids": ["S1"], "reason": "r"}
    fakes.gaps.extend([[gap]] * 3)  # still failing after the cap of 2 loops
    graph = build_graph()  # auto_approve never interrupts, so no checkpointer is needed

    await graph.ainvoke({"question": "Q?", "auto_approve": True})

    [path] = tmp_path.glob("report-*.md")
    assert '## Unresolved gaps\n\n- "c" [S1]: r\n' in path.read_text()


def test_gap_tasks_resolve_ids_to_urls():
    sources = [{"id": "S1", "url": "https://a.com"}, {"id": "S2", "url": "https://b.com"}]
    gap = {"sub_question": "q", "claim": "c", "source_ids": ["S2", "S9"], "reason": "r"}
    [send] = research.gap_tasks([gap], sources)
    assert send.arg["cited_urls"] == ["https://b.com"]
