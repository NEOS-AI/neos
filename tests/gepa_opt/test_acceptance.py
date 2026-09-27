"""Strict minibatch-sum acceptance. Val and test are not inputs."""

from __future__ import annotations

import pytest

from neos.gepa_opt.acceptance import accept_strict_minibatch_sum


pytestmark = pytest.mark.no_db


def test_strict_greater_accepts():
    assert accept_strict_minibatch_sum([0.0, 0.5], [0.5, 0.5]) is True
    assert accept_strict_minibatch_sum((1.0,), (1.1,)) is True


def test_equal_rejects():
    assert accept_strict_minibatch_sum([1.0, 0.0], [0.5, 0.5]) is False
    assert accept_strict_minibatch_sum([0.2], [0.2]) is False


def test_empty_rejects():
    assert accept_strict_minibatch_sum([], []) is False
    assert accept_strict_minibatch_sum([], [1.0]) is False
    assert accept_strict_minibatch_sum([1.0], []) is False


def test_length_mismatch_rejects():
    assert accept_strict_minibatch_sum([1.0], [1.0, 2.0]) is False
    assert accept_strict_minibatch_sum([0.0, 0.0, 0.0], [1.0]) is False
