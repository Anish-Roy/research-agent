def test_imports():
    import langchain_mcp_adapters  # noqa: F401
    import langgraph.checkpoint.postgres.aio  # noqa: F401

    from research_agent.config import Settings

    assert Settings().tavily_mcp_url.startswith("https://")
