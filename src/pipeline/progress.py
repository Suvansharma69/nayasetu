r"""Stage reporting for a running analysis, for the web interface's live progress.

`mark(stage)` is a no-op unless a listener is installed with `listening(fn)`.
The API runs one analysis at a time (the GPU handoff, src/api/main.py), so a
single module-level listener is enough. Nodes 3 and 5 run in parallel and both
mark; the listener just records each stage as it starts.
"""
from __future__ import annotations

from contextlib import contextmanager

STAGES = {
    "intake": "Checking whether this is a court order or FIR",
    "route": "Choosing the code from the offence date",
    "retrieve": "Searching statutes and judgments",
    "statute_identifier": "Proposing sections (local model)",
    "verifier": "Verifying every citation against the citation graph",
    "applicability": "Checking each section against the facts",
    "precedents": "Matching precedent judgments",
    "analytics": "Aggregating outcomes",
    "defense": "Drafting counter-arguments",
}

_listener = None


def mark(stage):
    if _listener is not None:
        _listener(stage)


@contextmanager
def listening(fn):
    global _listener
    prev, _listener = _listener, fn
    try:
        yield
    finally:
        _listener = prev


def staged(name, fn):
    """Wrap a graph node so it reports `name` when it starts."""
    def node(state):
        mark(name)
        return fn(state)
    node.__name__ = name
    return node
