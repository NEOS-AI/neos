from neos.workflow.harness.cache_policy import should_cache_harness_result


def result(mode, verdict, score=0.8):
    return {
        "metadata": {
            "harness": {
                "mode": mode,
                "verdict": verdict,
                "score": score,
            }
        }
    }


def test_gate_pass_can_be_cached():
    assert should_cache_harness_result(result("gate", "pass")) is True


def test_gate_fail_is_not_cached():
    assert should_cache_harness_result(result("gate", "fail")) is False


def test_advisory_pass_can_be_cached():
    assert should_cache_harness_result(result("advisory", "advisory_pass")) is True


def test_advisory_fail_is_skipped_by_default():
    assert should_cache_harness_result(result("advisory", "fail")) is False


def test_advisory_fail_can_be_cached_when_policy_allows_it():
    assert (
        should_cache_harness_result(
            result("advisory", "fail"),
            cache_policy="allow_advisory_fail",
        )
        is True
    )


def test_missing_harness_metadata_preserves_existing_cache_behavior():
    assert should_cache_harness_result({"metadata": {}}) is True

