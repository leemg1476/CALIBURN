"""Separate static verifier process; needs an independently configured DB role."""

import argparse
import asyncio
import contextlib

from caliburn.config import get_settings
from caliburn.runtime.redaction import platform_secrets
from caliburn.runtime.store import get_store
from caliburn.tool_factory.checks import VerifierAuthority
from caliburn.tool_factory.contracts import CHECKER_DIGEST
from caliburn.tool_factory.service import FactoryDenied
from caliburn.tool_factory.static_check import analyze


class StaticVerifier:
    def __init__(self, store, *, secrets=()):
        self.authority, self.secrets = VerifierAuthority(store), secrets

    async def run_once(self):
        job = await asyncio.to_thread(self.authority.claim)
        if job is None:
            return False
        async with asyncio.timeout(5):
            body = await asyncio.to_thread(analyze, job["payload"], CHECKER_DIGEST, self.secrets)
        await asyncio.to_thread(self.authority.finish, job["id"], job["lease_token"], body)
        return True

    async def serve(self):
        while True:
            try:
                if not await self.run_once():
                    await asyncio.sleep(0.25)
            except Exception:  # noqa: BLE001 -- no DSNs/source in diagnostics
                await asyncio.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--configure-role")
    parser.add_argument("--principal")
    parser.add_argument("--tenant", default="development")
    parser.add_argument("--disable-role")
    args = parser.parse_args()
    store = None
    try:
        settings = get_settings()
        store = get_store(settings.database_url)
        authority = VerifierAuthority(store)
        if args.configure_role:
            if not args.principal:
                parser.error("--principal is required")
            authority.configure(args.configure_role, args.principal, args.tenant)
        elif args.disable_role:
            authority.disable(args.disable_role)
        else:
            verifier = StaticVerifier(store, secrets=platform_secrets(settings))
            asyncio.run(verifier.run_once() if args.once else verifier.serve())
    except FactoryDenied:
        parser.exit(2, "Independent configured verifier authority required\n")
    except Exception:  # noqa: BLE001 -- sanitize source/DB diagnostic boundary
        parser.exit(2, "Static verifier failed; no candidate executed\n")
    finally:
        if store is not None:
            with contextlib.suppress(Exception):
                store.engine.dispose()


if __name__ == "__main__":
    main()
