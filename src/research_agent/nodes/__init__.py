"""Graph nodes.

plan, approve_plan, research_one, write, check_citations, self_check, approve_report, save_report.
Nodes that pick the next step return a `Command`; the rest are followed by static edges.
"""

from research_agent.nodes.planning import approve_plan, plan
from research_agent.nodes.research import research_one
from research_agent.nodes.review import approve_report, save_report, self_check
from research_agent.nodes.writing import check_citations, write

__all__ = [
    "approve_plan",
    "approve_report",
    "check_citations",
    "plan",
    "research_one",
    "save_report",
    "self_check",
    "write",
]
