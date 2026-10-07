"""Split a report into cited claims: the unit `citation_support` scores and you label.

A claim is one sentence or bullet that cites at least one source. Extraction is plain
code, so the same draft always yields the same claims and labels line up with verdicts.
"""

import re
from typing import TypedDict

from research_agent.citations import cited_ids

# Sentence ends: ., !, or ? followed by whitespace, unless the next thing is a citation.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?!\[S\d)")
_ONLY_CITATIONS = re.compile(r"^(\s*\[[^\[\]]+\]\s*[.,;]?)+$")


class Claim(TypedDict):
    text: str
    source_ids: list[str]


def _units(draft: str) -> list[str]:
    """Sentences and bullets, skipping headings and blank lines."""
    units: list[str] = []
    for line in draft.splitlines():
        line = line.strip().lstrip("-*0123456789. ").strip()
        if not line or line.startswith("#"):
            continue
        for sentence in _SENTENCE_END.split(line):
            sentence = sentence.strip()
            # A citation split off on its own belongs to the sentence before it.
            if units and _ONLY_CITATIONS.match(sentence):
                units[-1] = f"{units[-1]} {sentence}"
            elif sentence:
                units.append(sentence)
    return units


def cited_claims(draft: str) -> list[Claim]:
    return [Claim(text=u, source_ids=ids) for u in _units(draft) if (ids := cited_ids(u))]
