# research-agent

A LangGraph research agent: it plans sub-questions, researches them in parallel through Tavily's hosted MCP server, writes a cited report, and pauses for human approval of the plan and the draft. Runs are checkpointed in Postgres so they can be paused, resumed, and survive crashes. See [PROJECT.md](PROJECT.md) for the design.

## Setup

```bash
uv sync
cp .env.example .env   # then fill in keys and model names
docker compose up -d postgres
uv run pytest
```
