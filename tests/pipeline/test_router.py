"""Stage 0: the Offence-Date Router. The transition day itself is the case that matters."""
from datetime import date, datetime

import pytest

from src.pipeline.router import route, route_period

TODAY = date(2026, 9, 27)


@pytest.mark.parametrize("d, era", [
    ("2024-06-30", "ipc"),          # last day of the IPC
    ("2024-07-01", "bns"),          # the BNS binds from this day, inclusive
    ("2024-08-15", "bns"),          # Section 3 worked example
    ("2023-12-03", "ipc"),
    ("1995-01-01", "ipc"),
    (" 2025-02-11 ", "bns"),
    (date(2024, 6, 30), "ipc"),
    (datetime(2024, 7, 1, 0, 30), "bns"),
])
def test_routes_by_offence_date(d, era):
    assert route(d, today=TODAY) == era


@pytest.mark.parametrize("bad", ["", None, "15/08/2024", "08-15-2024", "2024-13-01", "yesterday", 20240815])
def test_unparseable_dates_are_refused_not_guessed(bad):
    with pytest.raises(ValueError):
        route(bad, today=TODAY)


def test_future_offence_date_is_refused():
    with pytest.raises(ValueError, match="future"):
        route("2026-09-28", today=TODAY)


@pytest.mark.parametrize("a, b, eras", [
    ("2024-01-10", "2024-06-30", ["ipc"]),
    ("2024-07-01", "2024-09-10", ["bns"]),
    ("2024-01-10", "2024-09-10", ["ipc", "bns"]),     # cruelty spanning the transition
    ("2024-06-30", "2024-07-01", ["ipc", "bns"]),     # the tightest straddle
])
def test_route_period(a, b, eras):
    assert route_period(a, b, today=TODAY) == eras


def test_backwards_period_is_refused():
    with pytest.raises(ValueError, match="backwards"):
        route_period("2024-09-10", "2024-01-10", today=TODAY)


def test_transition_date_comes_from_env(monkeypatch):
    monkeypatch.setenv("BNS_TRANSITION_DATE", "2024-08-01")
    assert route("2024-07-15", today=TODAY) == "ipc"
    assert route("2024-08-01", today=TODAY) == "bns"


def test_context_size_grows_with_the_prompt():
    from src.pipeline.llm import LLMError, context_size
    short = [{"role": "user", "content": "x" * 3000}]
    long = [{"role": "user", "content": "x" * 30000}]        # ~an LSI fact statement
    assert context_size(short, 1024) == 8192
    assert context_size(long, 1024) == 16384
    with pytest.raises(LLMError):
        context_size([{"role": "user", "content": "x" * 200000}], 1024)
