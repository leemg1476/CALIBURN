"""Operator/reviewer CLI; authority is PostgreSQL current_user, never an argument."""

import argparse
import json

from sqlalchemy.exc import SQLAlchemyError

from caliburn.config import get_settings
from caliburn.policy.review import ReviewDenied, ReviewPolicy
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import NotFound, get_store
from caliburn.sandbox.importer import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser(
        "configure-reviewer", help="Operator maps an already provisioned independent DB role"
    )
    configure.add_argument("--db-role", required=True)
    configure.add_argument("--principal", required=True)
    configure.add_argument("--tenant", default="development")
    plan = commands.add_parser(
        "register-plan", help="Register bounded inert test-plan files; never execute"
    )
    plan.add_argument("--workspace", required=True)
    plan.add_argument("--root", required=True)
    plan.add_argument("--file", action="append", required=True, dest="files")
    plan.add_argument("--image-digest", required=True)
    plan.add_argument("--ttl", type=int, default=3600)
    for command in ("inspect", "decide", "revoke"):
        sub = commands.add_parser(command)
        sub.add_argument("--request", required=True)
        if command == "decide":
            sub.add_argument("--binding-sha256", required=True)
            sub.add_argument("--decision", required=True, choices=["APPROVE", "REJECT"])
            sub.add_argument("--ttl", type=int, default=600)
    args = parser.parse_args()
    settings = get_settings()
    secrets = platform_secrets(settings)
    if contains_secret(vars(args), secrets):
        raise ReviewDenied()
    policy = ReviewPolicy(get_store(settings.database_url))
    if args.command == "configure-reviewer":
        policy.configure_reviewer(args.db_role, args.principal, args.tenant)
        result = {"configured": True}
    elif args.command == "register-plan":
        bundle = snapshot(args.root, args.files)
        if contains_secret(bundle.files, secrets):
            raise ReviewDenied()
        result = {
            "plan_ref": policy.register_plan(
                args.workspace, bundle.files, args.image_digest, args.ttl
            )
        }
    elif args.command == "inspect":
        result = policy.inspect(args.request)
    elif args.command == "decide":
        result = {
            "request_ref": policy.decide(args.request, args.binding_sha256, args.decision, args.ttl)
        }
    else:
        policy.revoke(args.request)
        result = {"revoked": True}
    if contains_secret(result, secrets):
        raise ReviewDenied()
    # JSON escapes control sequences in untrusted source; nothing is evaluated/imported.
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except (ReviewDenied, NotFound, ValueError, OSError, SQLAlchemyError):
        raise SystemExit(
            "Review operation denied or unavailable; no credentials/source logged"
        ) from None
