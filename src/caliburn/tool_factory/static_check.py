"""Bounded, deterministic triage. Never imports or executes candidate code."""

import ast
import re
import unicodedata

from caliburn.runtime.redaction import contains_secret
from caliburn.tool_factory.contracts import CapabilityBundle, digest


def instruction_override(text):
    normalized = "".join(
        c for c in unicodedata.normalize("NFKC", text).casefold() if unicodedata.category(c) != "Cf"
    )
    return (
        re.search(
            r"ignore\s+(?:all\s+)?(?:previous|prior|system|policy)|approve\s+yourself|bypass\s+(?:approval|policy)|"
            r"(?:이전|상위|시스템|보안|승인)(?:\s*(?:지시|명령|규칙|정책|절차))?\s*(?:을|를)?\s*(?:무시|우회|해제)|"
            r"(?:스스로|자체적으로)\s*승인",
            normalized,
        )
        is not None
    )


def manifest_texts(value, path="manifest"):
    if isinstance(value, str):
        yield path[:250], value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from manifest_texts(child, path + "." + key)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from manifest_texts(child, path + f"[{i}]")


def analyze(payload, checker_sha256, secrets=()):
    bundle = CapabilityBundle.model_validate(payload)
    findings = []

    def finding(code, path="manifest", line=0):
        if contains_secret(path, secrets):
            path = "redacted"
        item = {"code": code, "path": path, "line": line}
        if item not in findings and len(findings) < 129:
            findings.append(item)

    if contains_secret(payload, secrets):
        finding("configured_secret")
    if bundle.manifest.permissions:
        finding("permission_review_required")
    if bundle.dependency_lock:
        finding("dependency_audit_required")
    # Keep namespaces separate: a source file named 'manifest' cannot shadow metadata.
    for path, text in manifest_texts(bundle.manifest.model_dump()):
        if instruction_override(text):
            finding("instruction_override_pattern", path)
    texts = bundle.sources | bundle.tests
    for path, source in texts.items():
        if instruction_override(source):
            finding("instruction_override_pattern", path)
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            finding("invalid_python_syntax", path)
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                roots = (
                    [alias.name.split(".")[0] for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [(node.module or "").split(".")[0]]
                )
                if any(
                    root
                    in {
                        "os",
                        "subprocess",
                        "socket",
                        "urllib",
                        "http",
                        "requests",
                        "ctypes",
                        "importlib",
                        "pickle",
                        "marshal",
                        "multiprocessing",
                    }
                    for root in roots
                ):
                    finding("sensitive_import", path, node.lineno)
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if name in {
                    "exec",
                    "eval",
                    "compile",
                    "__import__",
                    "system",
                    "popen",
                    "spawn",
                    "connect",
                    "urlopen",
                    "loads",
                    "open",
                    "write_text",
                    "write_bytes",
                }:
                    finding("dynamic_or_io_call", path, node.lineno)
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                finding("dunder_introspection", path, node.lineno)
    blocked = {
        "configured_secret",
        "invalid_python_syntax",
        "instruction_override_pattern",
        "sensitive_import",
        "dynamic_or_io_call",
        "dunder_introspection",
    }
    return {
        "bundle_sha256": digest(payload),
        "checker_sha256": checker_sha256,
        "classification": "BLOCKED"
        if any(item["code"] in blocked for item in findings)
        else "REVIEW_REQUIRED",
        "source_executed": False,
        "activation_eligible": False,
        "execution": "NOT_RUN",
        "security": "INCOMPLETE",
        "dependencies": "UNVERIFIED",
        "license": "UNREVIEWED",
        "findings": findings[:128],
        "truncated": len(findings) > 128,
    }
