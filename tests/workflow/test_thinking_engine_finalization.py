import os
import sys
import types

os.environ["GOOGLE_API_KEY"] = "test-key"
os.environ["OPENAI_API_KEY"] = "test-key"

import neos.config.settings as settings_module

settings_module.settings.GOOGLE_API_KEY = "test-key"
settings_module.settings.OPENAI_API_KEY = "test-key"

youtube_module = types.ModuleType("youtube_transcript_api")
youtube_module.YouTubeTranscriptApi = object
youtube_errors_module = types.ModuleType("youtube_transcript_api._errors")
youtube_errors_module.TranscriptsDisabled = Exception
youtube_errors_module.NoTranscriptFound = Exception
youtube_errors_module.VideoUnavailable = Exception
sys.modules.setdefault("youtube_transcript_api", youtube_module)
sys.modules.setdefault("youtube_transcript_api._errors", youtube_errors_module)

googleapi_module = types.ModuleType("googleapiclient")
googleapi_discovery_module = types.ModuleType("googleapiclient.discovery")
googleapi_discovery_module.build = lambda *args, **kwargs: object()
googleapi_errors_module = types.ModuleType("googleapiclient.errors")
googleapi_errors_module.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapi_module)
sys.modules.setdefault("googleapiclient.discovery", googleapi_discovery_module)
sys.modules.setdefault("googleapiclient.errors", googleapi_errors_module)

isodate_module = types.ModuleType("isodate")
isodate_module.parse_duration = lambda value: value
sys.modules.setdefault("isodate", isodate_module)


from neos.workflow.graph import _is_gate_harness_blocked  # noqa: E402


def test_gate_fail_blocks_finalization():
    state = {
        "harness_mode": "gate",
        "harness_verdict": "fail",
    }

    assert _is_gate_harness_blocked(state) is True


def test_gate_pass_allows_finalization():
    state = {
        "harness_mode": "gate",
        "harness_verdict": "pass",
    }

    assert _is_gate_harness_blocked(state) is False
