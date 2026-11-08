"""Operator-only Factory reviewed-test supervisor. Never imported by runtime agents."""

import argparse
import asyncio
import contextlib
import hashlib
import json
from pathlib import Path

from caliburn.config import get_settings
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import get_store
from caliburn.sandbox.contracts import Bundle, Result, TestRun
from caliburn.sandbox.control import DockerExecutor, SandboxFailure, Supervisor
from caliburn.tool_factory.execution_queue import ExecutionQueue
from caliburn.tool_factory.oracle import (
    PLAN_FILE,
    OracleProof,
    parse_json,
    plan_digest,
    read_plan,
    same,
)
from caliburn.tool_factory.qualification import Qualification
from caliburn.tool_factory.service import FactoryDenied


class OracleExecutor(DockerExecutor):
    """Observe one input in one fresh container; host retains expected result."""

    def __init__(self, parent):
        super().__init__(parent.image, timeout=5)
        self.guard = parent.guard
        self.pending_creates = parent.pending_creates

    async def before_dispatch(self, job):
        if self.guard is None or not await self.guard(job):
            raise SandboxFailure("factory_execution_denied")

    def command(self, name, *, expires_at=None):
        args = super().command(name, expires_at=expires_at)
        args[-1] = "/opt/invoke_runner.py"
        return args

    def payload(self, job):
        return json.dumps(
            {
                "files": job["source_files"],
                "source_sha256": job["binding"]["source_sha256"],
                "entrypoint": job["oracle_entrypoint"],
                "input": job["oracle_input"],
            },
            ensure_ascii=True,
            allow_nan=False,
        ).encode()

    def validate(self, job, raw):
        observed = parse_json(raw)
        if not isinstance(observed, dict) or set(observed) != {"value"}:
            raise SandboxFailure("invalid_oracle_observation")
        return Result(ok=True, data=observed)


