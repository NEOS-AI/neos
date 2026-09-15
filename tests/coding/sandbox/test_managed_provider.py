"""Managed coding provider: factory, config, identity, profiles, client mapping."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from neos.coding.managed.allocation import legacy_ownership_digest
from neos.coding.sandbox.base import SandboxLimits, SandboxUnavailable
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.coding.sandbox.managed import (
    ManagedBackend,
    ManagedCodingAllocationAdapter,
    ManagedSandboxProvider,
    create_managed_coding_adapter,
)
from neos.coding.sandbox.managed.clients.base import (
    ProviderClientError,
    ProviderCreateSpec,
    ProviderErrorKind,
    classify_vendor_error,
    sanitize,
)
from neos.coding.sandbox.managed.clients.modal import ModalProviderClient
from neos.coding.sandbox.managed.identity import (
    DIGEST_PREFIX,
    ManagedCodingIdentity,
    PhysicalIdentity,
    decode_ownership_key,
)
from neos.coding.sandbox.managed.ledger import InMemoryCodingRuntimeLedger
from neos.coding.sandbox.managed.profiles import (
    DENY_ALL,
    OFFLINE_V1,
    PROFILES,
    NetworkPolicy,
    ProviderCapabilities,
    get_profile,
    negotiate_profile,
)
from neos.config.schema import AppConfig, ManagedSandboxConfig, SandboxConfig
from tests.coding.sandbox.managed_fakes import (
    IMAGE,
    LEAKED_TOKEN,
    OWNERSHIP_KEY,
    REFERENCE_KEY,
    AlreadyExistsError,
    FakeModalSdk,
    FakeVendor,
    NotFoundError,
    ServiceBusy,
    VendorHTTPError,
    allocation_cipher,
    build_client,
    create,
    managed_stack,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _config(**managed) -> SandboxConfig:
    return SandboxConfig.model_validate(
        {"provider": "managed", "managed": {"enabled": True, "provider": "e2b", **managed}}
    )


def _backend(tmp_path: Path, kind: str = "e2b", **changes) -> ManagedBackend:
    values = {
        "client": build_client(kind, FakeVendor(root=tmp_path)),
        "ledger": InMemoryCodingRuntimeLedger(),
        "image_digest": IMAGE,
        "ownership_key": OWNERSHIP_KEY,
        "allocation_cipher": allocation_cipher,
    }
    values.update(changes)
    return ManagedBackend(**values)


def _secret(key: bytes) -> str:
    return base64.b64encode(key).decode()


# ---- factory and config ----------------------------------------------------------


def test_defaults_stay_off_and_memory() -> None:
    config = AppConfig()
    assert config.sandbox.provider == "memory"
    assert config.sandbox.managed.enabled is False
    assert config.secrets.managed_coding_ownership_key is None
    assert ManagedSandboxConfig().coding_profile == "offline-v1"
    assert ManagedSandboxConfig().sandboxd_digest is None


def test_development_profile_stays_on_the_memory_sandbox() -> None:
    data = yaml.safe_load((REPO_ROOT / "config" / "neos.development.yaml").read_text()) or {}
    assert (data.get("sandbox") or {}).get("provider", "memory") == "memory"


def test_factory_refuses_managed_provider_when_plane_is_disabled() -> None:
    with pytest.raises(SandboxUnavailable, match="managed_sandbox_disabled"):
        create_sandbox_provider(SandboxConfig(provider="managed"))


@pytest.mark.parametrize("name", ("e2b", "modal"))
def test_factory_refuses_without_a_bound_client(name: str) -> None:
    with pytest.raises(SandboxUnavailable, match=f"managed_{name}_client_not_bound"):
        create_sandbox_provider(_config(provider=name))


@pytest.mark.parametrize("name", ("docker", "fake", "daytona"))
def test_factory_refuses_providers_without_a_guest_daemon(tmp_path, name: str) -> None:
    with pytest.raises(SandboxUnavailable, match=f"managed_provider_not_servable:{name}"):
        create_sandbox_provider(_config(provider=name), managed_backends={name: _backend(tmp_path)})


def test_factory_builds_the_provider_and_its_adapter_from_one_backend(tmp_path) -> None:
    backend = _backend(tmp_path)
    provider = create_sandbox_provider(_config(), managed_backends={"e2b": backend})
    assert isinstance(provider, ManagedSandboxProvider)
    assert provider.provider_name == "managed:e2b"
    assert provider.image_identity == IMAGE
    assert provider.local_provider is None
    assert provider.profile is OFFLINE_V1
    assert provider.fence is None
    adapter = create_managed_coding_adapter(_config(), backends={"e2b": backend})
    assert isinstance(adapter, ManagedCodingAllocationAdapter)
    assert adapter.provider == "e2b"
    assert adapter.capabilities.pause_resume is False


def test_factory_refuses_a_backend_for_another_provider(tmp_path) -> None:
    with pytest.raises(SandboxUnavailable, match="managed_backend_provider_mismatch"):
        create_sandbox_provider(
            _config(provider="modal"), managed_backends={"modal": _backend(tmp_path, "e2b")}
        )


def test_factory_refuses_an_unpinned_image_and_a_short_ownership_key(tmp_path) -> None:
    unpinned = _backend(tmp_path, image_digest="registry.example/neos-sandbox:latest")
    with pytest.raises(SandboxUnavailable, match="managed_image_unpinned"):
        create_sandbox_provider(_config(), managed_backends={"e2b": unpinned})
    short = _backend(tmp_path, ownership_key=b"k" * 16)
    with pytest.raises(SandboxUnavailable, match="managed_coding_ownership_key_invalid"):
        create_sandbox_provider(_config(), managed_backends={"e2b": short})


def test_factory_refuses_an_unregistered_profile(tmp_path) -> None:
    with pytest.raises(SandboxUnavailable, match="profile_unsupported:package-read-v1:unknown_profile"):
        create_sandbox_provider(
            _config(coding_profile="package-read-v1"), managed_backends={"e2b": _backend(tmp_path)}
        )


@pytest.mark.parametrize(
    "changes",
    ({"coding_profile": "Offline"}, {"sandboxd_digest": "sha256:xyz"}, {"sandboxd_digest": "0" * 64}),
)
def test_config_rejects_malformed_profile_and_digest(changes) -> None:
    with pytest.raises(ValidationError):
        _config(**changes)


def test_backend_repr_never_contains_the_key(tmp_path) -> None:
    assert "oooo" not in repr(_backend(tmp_path))


def test_managed_provider_requires_the_managed_plane() -> None:
    with pytest.raises(ValueError, match="requires sandbox.managed.enabled"):
        AppConfig.model_validate({"sandbox": {"provider": "managed"}})


def _managed_app(**secrets) -> dict:
    return {
        "sandbox": {"provider": "managed", "managed": {"enabled": True, "provider": "e2b"}},
        "secrets": {"managed_provider_reference_key": _secret(REFERENCE_KEY), **secrets},
    }


@pytest.mark.parametrize(
    ("secrets", "message"),
    (
        ({}, "requires secrets.managed_coding_ownership_key"),
        ({"managed_coding_ownership_key": "not base64!"}, "must be valid base64"),
        ({"managed_coding_ownership_key": _secret(b"o" * 16)}, "must decode to 32 bytes"),
        ({"managed_coding_ownership_key": _secret(REFERENCE_KEY)}, "must differ"),
    ),
)
def test_managed_provider_requires_a_separate_32_byte_ownership_key(secrets, message) -> None:
    with pytest.raises(ValueError, match=message):
        AppConfig.model_validate(_managed_app(**secrets))
    config = AppConfig.model_validate(
        _managed_app(managed_coding_ownership_key=_secret(OWNERSHIP_KEY))
    )
    assert _secret(OWNERSHIP_KEY) not in repr(config)


def test_the_managed_plane_alone_does_not_need_the_coding_ownership_key() -> None:
    config = AppConfig.model_validate(
        {
            "sandbox": {"managed": {"enabled": True}},
            "secrets": {"managed_provider_reference_key": _secret(REFERENCE_KEY)},
        }
    )
    assert config.sandbox.provider == "memory"


def test_staging_real_loop_accepts_a_managed_sandbox() -> None:
    config = AppConfig.model_validate(
        {
            "environment": "staging",
            "coding_model": {
                "enabled": True,
                "input_cost_micros_per_million": 3_000_000,
                "output_cost_micros_per_million": 15_000_000,
            },
            "sandbox": {
                "enabled": True,
                "provider": "managed",
                "managed": {"enabled": True, "provider": "e2b"},
            },
            "secrets": {
                "anthropic_api_key": "sk-ant-test-placeholder",
                "managed_provider_reference_key": _secret(REFERENCE_KEY),
                "managed_coding_ownership_key": _secret(OWNERSHIP_KEY),
            },
        }
    )
    assert config.sandbox.provider == "managed"


def test_the_ownership_key_is_loaded_from_its_own_environment_variable() -> None:
    from neos.config.loader import SECRET_ENV_MAPPING

    assert SECRET_ENV_MAPPING["MANAGED_CODING_OWNERSHIP_KEY"] == "secrets.managed_coding_ownership_key"
    template = (REPO_ROOT / ".env.template").read_text()
    assert "\nMANAGED_CODING_OWNERSHIP_KEY=\n" in template


def test_migration_057_attaches_the_runtime_to_the_allocation_plane() -> None:
    order = (REPO_ROOT / "db" / "BOOTSTRAP_ORDER.txt").read_text().splitlines()
    assert "db/migrations/057_add_coding_sandbox_ledger.sql" in order
    sql = (REPO_ROOT / "db" / "migrations" / "057_add_coding_sandbox_ledger.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS coding_managed_runtime (" in sql
    assert "REFERENCES coding_managed_sandboxes(allocation_id)" in sql
    assert "CREATE TABLE IF NOT EXISTS coding_managed_physical_objects (" in sql
    assert "idx_coding_managed_physical_active" in sql
    assert "coding_sandbox_ledger (" not in sql  # no second allocation ledger


async def test_configured_sandboxd_digest_is_what_the_handshake_must_match(tmp_path) -> None:
    from neos.coding.sandboxd.client import SandboxdExpectation

    pinned = SandboxdExpectation(bundle_digest="sha256:" + "2" * 64)
    async with managed_stack(tmp_path, "e2b", expectation=pinned) as stack:
        with pytest.raises(SandboxUnavailable, match="sandboxd_digest_mismatch"):
            await create(stack)


# ---- identity --------------------------------------------------------------------


def _identity_fields(**changes) -> PhysicalIdentity:
    values = dict(
        tenant_id="tenant_1",
        task_id="ct_1",
        allocation_id="msa_1",
        allocation_generation=1,
        sandbox_id="sbx_1",
        incarnation=1,
        profile="offline-v1",
        image_digest=IMAGE,
        region="local",
        expires_at=NOW,
    )
    values.update(changes)
    return PhysicalIdentity(**values)


def test_identifiers_are_deterministic_and_unambiguous() -> None:
    identity = ManagedCodingIdentity(OWNERSHIP_KEY)
    first = identity.sandbox_id(allocation_id="msa_1")
    assert first == ManagedCodingIdentity(OWNERSHIP_KEY).sandbox_id(allocation_id="msa_1")
    assert first != identity.sandbox_id(allocation_id="msa_2")
    assert identity.replacement_idempotency_key(sandbox_id=first, incarnation=2).endswith(f"{first}:2")
    with pytest.raises(ValueError, match="start at 2"):
        identity.replacement_idempotency_key(sandbox_id=first, incarnation=1)
    assert identity.provider_name(sandbox_id=first, incarnation=3).endswith("-i3")
    assert identity.ref_index(provider="e2b", provider_ref="a:b") != identity.ref_index(
        provider="e2b:a", provider_ref="b"
    )


@pytest.mark.parametrize(
    "change",
    (
        {"tenant_id": "tenant_2"},
        {"task_id": "ct_2"},
        {"allocation_id": "msa_2"},
        {"allocation_generation": 2},
        {"sandbox_id": "sbx_2"},
        {"incarnation": 2},
        {"profile": "strict-pids-v1"},
        {"image_digest": "other@sha256:" + "1" * 64},
        {"region": "eu"},
        {"expires_at": NOW + timedelta(seconds=1)},
    ),
)
def test_physical_digest_is_keyed_and_binds_every_fact(change) -> None:
    identity = ManagedCodingIdentity(OWNERSHIP_KEY)
    digest = identity.physical_digest(_identity_fields())
    assert digest.startswith(DIGEST_PREFIX)
    assert identity.verify_physical(digest, _identity_fields())
    assert not identity.verify_physical(digest, _identity_fields(**change))
    assert not ManagedCodingIdentity(b"z" * 32).verify_physical(digest, _identity_fields())
    assert "o" * 8 not in repr(identity)


def test_metadata_carries_both_the_legacy_and_the_keyed_digest() -> None:
    identity = ManagedCodingIdentity(OWNERSHIP_KEY)
    legacy = legacy_ownership_digest(tenant_id="tenant_1", allocation_id="msa_1")
    metadata = identity.metadata(_identity_fields(), idempotency_key="idem_1", legacy_ownership_digest=legacy)
    assert metadata["neos_ownership_digest"] == legacy
    assert metadata["neos_coding_ownership"] == identity.physical_digest(_identity_fields())
    assert metadata["neos_incarnation"] == "1"


def test_ownership_key_must_decode_to_exactly_32_bytes() -> None:
    assert decode_ownership_key(_secret(OWNERSHIP_KEY)) == OWNERSHIP_KEY
    with pytest.raises(ValueError, match="32_bytes"):
        decode_ownership_key(_secret(b"k" * 24))
    with pytest.raises(ValueError, match="invalid_encoding"):
        decode_ownership_key("%%%")
    with pytest.raises(ValueError):
        ManagedCodingIdentity(b"short")


# ---- profiles --------------------------------------------------------------------


def _capabilities(**changes) -> ProviderCapabilities:
    values = dict(
        provider="x",
        outbound_block_all=True,
        outbound_allowlist=False,
        inbound_closed_by_default=True,
        network_policy_readback=True,
        hard_pids_limit=False,
        hard_workspace_quota=False,
        suspend_preserves_processes=True,
        filesystem_snapshot=True,
        sandboxd_stdio_exec=True,
    )
    values.update(changes)
    return ProviderCapabilities(**values)


def test_profile_registry_is_immutable_and_offline_denies_everything() -> None:
    assert OFFLINE_V1.network == DENY_ALL
    with pytest.raises(TypeError):
        PROFILES["open-v1"] = OFFLINE_V1  # type: ignore[index]
    assert get_profile("offline-v1") is OFFLINE_V1


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"outbound_block_all": False}, "outbound_deny_unenforceable"),
        ({"inbound_closed_by_default": False}, "inbound_deny_unenforceable"),
        ({"network_policy_readback": False}, "network_policy_unverifiable"),
        ({"sandboxd_stdio_exec": False}, "sandboxd_channel_unavailable"),
    ),
)
def test_offline_profile_needs_every_capability(changes, reason) -> None:
    with pytest.raises(SandboxUnavailable, match=f"profile_unsupported:offline-v1:{reason}"):
        negotiate_profile(OFFLINE_V1, _capabilities(**changes))
    negotiate_profile(OFFLINE_V1, _capabilities())


def test_network_policy_cannot_mix_deny_and_allowlist() -> None:
    with pytest.raises(ValueError):
        NetworkPolicy(outbound="deny", inbound="deny", allow=("pypi.org",))
    with pytest.raises(ValueError):
        NetworkPolicy(outbound="allowlist", inbound="deny")


# ---- client error mapping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "kind"),
    (
        (TimeoutError(), ProviderErrorKind.TIMEOUT),
        (ConnectionResetError(), ProviderErrorKind.TRANSPORT),
        (NotFoundError(), ProviderErrorKind.NOT_FOUND),
        (AlreadyExistsError(), ProviderErrorKind.CONFLICT),
        (VendorHTTPError(429), ProviderErrorKind.RATE_LIMITED),
        (VendorHTTPError(401), ProviderErrorKind.AUTH),
        (ServiceBusy(), ProviderErrorKind.BUSY),
        (VendorHTTPError(500), ProviderErrorKind.SERVER_ERROR),
        (VendorHTTPError(400), ProviderErrorKind.INVALID),
        (ValueError("?"), ProviderErrorKind.OTHER),
    ),
)
def test_vendor_errors_are_classified(error, kind) -> None:
    assert classify_vendor_error(error) is kind


async def test_sanitize_keeps_only_provider_operation_and_kind() -> None:
    async def explode():
        raise VendorHTTPError(502)

    with pytest.raises(ProviderClientError) as info:
        await sanitize("modal", "create", explode())
    assert str(info.value) == "modal_create_server_error"
    assert info.value.ambiguous is True
    assert info.value.__suppress_context__ is True
    assert LEAKED_TOKEN not in str(info.value)


def _spec(**changes) -> ProviderCreateSpec:
    values = dict(
        allocation_id="msa_1",
        idempotency_key="idem_msa_1",
        provider_name="neos-sbx-1-i1",
        metadata={},
        image=IMAGE,
        region="local",
        network=DENY_ALL,
        limits=SandboxLimits.safe_defaults(),
        lifetime_sec=3600,
    )
    values.update(changes)
    return ProviderCreateSpec(**values)


async def test_modal_client_refuses_lifetimes_over_24_hours_without_calling_the_sdk(tmp_path) -> None:
    vendor = FakeVendor(root=tmp_path)
    client = ModalProviderClient(sdk=FakeModalSdk(vendor))
    with pytest.raises(ProviderClientError, match="modal_create_invalid"):
        await client.create(_spec(lifetime_sec=int(timedelta(hours=24).total_seconds()) + 1))
    assert vendor.calls == []


@pytest.mark.parametrize("kind", ("e2b", "modal"))
async def test_clients_refuse_anything_but_deny_networking(tmp_path, kind: str) -> None:
    vendor = FakeVendor(root=tmp_path)
    client = build_client(kind, vendor)
    open_network = NetworkPolicy(outbound="allowlist", inbound="deny", allow=("pypi.org",))
    with pytest.raises(ProviderClientError, match=f"{kind}_create_invalid"):
        await client.create(_spec(network=open_network))
    assert vendor.calls == []


@pytest.mark.parametrize("kind", ("e2b", "modal"))
async def test_client_probes_never_claim_hard_quotas(tmp_path, kind: str) -> None:
    capabilities = await build_client(kind, FakeVendor(root=tmp_path)).probe()
    assert capabilities.hard_pids_limit is False
    assert capabilities.hard_workspace_quota is False
    assert capabilities.outbound_allowlist is False
    assert capabilities.suspend_preserves_processes is (kind == "e2b")
