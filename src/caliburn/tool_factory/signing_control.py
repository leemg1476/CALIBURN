"""Operator signer CLI. Private material is never sent to API/runtime/source/traces."""

import argparse
import contextlib
import json
import os
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from caliburn.config import get_settings
from caliburn.runtime.redaction import platform_secrets
from caliburn.runtime.store import get_store
from caliburn.tool_factory.artifact_integrity import ArtifactDenied, admission, parse, verify
from caliburn.tool_factory.registry import ArtifactRegistry


def public_key(path):
    raw = Path(path).read_bytes()
    if len(raw) > 4096:
        raise ArtifactDenied()
    key = serialization.load_pem_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise ArtifactDenied()
    return key.public_bytes_raw()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure-role")
    parser.add_argument("--principal")
    parser.add_argument("--tenant", default="development")
    parser.add_argument("--actor", default="development-service")
    parser.add_argument("--disable-role")
    parser.add_argument("--register-key")
    parser.add_argument("--signer-role")
    parser.add_argument("--revoke-key")
    parser.add_argument("--publish-job")
    parser.add_argument("--private-key")
    parser.add_argument("--export")
    parser.add_argument("--import-envelope")
    parser.add_argument("--verify-envelope")
    parser.add_argument("--trusted-public-key")
    args = parser.parse_args()
    store = None
    try:
        if args.verify_envelope:
            if not args.trusted_public_key:
                parser.error("--trusted-public-key required")
            envelope = parse(Path(args.verify_envelope).read_bytes())
            valid = verify(
                envelope.model_dump(),
                public_key(args.trusted_public_key),
                actor=args.actor,
                tenant=args.tenant,
                now=time.time(),
            )
            print(
                json.dumps(
                    {"statement_sha256": valid.statement_sha256, "admission": admission(valid)}
                )
            )
            return
        settings = get_settings()
        store = get_store(settings.database_url)
        password = os.getenv("CALIBURN_SIGNING_KEY_PASSWORD", "")
        registry = ArtifactRegistry(
            store, secrets=platform_secrets(settings) + ((password,) if password else ())
        )
        if args.configure_role:
            if not args.principal:
                parser.error("--principal required")
            registry.configure(args.configure_role, args.principal, args.tenant)
        elif args.disable_role:
            registry.disable(args.disable_role)
        elif args.register_key:
            if not args.signer_role:
                parser.error("--signer-role required")
            print(
                json.dumps(
                    {
                        "key_id": registry.register_key(
                            public_key(args.register_key), args.signer_role
                        )
                    }
                )
            )
        elif args.revoke_key:
            registry.revoke_key(args.revoke_key)
        elif args.publish_job:
            if not args.private_key or not password:
                parser.error("encrypted --private-key and CALIBURN_SIGNING_KEY_PASSWORD required")
            raw = Path(args.private_key).read_bytes()
            if len(raw) > 4096:
                raise ArtifactDenied()
            private = serialization.load_pem_private_key(raw, password=password.encode())
            if not isinstance(private, Ed25519PrivateKey):
                raise ArtifactDenied()
            print(json.dumps({"artifact_ref": registry.publish(args.publish_job, private)}))
        elif args.import_envelope:
            print(
                json.dumps(
                    {
                        "artifact_ref": registry.import_envelope(
                            parse(Path(args.import_envelope).read_bytes())
                        )
                    }
                )
            )
        elif args.export:
            print(
                json.dumps(
                    registry.read(args.export, args.actor, args.tenant)["envelope"],
                    ensure_ascii=False,
                )
            )
        else:
            parser.error("an explicit operator action required")
    except Exception:  # noqa: BLE001 -- sanitize secret-bearing key/DSN/parser exceptions
        parser.exit(2, "Artifact signing/verification denied\n")
    finally:
        if store is not None:
            with contextlib.suppress(Exception):
                store.engine.dispose()


if __name__ == "__main__":
    main()
