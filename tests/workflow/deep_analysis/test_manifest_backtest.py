from scripts.manifest_backtest import MANIFEST_FIELDS, recoverable_fields


def test_legacy_artifact_recovers_only_what_it_recorded():
    """표본 #16~#20 의 실제 모양.

    옛 지문에는 models·resolved_models·global_token_cap 등이 있으나
    프롬프트 해시도 스킬 목록도 components 도 없다.
    """
    legacy = {
        "config_fingerprint": {
            "global_token_cap": 300000,
            "max_depth": 2,
            "models": {"judge": None},
            "resolved_models": {"judge": {"model": "claude-sonnet-5"}},
            "git": {"commit": "abc"},
        }
    }

    recovered = recoverable_fields(legacy)

    assert recovered["models"] is True
    assert recovered["prompts"] is False
    assert recovered["skills"] is False
    assert recovered["components"] is False
    assert recovered["profile"] is False


def test_new_artifact_recovers_every_field():
    new = {
        "config_fingerprint": {
            "manifest_version": 1,
            "git": {"commit": "abc"},
            "runs": {
                "r1": {
                    "manifest_version": 1,
                    "profile": "dev",
                    "models": {"judge": {"model": "claude-sonnet-5"}},
                    "budget": {"global_token_cap": 140000},
                    "prompts": {"final_compose": "sha256:a"},
                    "skills": [],
                    "components": {"grader": "x:Y"},
                    "config": {"max_depth": 2},
                }
            },
        }
    }

    recovered = recoverable_fields(new)

    assert all(recovered[field] for field in MANIFEST_FIELDS)


def test_every_manifest_field_is_judged():
    legacy = {"config_fingerprint": {}}

    assert set(recoverable_fields(legacy)) == set(MANIFEST_FIELDS)
