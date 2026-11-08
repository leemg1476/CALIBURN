"""Explicitly opted-in live synthetic model/tool smoke; persistent shared token/call caps."""

import argparse
import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from caliburn.config import get_settings
from caliburn.llm import OpenAICompatibleModel
from caliburn.runtime.contracts import Submit
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.schema import steps
from caliburn.runtime.store import Store
from caliburn.runtime.worker import Worker


class BudgetedModel:
    def __init__(self, settings, path):
        self.model = OpenAICompatibleModel(settings)
        self.settings, self.path = settings, path
        self.state = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {
                "max_calls": 100,
                "max_tokens": 50000,
                "attempts": 0,
                "charged_tokens": 0,
                "actual_tokens": 0,
                "usage": [],
            }
        )
        if self.state["max_calls"] != 100 or self.state["max_tokens"] != 50000:
            raise ValueError("Live budget scope mismatch")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    async def complete(self, messages, tools):
        reserve = (
            len(json.dumps([messages, tools], ensure_ascii=True).encode())
            + 1024
            + self.settings.max_output_tokens
        )
        if self.state["attempts"] >= 100 or self.state["charged_tokens"] + reserve > 50000:
            raise ValueError("Live cumulative token/call budget exhausted")
        if contains_secret([messages, tools], platform_secrets(self.settings)):
            raise ValueError("Credential-bearing model input denied")
        self.state["attempts"] += 1
        self.state["charged_tokens"] += reserve
        self.save()  # failed/interrupted requests keep their conservative reservation
        result = await self.model.complete(messages, tools)
        usage = result.get("usage") or {}
        total = usage.get("total_tokens")
        if type(total) is int and 0 <= total <= reserve:
            self.state["charged_tokens"] -= reserve - total
            self.state["actual_tokens"] += total
            self.state["usage"].append(
                {
                    name: usage.get(name)
                    for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if type(usage.get(name)) is int
                }
            )
            self.save()
        return result


async def run(args):
    os.environ["CALIBURN_API_ENV_FILE"] = args.api_env_file
    os.environ["CALIBURN_PROVIDER"] = "openai_compatible"
    os.environ["CALIBURN_MODEL_CALL_COST"] = "0.01"
    get_settings.cache_clear()
    settings = replace(get_settings(), max_output_tokens=256, task_max_cost=0.06)
    if (
        settings.upstream_base_url != "https://api.openai.com/v1"
        or not settings.upstream_api_key
        or not settings.database_url.startswith("postgresql+psycopg:")
    ):
        raise ValueError("Explicit official OpenAI profile and disposable PostgreSQL required")
    budget = BudgetedModel(settings, Path(".caliburn/live-llm-budget.json"))
    store = Store(settings.database_url)
    try:
        task = store.submit(
            Submit(
                prompt="Use add_numbers to compute 19+23. Then use add_numbers again to add 5 to that tool result. Do not calculate either stage without a tool. After both tool results, answer only the final number.",
                limits={
                    "max_steps": 6,
                    "max_tool_calls": 4,
                    "max_tokens": 50000,
                    "max_cost": 0.06,
                    "timeout_seconds": 180,
                    "call_timeout_seconds": 60,
                },
            )
        )
        await Worker(
            store, budget, output_tokens=256, call_cost=0.01, secrets=platform_secrets(settings)
        ).run_once()
        final = store.get(task["id"])
        with store.engine.connect() as c:
            tool_steps = (
                c.execute(
                    select(steps)
                    .where(steps.c.task_id == task["id"], steps.c.kind == "TOOL")
                    .order_by(steps.c.ordinal)
                )
                .mappings()
                .all()
            )
        sums = [
            json.loads(row["output"]["content"])["sum"]
            for row in tool_steps
            if row["status"] == "COMPLETED" and row["input"]["function"]["name"] == "add_numbers"
        ]
        evidence = {
            "live_model": True,
            "model": settings.upstream_model,
            "api": "chat_completions",
            "reasoning_effort": "none"
            if settings.upstream_model == "gpt-6-luna"
            else "unspecified",
            "task_id": task["id"],
            "state": final["state"],
            "error": final["error"],
            "result": final["result"],
            "model_calls": final["model_calls"],
            "tool_calls": final["tool_calls"],
            "observed_tool_sums": sums,
            "budget": budget.state,
            "commercial_fallback": settings.allow_commercial_fallback,
        }
        if contains_secret(evidence, platform_secrets(settings)):
            raise ValueError("Evidence contains credential material")
        Path("docs/evidence/live-llm-smoke.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    k: evidence[k]
                    for k in (
                        "model",
                        "task_id",
                        "state",
                        "result",
                        "model_calls",
                        "tool_calls",
                        "observed_tool_sums",
                    )
                },
                ensure_ascii=False,
            )
        )
        if (
            final["state"] != "COMPLETED"
            or sums != [42.0, 47.0]
            or "47" not in (final["result"] or "")
        ):
            raise ValueError("Live model/tool smoke did not meet acceptance")
    finally:
        store.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--api-env-file", default=".env.apikey")
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error("Explicit --allow-paid required")
    try:
        asyncio.run(run(args))
    except Exception:  # noqa: BLE001 -- key/URL/provider exceptions never reach diagnostics
        parser.exit(2, "Live smoke failed; inspect sanitized task evidence/budget\n")


if __name__ == "__main__":
    main()
