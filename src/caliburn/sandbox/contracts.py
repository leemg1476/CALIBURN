"""Bounded contracts used by the API/runtime and isolated read/patch runner."""

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_FILES = 128
MAX_FILE_BYTES = 65536
MAX_BUNDLE_BYTES = 1048576


DENIED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".ssh",
    ".aws",
    ".kube",
    ".docker",
    ".caliburn",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
    "id_rsa",
    "id_ed25519",
}


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 240
        or path.is_absolute()
        or str(path) != value
        or any(
            part in {".", ".."}
            or part.endswith((" ", "."))
            or part.casefold() in DENIED_PARTS
            or part.casefold().startswith(".env")
            for part in path.parts
        )
        or any(ch in value for ch in ("\\", ":", "\x00"))
        or any(ord(ch) < 32 for ch in value)
    ):
        raise ValueError("Invalid workspace path")
    return value


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Bundle(Contract):
    files: dict[str, str] = Field(min_length=1, max_length=MAX_FILES)

    @field_validator("files")
    @classmethod
    def validate_files(cls, value):
        total = 0
        folded = set()
        for name, content in value.items():
            safe_path(name)
            if name.casefold() in folded:
                raise ValueError("Case-colliding workspace path")
            folded.add(name.casefold())
            size = len(content.encode("utf-8"))
            if size > MAX_FILE_BYTES or "\x00" in content:
                raise ValueError("Workspace file exceeds text-file limits")
            total += size
        names = set(value)
        if any(str(parent) in names for name in names for parent in PurePosixPath(name).parents):
            raise ValueError("File/directory collision")
        if len(json.dumps(value, ensure_ascii=False).encode()) > 1500000:
            raise ValueError("Workspace exceeds wire limit")
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Workspace exceeds bundle limit")
        return value

    def digest(self):
        return hashlib.sha256(
            json.dumps(
                self.files, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()


class ListArgs(Contract):
    pass


class ReadArgs(Contract):
    path: str
    start_line: int = Field(default=1, ge=1, le=100000)
    max_lines: int = Field(default=100, ge=1, le=200)
    _path = field_validator("path")(safe_path)


class SearchArgs(Contract):
    text: str = Field(min_length=1, max_length=200)
    max_matches: int = Field(default=50, ge=1, le=100)


class PatchArgs(Contract):
    parent_candidate_ref: str | None = Field(default=None, min_length=36, max_length=36)
    path: str
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    old: str = Field(min_length=1, max_length=16384)
    new: str = Field(max_length=16384)
    _path = field_validator("path")(safe_path)


class TestArgs(Contract):
    request_ref: str = Field(min_length=36, max_length=36)


class GitArgs(Contract):
    candidate_ref: str | None = Field(default=None, min_length=36, max_length=36)


ARGUMENTS = {
    "repo_list": ListArgs,
    "repo_read": ReadArgs,
    "repo_search": SearchArgs,
    "repo_patch": PatchArgs,
    "repo_test": TestArgs,
    "repo_git_status": GitArgs,
}
PERMISSIONS = {
    "repo_list": "read",
    "repo_read": "read",
    "repo_search": "read",
    "repo_patch": "propose_patch",
    "repo_test": "execute_reviewed_tests",
    "repo_git_status": "git_inspect",
}


class Operation(Contract):
    tool: Literal[
        "repo_list", "repo_read", "repo_search", "repo_patch", "repo_test", "repo_git_status"
    ]
    arguments: dict

    @model_validator(mode="after")
    def validate_args(self):
        self.arguments = ARGUMENTS[self.tool].model_validate(self.arguments).model_dump()
        return self


class Result(Contract):
    ok: bool
    data: dict = Field(default_factory=dict)
    error: str | None = None
    isolation: dict = Field(default_factory=dict)
    candidate_ref: str | None = None

    @model_validator(mode="after")
    def bounded(self):
        if len(self.model_dump_json().encode()) > 131072:
            raise ValueError("Runner result exceeds limit")
        return self


WORKSPACE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + Path(__file__).with_name("runner.py").read_bytes()
    + Path(__file__).with_name("test_runner.py").read_bytes()
    + Path(__file__).with_name("test_check.py").read_bytes()
    + Path(__file__).with_name("test_control.py").read_bytes()
    + Path(__file__).with_name("control.py").read_bytes()
    + Path(__file__).with_name("queue.py").read_bytes()
    + Path(__file__).with_name("git_workspace.py").read_bytes()
    + Path(__file__).with_name("git_runner.py").read_bytes()
    + Path(__file__).with_name("git_control.py").read_bytes()
).hexdigest()


def definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": {
                    "repo_list": "List granted repository snapshot files",
                    "repo_read": "Read bounded lines from granted snapshot",
                    "repo_search": "Find literal text in granted snapshot",
                    "repo_patch": "Propose an inert patch from original snapshot or same-task parent_candidate_ref; every changed candidate needs a new independent review",
                    "repo_test": "Run only independently reviewed exact candidate/test-plan hashes in isolated containers; requires explicit execution grant",
                    "repo_git_status": "Inspect a scoped Git baseline checkout and staged candidate diff in a fixed isolated image; no source execution or remote operations",
                }[name],
                "parameters": cls.model_json_schema(),
            },
        }
        for name, cls in ARGUMENTS.items()
    ]