class FactoryTestExecutor(DockerExecutor):
    tools = ("capability_execute_tests",)

    def __init__(self, image_digest, *, timeout=20):
        super().__init__(image_digest, timeout=timeout)
        self.guard = None

    def bind_guard(self, guard):
        self.guard = guard

    async def execute(self, job):
        try:
            async with asyncio.timeout(self.timeout):
                result = await super().execute(job)
                if not result.ok or result.data["status"] != "PASSED":
                    return result
                plan = read_plan(job["plan_files"])
                fingerprint = plan_digest(plan)
                if fingerprint != job["binding"]["oracle_sha256"]:
                    raise SandboxFailure("oracle_plan_mismatch")
                checked = 0
                oracle = OracleExecutor(self)
                for case in plan.cases:
                    # Never send the plan, tests, expected value or pass bit to the subject.
                    observed = await oracle.execute(
                        job | {"oracle_entrypoint": plan.entrypoint, "oracle_input": case.input}
                    )
                    if not observed.ok or not same(observed.data["value"], case.expected):
                        break
                    checked += 1
                status = "PASSED" if checked == len(plan.cases) else "FAILED"
                result.isolation["host_oracle"] = OracleProof(
                    plan_sha256=fingerprint, total=len(plan.cases), checked=checked, status=status
                ).model_dump()
                if status == "FAILED":
                    # Preserve the actual child exit; never invent a failing exit code.
                    result.isolation["untrusted_test_run"] = result.data
                    return Result(
                        ok=False, error="factory_oracle_failed", isolation=result.isolation
                    )
                return result
        except TimeoutError:
            return Result(ok=False, error="factory_oracle_timeout")
        except (KeyError, ValueError, SandboxFailure):
            return Result(ok=False, error="factory_oracle_denied")

    async def before_dispatch(self, job):
        if self.guard is None or not await self.guard(job):
            raise SandboxFailure("factory_execution_denied")

    def command(self, name, *, expires_at=None):
        args = super().command(name, expires_at=expires_at)
        args[-1] = "/opt/test_runner.py"
        return args

    def payload(self, job):
        return json.dumps(
            {
                "files": job["source_files"],
                "source_sha256": job["binding"]["source_sha256"],
                "plan": {k: v for k, v in job["plan_files"].items() if k != PLAN_FILE},
                "plan_sha256": job["binding"]["child_plan_sha256"],
            },
            ensure_ascii=False,
        ).encode()

    def validate(self, job, raw):
        result = Result.model_validate_json(raw)
        root = Path(__file__).parent.parent / "sandbox"
        expected = hashlib.sha256(
            b"".join(
                (root / name).read_bytes()
                for name in ("test_runner.py", "runner.py", "test_check.py")
            )
        ).hexdigest()
        if result.isolation.get("runner_sha256") != expected:
            raise SandboxFailure("factory_runner_revision_mismatch")
        if result.ok:
            proof = TestRun.model_validate(result.data)
            if (
                proof.source_sha256 != job["binding"]["source_sha256"]
                or proof.plan_sha256 != job["binding"]["child_plan_sha256"]
            ):
                raise SandboxFailure("factory_test_artifact_mismatch")
            # Actual child bytes/exit remain available separately. The aggregate
            # execution record names the full reviewed host+child plan.
            result.isolation["child_test_run"] = proof.model_dump()
            result.data = proof.model_copy(
                update={"plan_sha256": job["binding"]["plan_sha256"]}
            ).model_dump()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--configure-role")
    parser.add_argument("--principal")
    parser.add_argument("--kind", choices=["REVIEWER", "EXECUTOR"])
    parser.add_argument("--tenant", default="development")
    parser.add_argument("--plan-bundle")
    parser.add_argument("--static-report")
    parser.add_argument("--independent-tests")
    parser.add_argument(
        "--oracle-cases", help="Operator-owned JSON input/expected vectors; host-only comparison"
    )
    parser.add_argument("--inspect")
    parser.add_argument("--decide")
    parser.add_argument("--binding-sha")
    parser.add_argument("--decision", choices=["APPROVE", "REJECT"])
    parser.add_argument("--revoke")
    parser.add_argument("--disable-role")
    args = parser.parse_args()
    store = None
    try:
        settings = get_settings()
        store = get_store(settings.database_url)
        policy = Qualification(store)
        if args.configure_role:
            if not args.principal or not args.kind:
                parser.error("--principal and --kind required")
            policy.configure(args.configure_role, args.principal, args.kind, args.tenant)
        elif args.disable_role:
            policy.disable(args.disable_role)
        elif args.plan_bundle:
            if not all((args.static_report, args.independent_tests, args.image)):
                parser.error("report, independent test JSON and immutable image required")
            files = Bundle(
                files=json.loads(Path(args.independent_tests).read_text(encoding="utf-8"))
            )
            if contains_secret(files.model_dump(), platform_secrets(settings)):
                raise FactoryDenied()
            cases = (
                json.loads(Path(args.oracle_cases).read_text(encoding="utf-8"))
                if args.oracle_cases
                else None
            )
            if contains_secret(cases, platform_secrets(settings)):
                raise FactoryDenied()
            print(
                json.dumps(
                    {
                        "plan_ref": policy.register_plan(
                            args.plan_bundle,
                            args.static_report,
                            files,
                            args.image,
                            oracle_cases=cases,
                        )
                    }
                )
            )
        elif args.inspect:
            result = policy.inspect(args.inspect)
            if contains_secret(result, platform_secrets(settings)):
                raise FactoryDenied()
            print(json.dumps(result, ensure_ascii=False))
        elif args.decide:
            if not args.binding_sha or not args.decision:
                parser.error("binding SHA and decision required")
            policy.decide(args.decide, args.binding_sha, args.decision)
        elif args.revoke:
            policy.revoke(args.revoke)
        else:
            if not args.image:
                parser.error("immutable --image required")
            executor = FactoryTestExecutor(args.image)
            supervisor = Supervisor(
                ExecutionQueue(store), executor, secrets=platform_secrets(settings)
            )
            asyncio.run(supervisor.run_once() if args.once else supervisor.serve())
    except Exception:  # noqa: BLE001 -- no source/credential-bearing diagnostics
        parser.exit(2, "Factory execution authority/configuration denied\n")
    finally:
        if store is not None:
            with contextlib.suppress(Exception):
                store.engine.dispose()


if __name__ == "__main__":
    main()
