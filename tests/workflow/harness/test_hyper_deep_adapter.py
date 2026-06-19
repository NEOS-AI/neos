from neos.workflow.harness.adapters.hyper_deep import hyper_deep_metadata_checks


def test_hyper_deep_metadata_checks_pass_good_metrics():
    checks = hyper_deep_metadata_checks(
        {
            "average_section_quality": 0.86,
            "total_section_iterations": 4,
            "sections_refined": 3,
        }
    )

    assert checks[0].name == "hyperdeep_section_quality"
    assert checks[0].passed is True
    assert checks[0].score == 0.86


def test_hyper_deep_metadata_checks_fail_low_quality():
    checks = hyper_deep_metadata_checks(
        {
            "average_section_quality": 0.62,
            "sections_refined": 3,
        }
    )

    assert checks[0].passed is False
    assert checks[0].repairable is True