class FileView(Contract):
    path: str
    bytes: int = Field(ge=0, le=MAX_FILE_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    _path = field_validator("path")(safe_path)


class ListData(Contract):
    files: list[FileView] = Field(max_length=MAX_FILES)
    bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReadData(Contract):
    path: str
    content: str = Field(max_length=16384)
    truncated: bool
    start_line: int = Field(ge=1, le=100000)
    total_lines: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    _path = field_validator("path")(safe_path)


class Match(Contract):
    path: str
    line: int = Field(ge=1)
    text: str = Field(max_length=512)
    _path = field_validator("path")(safe_path)


class SearchData(Contract):
    matches: list[Match] = Field(max_length=100)
    limit_reached: bool


class PatchData(Contract):
    path: str
    base_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate: str = Field(max_length=MAX_FILE_BYTES)
    diff: str
    executable: Literal[False]
    approved: Literal[False]
    _path = field_validator("path")(safe_path)


class TestRun(Contract):
    status: Literal["PASSED", "FAILED", "TIMEOUT", "OUTPUT_LIMIT"]
    exit_code: int
    output: str = Field(max_length=16384)
    truncated: bool
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistent_outcome(self):
        if (self.status == "PASSED") != (self.exit_code == 0) or (
            self.status == "OUTPUT_LIMIT"
        ) != self.truncated:
            raise ValueError("Inconsistent test process evidence")
        return self


class TestData(Contract):
    request_ref: str = Field(min_length=36, max_length=36)
    binding_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    image_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    baseline: TestRun
    candidate: TestRun
    source_executed: Literal[True]
    production_approved: Literal[False]


class GitData(Contract):
    mode: Literal["scoped_snapshot_reconstruction"]
    baseline_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseline_git_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    baseline_tree: str = Field(pattern=r"^[a-f0-9]{40}$")
    candidate_tree: str = Field(pattern=r"^[a-f0-9]{40}$")
    git_version: str = Field(max_length=100)
    changed_files: list[str] = Field(max_length=128)
    diff: str = Field(max_length=16384)
    diff_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    diff_truncated: bool
    source_executed: Literal[False]

    @field_validator("changed_files")
    @classmethod
    def safe_names(cls, names):
        return [safe_path(name) for name in names]


OUTPUTS = {
    "repo_list": ListData,
    "repo_read": ReadData,
    "repo_search": SearchData,
    "repo_patch": PatchData,
    "repo_test": TestData,
    "repo_git_status": GitData,
}
TOOL_MANIFESTS = {
    name: {
        "version": "1.0.0",
        "owner": "caliburn-maintainers",
        "digest": WORKSPACE_DIGEST,
        "input_schema": ARGUMENTS[name].model_json_schema(),
        "output_schema": OUTPUTS[name].model_json_schema(),
        "permissions": [PERMISSIONS[name]],
        "network": [],
        "secret_scopes": [],
        "timeout_seconds": 40 if name == "repo_test" else 20,
        "failure_modes": [
            "workspace_denied",
            "invalid_arguments",
            "sandbox_timeout",
            "output_limit",
        ],
        "side_effects": "ephemeral_reviewed_test_execution"
        if name == "repo_test"
        else "inert_candidate_only"
        if name == "repo_patch"
        else "none",
    }
    for name in ARGUMENTS
}


def validate_result(operation: Operation, result: Result) -> Result:
    if result.ok:
        result.data = OUTPUTS[operation.tool].model_validate(result.data).model_dump()
    return result
