"""Bounded, deterministic triage. Never imports or executes candidate code."""

import ast
import re

from caliburn.runtime.redaction import contains_secret
from caliburn.tool_factory.contracts import CapabilityBundle, digest


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
    texts = {"manifest": bundle.manifest.description} | bundle.sources | bundle.tests
    for path, source in texts.items():
        if re.search(
            r"ignore\s+(?:all\s+)?(?:previous|prior|system|policy)|approve\s+yourself|bypass\s+(?:approval|policy)",
            source,
            re.IGNORECASE,
        ):
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
