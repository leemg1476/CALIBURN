import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from caliburn.config import get_settings
from caliburn.runtime.store import get_store
from caliburn.task_store import get_task_store


@pytest.fixture(autouse=True)
def config_for_tests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("CALIBURN_API_ENV_FILE", raising=False)
    monkeypatch.setenv("CALIBURN_API_TOKEN", "test-service-token-secret")
    monkeypatch.setenv("CALIBURN_PROVIDER", "fixture")
    monkeypatch.setenv("CALIBURN_MODEL", "caliburn-agent")
    monkeypatch.setenv("CALIBURN_DB_PATH", str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setenv(
        "CALIBURN_DATABASE_URL", "sqlite+pysqlite:///" + str(tmp_path / "runtime.db")
    )
    monkeypatch.setenv("CALIBURN_MAX_STEPS", "6")
    monkeypatch.setenv("CALIBURN_MODEL_CALL_COST", "0")
    monkeypatch.setenv("CALIBURN_TASK_MAX_COST", "0")
    monkeypatch.setenv("CALIBURN_ALLOW_COMMERCIAL_FALLBACK", "false")
    get_settings.cache_clear()
    get_task_store.cache_clear()
    from caliburn.runtime.schema import metadata
    from caliburn.runtime.store import get_store

    get_store.cache_clear()
    store = get_store(get_settings().database_url)
    metadata.create_all(store.engine)
    yield
    store.engine.dispose()
    get_store.cache_clear()
    get_settings.cache_clear()
    get_task_store.cache_clear()


@pytest.fixture(params=["sqlite", "postgres"])
def durable(request, monkeypatch, tmp_path):
    admin = None
    if request.param == "postgres":
        base = os.getenv("CALIBURN_TEST_DATABASE_URL")
        if not base:
            pytest.skip("Set CALIBURN_TEST_DATABASE_URL for real PostgreSQL tests")
        admin = create_engine(base)
        namespace = "caliburn_test_" + uuid4().hex
        with admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA "{namespace}"'))
        url = make_url(base).update_query_dict({"options": f"-csearch_path={namespace}"})
        url = url.render_as_string(hide_password=False)
    else:
        url = "sqlite+pysqlite:///" + str(tmp_path / "durable.db")
    monkeypatch.setenv("CALIBURN_DATABASE_URL", url)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    store = get_store(url)
    yield store
    store.engine.dispose()
    get_store.cache_clear()
    if admin:
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
        admin.dispose()


@pytest.fixture
def authority(durable):
    from caliburn.policy.review import ReviewPolicy
    from caliburn.runtime.store import Store

    if durable.engine.dialect.name != "postgresql":
        pytest.skip("Independent authority is intentionally PostgreSQL-only")
    name = "review_fixture_" + uuid4().hex
    with durable.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        c.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
    policy = ReviewPolicy(durable)
    policy.configure_reviewer(name, "independent-synthetic-reviewer")
    url = durable.engine.url.update_query_dict({"options": f"-csearch_path={schema} -crole={name}"})
    reviewer = Store(url.render_as_string(hide_password=False))
    yield policy, ReviewPolicy(reviewer), name
    reviewer.engine.dispose()
    # Only this random fixture role's grants in this fixture schema are removed.
    with durable.engine.begin() as c:
        c.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{name}"'))
        c.execute(
            text(
                f'REVOKE UPDATE (state,error,sequence,updated_at,lease_token,lease_owner,lease_until) ON runtime_tasks FROM "{name}"'
            )
        )
        c.execute(text(f'REVOKE UPDATE (outcome,ended_at) ON runtime_runs FROM "{name}"'))
        c.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{name}"'))
        c.execute(text(f'DROP ROLE "{name}"'))


@pytest.fixture
def factory_verifier(durable):
    from caliburn.runtime.store import Store
    from caliburn.tool_factory.checks import VerifierAuthority

    if durable.engine.dialect.name != "postgresql":
        pytest.skip("Independent Factory verifier requires PostgreSQL")
    name = "verify_fixture_" + uuid4().hex
    with durable.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        c.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
    authority = VerifierAuthority(durable)
    authority.configure(name, "synthetic-independent-verifier")
    url = durable.engine.url.update_query_dict({"options": f"-csearch_path={schema} -crole={name}"})
    store = Store(url.render_as_string(hide_password=False))
    yield authority, VerifierAuthority(store), store, name
    store.engine.dispose()
    with durable.engine.begin() as c:
        c.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{name}"'))
        c.execute(
            text(
                f'REVOKE UPDATE (state,attempts,lease_token,lease_until,error) ON factory_check_jobs FROM "{name}"'
            )
        )
        c.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{name}"'))
        c.execute(text(f'DROP ROLE "{name}"'))


@pytest.fixture
def factory_execution_authority(durable, factory_verifier):
    from caliburn.runtime.store import Store
    from caliburn.tool_factory.qualification import Qualification

    names = ["factory_review_fixture_" + uuid4().hex, "factory_runner_fixture_" + uuid4().hex]
    stores = []
    owner = Qualification(durable)
    with durable.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        for name in names:
            c.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
    for name, kind in zip(names, ("REVIEWER", "EXECUTOR")):
        owner.configure(name, "synthetic-" + kind.lower(), kind)
        url = durable.engine.url.update_query_dict(
            {"options": f"-csearch_path={schema} -crole={name}"}
        )
        stores.append(Store(url.render_as_string(hide_password=False)))
    yield owner, Qualification(stores[0]), stores[1], names
    for store in stores:
        store.engine.dispose()
    with durable.engine.begin() as c:
        for name in names:
            c.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{name}"'))
            c.execute(
                text(
                    f'REVOKE UPDATE (state,attempts,lease_token,lease_until,result,result_sha256,executor_role) ON factory_exec_jobs FROM "{name}"'
                )
            )
            c.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{name}"'))
            c.execute(text(f'DROP ROLE "{name}"'))


@pytest.fixture
def artifact_signer(durable, factory_execution_authority):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from caliburn.runtime.store import Store
    from caliburn.tool_factory.registry import ArtifactRegistry

    name = "artifact_sign_fixture_" + uuid4().hex
    with durable.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        c.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
    owner = ArtifactRegistry(durable)
    owner.configure(name, "synthetic-artifact-signer")
    private = Ed25519PrivateKey.generate()
    kid = owner.register_key(private.public_key().public_bytes_raw(), name)
    url = durable.engine.url.update_query_dict({"options": f"-csearch_path={schema} -crole={name}"})
    store = Store(url.render_as_string(hide_password=False))
    yield owner, ArtifactRegistry(store), private, kid, store, name
    store.engine.dispose()
    with durable.engine.begin() as c:
        c.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{name}"'))
        c.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{name}"'))
        c.execute(text(f'DROP ROLE "{name}"'))
