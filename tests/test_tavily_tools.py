import json
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.types import CallToolResult, TextContent

from research_agent.config import settings
from research_agent.tools import tavily
from research_agent.tools.tavily import get_tavily_tools, retry_tavily_errors, tavily_connection


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


def _result(body: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body))])


@pytest.fixture
def handler(monkeypatch):
    """A tool handler that replays `responses` in order, with sleeps skipped."""
    delays: list[float] = []

    async def no_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(tavily.asyncio, "sleep", no_sleep)
    responses: list[CallToolResult] = []

    async def call(request):
        return responses.pop(0)

    return SimpleNamespace(call=call, responses=responses, delays=delays)


REQUEST = SimpleNamespace(name="tavily_search")
RATE_LIMITED = {"error": "Search failed", "status": 429}


async def test_retries_rate_limit_until_success(handler):
    handler.responses[:] = [_result(RATE_LIMITED), _result(RATE_LIMITED), _result({"results": []})]
    result = await retry_tavily_errors(REQUEST, handler.call)
    assert not result.isError
    assert len(handler.delays) == 2
    assert handler.delays[1] > handler.delays[0]  # backs off


async def test_flags_error_after_last_retry(handler):
    handler.responses[:] = [_result(RATE_LIMITED)] * (tavily.MAX_RETRIES + 1)
    result = await retry_tavily_errors(REQUEST, handler.call)
    assert result.isError
    assert len(handler.delays) == tavily.MAX_RETRIES


async def test_does_not_retry_client_errors(handler):
    handler.responses[:] = [_result({"error": "Unauthorized", "status": 401})]
    result = await retry_tavily_errors(REQUEST, handler.call)
    assert result.isError
    assert handler.delays == []


async def test_normal_result_passes_through(handler):
    handler.responses[:] = [_result({"results": []})]
    result = await retry_tavily_errors(REQUEST, handler.call)
    assert not result.isError
    assert handler.delays == []
