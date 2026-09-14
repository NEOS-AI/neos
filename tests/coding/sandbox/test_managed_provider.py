"""Managed coding provider: factory, config, identity, profiles, client mapping."""

from __future__ import annotations

import base64
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from neos.coding.sandbox.base import SandboxLimits, SandboxUnavailable
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.coding.sandbox.managed import ManagedBackend, ManagedSandboxProvider
from neos.coding.sandbox.managed.clients.base import (
    ProviderClientError,
    ProviderCreateSpec,
    ProviderErrorKind,
    classify_vendor_error,
    sanitize,
)
from neos.coding.sandbox.managed.clients.modal import ModalProviderClient
from neos.coding.sandbox.managed.identity import (
    SandboxIdentity,
    derive_ownership_key,
    ownership_key_from_secret,
)
from neos.coding.sandbox.managed.ledger import InMemorySandboxLedger
from neos.coding.sandbox.managed.profiles import (
    DENY_ALL,
    OFFLINE_V1,
    PROFILES,
    NetworkPolicy,
    ProviderCapabilities,
    get_profile,
    negotiate_profile,
)
from neos.coding.sandboxd import guest
from neos.config.schema import AppConfig, ManagedSandboxConfig, SandboxConfig
from tests.coding.sandbox.managed_fakes import (
    IMAGE,
    KEY,
    LEAKED_TOKEN,
    AlreadyExistsError,
    FakeModalSdk,
    FakeVendor,
    NotFoundError,
    ServiceBusy,
    VendorHTTPError,
    build_client,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[3]


def _config(**managed) -> SandboxConfig:
    return SandboxConfig.model_validate(
        {"provider": "managed", "managed": {"enabled": True, "provider": "e2b", **managed}}
    )


def _backend(tmp_path: Path, kind: str = "e2b", **changes) -> ManagedBackend:
    values = {
        "client": build_client(kind, FakeVendor(root=tmp_path)),
        "ledger": InMemorySandboxLedger(),
        "image_digest": IMAGE,
        "ownership_key": KEY,
    }
    values.update(changes)
    return ManagedBackend(**values)


# ---- factory and config ----------------------------------------------------------


def test_defaults_stay_off_and_memory() -> None:
    config = AppConfig()
    assert config.sandbox.provider == "memory"
    assert config.sandbox.managed.enabled is False
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


def test_factory_builds_the_provider_from_an_injected_backend(tmp_path) -> None:
    provider = create_sandbox_provider(_config(), managed_backends={"e2b": _backend(tmp_path)})
    assert isinstance(provider, ManagedSandboxProvider)
    assert provider.provider_name == "managed:e2b"
    assert provider.image_identity == IMAGE
    assert provider.local_provider is None
    assert provider.profile is OFFLINE_V1


def test_factory_refuses_a_backend_for_another_provider(tmp_path) -> None:
    with pytest.raises(SandboxUnavailable, match="managed_backend_provider_mismatch"):
        create_sandbox_provider(
            _config(provider="modal"), managed_backends={"modal": _backend(tmp_path, "e2b")}
        )


def test_factory_refuses_an_unpinned_image(tmp_path) -> None:
    backend = _backend(tmp_path, image_digest="registry.example/neos-sandbox:latest")
    with pytest.raises(SandboxUnavailable, match="managed_image_unpinned"):
        create_sandbox_provider(_config(), managed_backends={"e2b": backend})


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


async def test_configured_sandboxd_digest_is_what_the_handshake_must_match(tmp_path) -> None:
    backend = _backend(tmp_path)
    provider = create_sandbox_provider(
        _config(sandboxd_digest="sha256:" + "2" * 64), managed_backends={"e2b": backend}
    )
    try:
        with pytest.raises(SandboxUnavailable, match="sandboxd_digest_mismatch"):
            await provider.create(owner_id="ct_1", limits=SandboxLimits.safe_defaults())
    finally:
        await provider.close()
    bundled = create_sandbox_provider(_config(), managed_backends={"e2b": backend})
    assert bundled._expectation.bundle_digest == guest.bundle_digest()


def test_backend_repr_never_contains_the_key(tmp_path) -> None:
    assert "kkkk" not in repr(_backend(tmp_path))


def test_managed_provider_requires_the_managed_plane() -> None:
    with pytest.raises(ValueError, match="requires sandbox.managed.enabled"):
        AppConfig.model_validate({"sandbox": {"provider": "managed"}})


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
                "managed_provider_reference_key": base64.b64encode(b"k" * 32).decode(),
            },
        }
    )
    assert config.sandbox.provider == "managed"


def test_migration_057_is_in_the_canonical_bootstrap_order() -> None:
    order = (REPO_ROOT / "db" / "BOOTSTRAP_ORDER.txt").read_text().splitlines()
    assert "db/migrations/057_add_coding_sandbox_ledger.sql" in order
    sql = (REPO_ROOT / "db" / "migrations" / "057_add_coding_sandbox_ledger.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS coding_sandbox_ledger (" in sql
    assert "'destroy_pending'" in sql


# ---- identity --------------------------------------------------------------------


def test_identifiers_are_deterministic_and_unambiguous() -> None:
    identity = SandboxIdentity(KEY)
    first = identity.sandbox_id(owner_id="ct_1", task_id="ct_1", ordinal=1)
    assert first == SandboxIdentity(KEY).sandbox_id(owner_id="ct_1", task_id="ct_1", ordinal=1)
    assert first != identity.sandbox_id(owner_id="ct_1", task_id="ct_1", ordinal=2)
    assert identity.sandbox_id(owner_id="a:b", task_id="c", ordinal=1) != identity.sandbox_id(
        owner_id="a", task_id="b:c", ordinal=1
    )
    allocation = identity.allocation_id(sandbox_id=first, generation=1)
    assert identity.idempotency_key(allocation).endswith(allocation)
    assert identity.provider_name(allocation).startswith("neos-alc-")


def test_ownership_digest_is_keyed() -> None:
    identity = SandboxIdentity(KEY)
    digest = identity.ownership_digest(allocation_id="alc_1", owner_id="ct_1", generation=1)
    assert digest.startswith("hmac-sha256:")
    assert identity.verify_ownership(digest, allocation_id="alc_1", owner_id="ct_1", generation=1)
    assert not identity.verify_ownership(digest, allocation_id="alc_1", owner_id="ct_2", generation=1)
    assert not identity.verify_ownership(digest, allocation_id="alc_1", owner_id="ct_1", generation=2)
    assert not SandboxIdentity(b"z" * 32).verify_ownership(
        digest, allocation_id="alc_1", owner_id="ct_1", generation=1
    )
    assert "k" * 8 not in repr(identity)


def test_ownership_key_is_derived_from_the_reference_secret() -> None:
    secret = base64.b64encode(KEY).decode()
    derived = ownership_key_from_secret(secret)
    assert derived == derive_ownership_key(KEY)
    assert derived != KEY
    with pytest.raises(ValueError):
        derive_ownership_key(b"short")


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
        allocation_id="alc_1",
        idempotency_key="neos-coding-sbx:v1:alc_1",
        provider_name="neos-alc-1",
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
