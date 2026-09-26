import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import store_longevity_download as download
import store_longevity_radar as radar


class HistoricalCodesTest(unittest.TestCase):
    def test_default_codes_expand_to_matching_legacy_codes(self):
        self.assertEqual(
            radar.historical_codes({"G21302", "G21306"}),
            {"G21302", "G21306", "D08A01", "D04A01", "D04A02"},
        )

    def test_custom_code_does_not_include_default_legacy_codes(self):
        self.assertEqual(radar.historical_codes({"G99999"}), {"G99999"})


class DownloadFailureTest(unittest.TestCase):
    def test_timeout_reports_unavailable_json(self):
        with (
            tempfile.TemporaryDirectory() as cache_dir,
            patch.object(download, "CACHE_DIR", cache_dir),
            patch.object(download, "http_get", side_effect=TimeoutError("timed out")),
            self.assertRaises(SystemExit) as raised,
        ):
            download.download_latest_zip()

        payload = json.loads(str(raised.exception))
        self.assertEqual(payload["status"], "unavailable")
        self.assertIn("timed out", payload["note"])

    def test_direct_timeout_falls_back_to_verified_mirror(self):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr(
                "상가정보_서울.csv",
                "상가업소번호,상호명,상권업종소분류코드\nS001,행복문구,G21302\n",
            )
        zip_bytes = zip_buffer.getvalue()
        object_url = (
            "https://pub-c974105a1e4840bcaa264cb2a55d99a1.r2.dev/"
            "store-longevity-radar/objects/FILE_1.zip"
        )
        manifest = json.dumps({
            "source_file_id": "FILE_1",
            "size_bytes": len(zip_bytes),
            "sha256": hashlib.sha256(zip_bytes).hexdigest(),
            "object_url": object_url,
        }).encode()

        def fake_http_get(url, timeout=60):
            if url == download.DATASET_PAGE:
                raise TimeoutError("timed out")
            if url == download.MIRROR_MANIFEST_URL:
                return io.BytesIO(manifest)
            if url == object_url:
                return io.BytesIO(zip_bytes)
            raise AssertionError(f"unexpected URL: {url}")

        with (
            tempfile.TemporaryDirectory() as cache_dir,
            patch.object(download, "CACHE_DIR", cache_dir),
            patch.object(download, "http_get", side_effect=fake_http_get),
        ):
            path = download.download_latest_zip()
            self.assertEqual(Path(path).read_bytes(), zip_bytes)


if __name__ == "__main__":
    unittest.main()
