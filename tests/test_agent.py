import json

import pytest

from caliburn.agent import AgentStepLimitError, run_agent
from caliburn.llm import FixtureModel
from caliburn.tools import ToolError, execute_curated_tool


def test_unknown_tool_denied():
    with pytest.raises(ToolError, match="allowlist"):
        execute_curated_tool("host_shell", json.dumps({"command": "whoami"}))


def test_invalid_arguments_denied():
    with pytest.raises(ToolError, match="Invalid tool arguments"):
        execute_curated_tool("add_numbers", '{"a": 1, "b": 2, "command": "oops"}')


@pytest.mark.asyncio
async def test_step_limit_enforced():
    with pytest.raises(AgentStepLimitError):
        await run_agent(FixtureModel(), [{"role": "user", "content": "sum 2 3"}], 1)


@pytest.mark.asyncio
async def test_safe_fixture_tool_call():
    answer, steps = await run_agent(FixtureModel(), [{"role": "user", "content": "sum 5 7"}], 6)
    assert '"sum": 12.0' in answer
    assert steps == 2


def test_curated_tool_contracts_and_clock_fixture(monkeypatch):
    from datetime import UTC, datetime

    from caliburn import tools

    class FixedClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 8, tzinfo=UTC)

    monkeypatch.setattr(tools, "datetime", FixedClock)
    assert tools.execute_curated_tool("utc_now", "{}") == {"utc": "2026-11-08T00:00:00+00:00"}
    assert tools.execute_curated_tool("add_numbers", '{"a":2,"b":3}') == {"sum": 5.0}
    for contract in tools.TOOL_CONTRACTS.values():
        assert contract["owner"] and contract["version"] == "1.0.0"
        assert contract["permissions"] == [] and contract["egress"] == []
        assert contract["output_schema"]["type"] == "object"


@pytest.mark.asyncio
async def test_legacy_loop_does_not_reinject_platform_secret():
    from caliburn.agent import AgentProtocolError

    class LeakingModel:
        async def complete(self, messages, tools):
            return {"choices": [{"message": {"role": "assistant", "content": "guard-sentinel"}}]}

    with pytest.raises(AgentProtocolError, match="forbidden credential"):
        await run_agent(
            LeakingModel(), [{"role": "user", "content": "hello"}], 3, ("guard-sentinel",)
        )
