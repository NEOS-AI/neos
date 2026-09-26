import argparse
import os
import sys
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPT_DIR)

import run_survey  # noqa: E402


class SurveyUrlTests(unittest.TestCase):
    def test_build_url_uses_proxy_and_encodes_query(self):
        args = argparse.Namespace(
            sources=["kstartup", "bizinfo"],
            keyword="AI 바우처",
            max_pages=2,
            per_page=50,
            proxy_base_url="https://proxy.example/",
        )
        self.assertEqual(
            run_survey.build_url(args),
            "https://proxy.example/v1/government-support/survey?"
            "sources=kstartup%2Cbizinfo&maxPages=2&perPage=50&keyword=AI+%EB%B0%94%EC%9A%B0%EC%B2%98",
        )


if __name__ == "__main__":
    unittest.main()
