"""Citation parsing shared by `write` and `check_citations`.

Citations look like [S1]. Models also write [S1, S3] or [S1][S3]; both are accepted.
A bracket group counts as a citation only if every token in it is an ID, so markdown
links like [docs](url) are ignored.
"""

import re

from research_agent.state import Source

_BRACKETS = re.compile(r"\[([^\[\]]+)\]")
_ID = re.compile(r"S\d+")


def cited_ids(draft: str) -> list[str]:
    """IDs cited in the draft, in order of first appearance."""
    ids: dict[str, None] = {}
    for group in _BRACKETS.findall(draft):
        tokens = [t for t in re.split(r"[,;\s]+", group) if t]
        if tokens and all(_ID.fullmatch(t) for t in tokens):
            ids.update(dict.fromkeys(tokens))
    return list(ids)


def broken_ids(draft: str, sources: list[Source]) -> list[str]:
    """Cited IDs that don't match any source."""
    known = {s["id"] for s in sources}
    return [i for i in cited_ids(draft) if i not in known]


def format_sources(sources: list[Source]) -> str:
    """Sources as prompt text: a `[S1] title (url)` header, then the trimmed text."""
    return "\n\n".join(f"[{s['id']}] {s['title']} ({s['url']})\n{s['content']}" for s in sources)
