"""Internal pure-JSON releases and typed invocation; never customer clearance."""

import ast
import builtins
import hashlib
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, model_validator

from caliburn.sandbox.contracts import Bundle
from caliburn.tool_factory.artifact_integrity import canonical, key_id
from caliburn.tool_factory.contracts import CapabilityBundle, Contract

DOMAIN = b"CALIBURN\x00INTERNAL_RELEASE\x00ED25519\x00V1\x00"
BUILTINS = {
    "len",
    "sum",
    "min",
    "max",
    "abs",
    "round",
    "sorted",
    "str",
    "int",
    "float",
    "bool",
    "dict",
    "list",
    "tuple",
    "set",
    "range",
    "enumerate",
    "zip",
    "all",
    "any",
    "reversed",
}
NODES = {
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Dict,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.Call,
    ast.keyword,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.USub,
    ast.UAdd,
}


class ReleaseDenied(Exception):
    pass


def profile(payload):
    """Inspect inert AST; candidate source is never evaluated on this host."""
    bundle = CapabilityBundle.model_validate(payload)
    path, _, symbol = bundle.manifest.entrypoint.partition(":")
    if (
        bundle.manifest.kind != "tool"
        or bundle.manifest.permissions
        or bundle.dependency_lock
        or bundle.sbom_components
        or set(bundle.sources) != {path}
        or bundle.declared_license
        not in {"MIT", "BSD-3-Clause", "Apache-2.0", "LicenseRef-Proprietary"}
    ):
        raise ReleaseDenied()
    tree = ast.parse(bundle.sources[path])
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    entry = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == symbol), None
    )
    if (
        entry is None
        or entry.args.posonlyargs
        or {a.arg for a in entry.args.args + entry.args.kwonlyargs}
        != set(bundle.manifest.input_schema["properties"])
        or set(bundle.manifest.input_schema.get("required", []))
        != set(bundle.manifest.input_schema["properties"])
    ):
        raise ReleaseDenied()
    if symbol not in functions or any(
        n.startswith("_") or n in set(dir(builtins)) - BUILTINS for n in functions
    ):
        raise ReleaseDenied()
    for item in tree.body:
        if not isinstance(item, ast.FunctionDef) and not (
            isinstance(item, ast.Expr)
            and isinstance(item.value, ast.Constant)
            and isinstance(item.value.value, str)
        ):
            raise ReleaseDenied()
    for node in ast.walk(tree):
        if type(node) not in NODES:
            raise ReleaseDenied()
        if isinstance(node, ast.Name) and (
            node.id.startswith("_") or node.id in set(dir(builtins)) - BUILTINS
        ):
            raise ReleaseDenied()
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in BUILTINS | functions
        ):
            raise ReleaseDenied()
        if isinstance(node, ast.FunctionDef) and (
            node.decorator_list
            or node.returns is not None
            or node.args.defaults
            or any(x is not None for x in node.args.kw_defaults)
            or node.args.vararg
            or node.args.kwarg
        ):
            raise ReleaseDenied()
        if isinstance(node, ast.arg) and (node.annotation is not None or node.arg.startswith("_")):
            raise ReleaseDenied()
    return {
        "profile": "pure-json-v1",
        "source_sha256": Bundle(files=bundle.sources).digest(),
        "ast_sha256": hashlib.sha256(ast.dump(tree).encode()).hexdigest(),
        "external_dependencies": [],
        "license": bundle.declared_license,
        "clearance_scope": "internal_development",
    }


class ReleaseStatement(Contract):
    format: Literal["caliburn-internal-release-v1"] = "caliburn-internal-release-v1"
    scope: Literal["internal_development"] = "internal_development"
    request_ref: str
    binding_sha256: str
    approval_ref: str
    approval_sha256: str
    artifact_ref: str
    artifact_sha256: str
    actor: str
    tenant: str
    name: str
    version: str
    image_digest: str
    source_sha256: str
    qualification: dict
    manifest: dict
    key_id: str
    issued_at: int
    expires_at: int


def release_sign(statement, private):
    return {
        "algorithm": "Ed25519",
        "statement": statement.model_dump(),
        "signature_hex": private.sign(DOMAIN + canonical(statement)).hex(),
    }


def release_verify(envelope, public, actor, tenant, now):
    try:
        if (
            set(envelope) != {"algorithm", "statement", "signature_hex"}
            or envelope["algorithm"] != "Ed25519"
        ):
            raise ReleaseDenied()
        statement = ReleaseStatement.model_validate(envelope["statement"])
        if (
            statement.actor != actor
            or statement.tenant != tenant
            or statement.key_id != key_id(public)
            or not statement.issued_at <= now < statement.expires_at
        ):
            raise ReleaseDenied()
        Ed25519PublicKey.from_public_bytes(public).verify(
            bytes.fromhex(envelope["signature_hex"]), DOMAIN + canonical(statement)
        )
        return statement
    except Exception as exc:
        raise ReleaseDenied() from exc


class InvocationResult(Contract):
    ok: bool
    release_ref: str
    version: str
    source_sha256: str
    value: dict | None = None
    error: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.ok != (self.value is not None)
            or (self.ok and self.error is not None)
            or (not self.ok and not self.error)
        ):
            raise ValueError("Invalid invocation receipt")
        return self


def release_digest():
    names = ("release_contracts.py", "release_service.py", "release_queue.py", "release_control.py")
    return hashlib.sha256(
        b"".join(Path(__file__).with_name(n).read_bytes() for n in names)
    ).hexdigest()
