"""Trusted operator release/review/rollback and isolated invocation supervisor."""

import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from caliburn.config import get_settings
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import get_store
from caliburn.sandbox.control import Supervisor
from caliburn.tool_factory.execution_control import FactoryTestExecutor, OracleExecutor
from caliburn.tool_factory.release_contracts import ReleaseDenied
from caliburn.tool_factory.release_queue import InvocationQueue
from caliburn.tool_factory.release_service import ReleaseService


class ReleasedExecutor(OracleExecutor):
    tools = ("registered_tool",)

    def __init__(self, image):
        super().__init__(FactoryTestExecutor(image))

    def bind_guard(self, guard):
        self.guard = guard


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--configure-role")
    p.add_argument("--principal")
    p.add_argument("--kind", choices=["REVIEWER", "EXECUTOR", "SIGNER"])
    p.add_argument("--tenant", default="development")
    p.add_argument("--disable-role")
    p.add_argument("--request-artifact")
    p.add_argument("--inspect")
    p.add_argument("--decide")
    p.add_argument("--binding-sha")
    p.add_argument("--decision", choices=["APPROVE", "REJECT"])
    p.add_argument("--internal-license-approved", action="store_true")
    p.add_argument("--activate")
    p.add_argument("--private-key")
    p.add_argument("--rollback")
    p.add_argument("--revoke")
    p.add_argument("--image")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    store = None
    try:
        settings = get_settings()
        store = get_store(settings.database_url)
        service = ReleaseService(store, secrets=platform_secrets(settings))
        if args.configure_role:
            service.configure(args.configure_role, args.principal, args.kind, args.tenant)
        elif args.disable_role:
            service.disable(args.disable_role, args.kind)
        elif args.request_artifact:
            print(json.dumps({"release_request": service.request(args.request_artifact)}))
        elif args.inspect:
            result = service.inspect(args.inspect)
            if contains_secret(result, platform_secrets(settings)):
                raise ReleaseDenied()
            print(json.dumps(result))
        elif args.decide:
            print(
                json.dumps(
                    {
                        "decision_ref": service.decide(
                            args.decide,
                            args.binding_sha,
                            args.decision,
                            internal_license_approved=args.internal_license_approved,
                        )
                    }
                )
            )
        elif args.activate:
            password = os.getenv("CALIBURN_SIGNING_KEY_PASSWORD", "")
            if not password or not args.private_key:
                raise ReleaseDenied()
            raw = Path(args.private_key).read_bytes()
            if len(raw) > 4096:
                raise ReleaseDenied()
            private = serialization.load_pem_private_key(raw, password=password.encode())
            if not isinstance(private, Ed25519PrivateKey):
                raise ReleaseDenied()
            print(json.dumps({"release_ref": service.activate(args.activate, private)}))
        elif args.rollback:
            service.rollback(args.rollback)
        elif args.revoke:
            service.revoke(args.revoke)
        elif args.image:
            supervisor = Supervisor(
                InvocationQueue(store),
                ReleasedExecutor(args.image),
                secrets=platform_secrets(settings),
            )
            asyncio.run(supervisor.run_once() if args.once else supervisor.serve())
        else:
            raise ReleaseDenied()
    except Exception:  # noqa: BLE001 -- key/credential-bearing exceptions stay redacted
        p.exit(2, "Internal release authority/configuration denied\n")
    finally:
        if store is not None:
            with contextlib.suppress(Exception):
                store.engine.dispose()


if __name__ == "__main__":
    main()
