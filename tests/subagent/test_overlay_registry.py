from __future__ import annotations

from dataclasses import replace

import pytest

from neos.subagent.catalog import SpecRegistry, UnknownSpec, lookup_spec

pytestmark = pytest.mark.no_db


def test_overlay_register_does_not_mutate_the_global_catalog() -> None:
    overlay = SpecRegistry()
    base = lookup_spec("fsi-reader")
    alias = replace(base, name="kyc-doc-reader")
    overlay.register(alias)
    assert overlay.lookup_spec("kyc-doc-reader").name == "kyc-doc-reader"
    with pytest.raises(UnknownSpec):
        lookup_spec("kyc-doc-reader")
    assert lookup_spec("fsi-reader") is base


def test_default_registry_still_sees_fsi_reader() -> None:
    assert SpecRegistry().lookup_spec("fsi-reader").name == "fsi-reader"


def test_overlay_unknown_is_fail_closed() -> None:
    with pytest.raises(UnknownSpec) as raised:
        SpecRegistry().lookup_spec("not-a-spec")
    assert raised.value.name == "not-a-spec"
