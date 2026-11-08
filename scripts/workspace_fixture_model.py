"""Scripted inference fixture: real source inspection/patch data, never code execution."""

import json


class WorkspaceFixtureModel:
    async def complete(self, messages, tools):
        observations = [m for m in messages if m["role"] == "tool"]
        count = len(observations)
        if count == 0:
            name, args = "repo_list", {}
        elif count == 1:
            name, args = "repo_search", {"text": "return"}
        elif count == 2:
            name, args = "repo_read", {"path": "calc.py"}
        elif count == 3:
            observed = json.loads(observations[-1]["content"])["data"]
            name, args = (
                "repo_patch",
                {
                    "path": "calc.py",
                    "expected_sha256": observed["sha256"],
                    "old": "a - b",
                    "new": "a + b",
                },
            )
        else:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Candidate diff is ready for independent review. No repository code was executed."
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "workspace-fixture-" + str(count),
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                        ],
                    }
                }
            ]
        }
