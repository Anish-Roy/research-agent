import pytest
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from research_agent.config import settings
from research_agent.tools.tavily import get_tavily_tools, tavily_connection


def _fake_tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(func=lambda query: query, name=name, description=name)


@pytest.fixture
def fake_key(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "test-key")


@pytest.fixture
def fake_server(monkeypatch, fake_key):
    async def get_tools(self, *, server_name=None):
        return [_fake_tool(n) for n in ("tavily_search", "tavily_extract", "tavily_crawl")]

    monkeypatch.setattr(MultiServerMCPClient, "get_tools", get_tools)


def test_connection_sends_key_in_header_not_url(fake_key):
    conn = tavily_connection()
    assert conn["headers"]["Authorization"] == "Bearer test-key"
    assert "test-key" not in conn["url"]


def test_connection_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "")
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        tavily_connection()


async def test_filters_to_search_and_extract(fake_server):
    tools = await get_tavily_tools()
    assert sorted(t.name for t in tools) == ["tavily_extract", "tavily_search"]


@pytest.mark.integration
@pytest.mark.skipif(not settings.tavily_api_key, reason="TAVILY_API_KEY not set")
async def test_real_search():
    tools = {t.name.replace("-", "_"): t for t in await get_tavily_tools()}
    result = await tools["tavily_search"].ainvoke({"query": "LangGraph"})
    assert result
