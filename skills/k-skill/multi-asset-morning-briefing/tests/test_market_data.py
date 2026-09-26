#!/usr/bin/env python3
"""market_data.py 오프라인 단위 테스트. 네트워크를 타지 않는다."""

import contextlib
import io
import json
import os
import re
import sys
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
)

import market_data  # noqa: E402


TREASURY_FIXTURE = (
    'Date,"1 Mo","2 Mo","3 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "09/15/2026,3.93,4.06,4.11,4.17,4.39,4.67,4.76,4.83,4.91,5.00,5.40,5.36\n"
    "09/14/2026,3.94,4.06,4.11,4.18,4.37,4.65,4.73,4.80,4.88,4.97,5.37,5.34\n"
    "09/11/2026,3.93,4.05,4.07,4.12,4.35,4.63,4.69,4.78,4.87,4.96,5.38,5.35\n"
)

FRED_FIXTURE = (
    "observation_date,SP500,VIXCLS,DEXKOUS\n"
    "2026-09-11,7656.98,15.10,1340.30\n"
    "2026-09-14,7619.98,,1385.09\n"
    "2026-09-15,7585.73,17.20,.\n"
)

CBOE_FIXTURE = (
    "DATE,OPEN,HIGH,LOW,CLOSE\n09/10/2026,15,17,14,16.2\n09/11/2026,16,18,15,17.1\n"
)
ECB_FIXTURE = (
    "TIME_PERIOD,OBS_VALUE,CURRENCY\n"
    "2026-09-11,1.18,USD\n2026-09-11,173.46,JPY\n2026-09-11,0.86,GBP\n"
)
ECOS_FIXTURE = json.dumps(
    {
        "StatisticSearch": {
            "row": [
                {"TIME": "20260910", "ITEM_NAME1": "KOSPI지수", "DATA_VALUE": "3300.1"},
                {"TIME": "20260911", "ITEM_NAME1": "KOSPI지수", "DATA_VALUE": "3310.2"},
                {"TIME": "20260911", "ITEM_NAME1": "KOSDAQ지수", "DATA_VALUE": "910.3"},
            ]
        }
    }
)


class TreasuryParseTests(unittest.TestCase):
    def test_parses_and_sorts_ascending(self):
        records = market_data.parse_treasury_csv(TREASURY_FIXTURE)
        self.assertEqual(
            [item["date"] for item in records],
            ["2026-09-11", "2026-09-14", "2026-09-15"],
        )
        self.assertEqual(records[-1]["y2"], 4.67)
        self.assertEqual(records[-1]["y10"], 5.00)
        self.assertEqual(records[-1]["y30"], 5.36)

    def test_missing_column_is_parse_error(self):
        with self.assertRaises(market_data.DataError) as context:
            market_data.parse_treasury_csv('Date,"2 Yr"\n09/15/2026,4.67\n')
        self.assertEqual(context.exception.code, "PARSE")
        self.assertEqual(context.exception.source, "us-treasury")

    def test_empty_input_is_parse_error(self):
        with self.assertRaises(market_data.DataError) as context:
            market_data.parse_treasury_csv("")
        self.assertEqual(context.exception.code, "PARSE")


class FredParseTests(unittest.TestCase):
    def test_blank_and_dot_values_become_none(self):
        ids, rows = market_data.parse_fred_csv(FRED_FIXTURE)
        self.assertEqual(ids, ["SP500", "VIXCLS", "DEXKOUS"])
        self.assertEqual(rows[-1]["values"]["VIXCLS"], 17.20)
        self.assertIsNone(rows[-1]["values"]["DEXKOUS"])
        self.assertIsNone(rows[-2]["values"]["VIXCLS"])

    def test_bad_header_is_parse_error(self):
        with self.assertRaises(market_data.DataError) as context:
            market_data.parse_fred_csv("date,VALUE\n2026-09-15,1.0\n")
        self.assertEqual(context.exception.code, "PARSE")
        self.assertEqual(context.exception.source, "fred")

    def test_plain_payload_is_single_table(self):
        payloads, was_zipped = market_data.extract_fred_payloads(
            FRED_FIXTURE.encode("utf-8")
        )
        self.assertFalse(was_zipped)
        self.assertEqual(len(payloads), 1)
        ids, rows = market_data.parse_fred_csv(payloads[0][1])
        self.assertEqual(ids, ["SP500", "VIXCLS", "DEXKOUS"])
        self.assertEqual(len(rows), 3)

    def test_split_zip_members_are_merged_without_losing_series(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("README.txt", "source: FRED")
            archive.writestr(
                "sp500.csv",
                "observation_date,SP500\n2026-09-11,7656.98\n2026-09-15,7585.73\n",
            )
            archive.writestr(
                "vix.csv",
                "observation_date,VIXCLS\n2026-09-11,15.10\n2026-09-14,16.40\n",
            )

        payloads, was_zipped = market_data.extract_fred_payloads(buffer.getvalue())
        self.assertTrue(was_zipped)
        self.assertEqual(len(payloads), 2)

        ids, rows = market_data.merge_fred_tables(
            [market_data.parse_fred_csv(text) for _name, text in payloads]
        )
        self.assertEqual(ids, ["SP500", "VIXCLS"])
        self.assertEqual(
            [row["date"] for row in rows], ["2026-09-11", "2026-09-14", "2026-09-15"]
        )
        self.assertEqual(rows[1]["values"], {"SP500": None, "VIXCLS": 16.40})
        self.assertEqual(rows[-1]["values"], {"SP500": 7585.73, "VIXCLS": None})


class OfficialSourceParseTests(unittest.TestCase):
    def test_cboe_vix_and_asset_unit(self):
        rows = market_data.parse_cboe_csv(CBOE_FIXTURE)
        self.assertEqual(rows[-1], {"date": "2026-09-11", "value": 17.1})

    def test_ecb_cross_rates_have_pair_units(self):
        rows = market_data.parse_ecb_csv(ECB_FIXTURE)
        crosses = market_data.ecb_crosses(rows[-1])
        self.assertEqual(crosses["EUR/USD"]["unit"], "USD/EUR")
        self.assertEqual(crosses["USD/JPY"]["unit"], "JPY/USD")
        self.assertAlmostEqual(crosses["USD/JPY"]["value"], 147.0)

    def test_malformed_ecos_json_is_typed(self):
        with self.assertRaises(market_data.DataError) as context:
            market_data.parse_ecos_json("{not-json")
        self.assertEqual(
            (context.exception.code, context.exception.source), ("PARSE", "ecos")
        )


class IndependentSessionTests(unittest.TestCase):
    def test_snapshot_resolves_us_and_korea_sessions_independently(self):
        cboe_us_holiday = "DATE,OPEN,HIGH,LOW,CLOSE\n09/10/2026,15,17,14,16.2\n"

        def fake_fetch(url, timeout=market_data.DEFAULT_TIMEOUT):
            if "VIX_History" in url:
                return cboe_us_holiday.encode()
            if "ecos.bok" in url:
                return ECOS_FIXTURE.encode()
            if "treasury.gov" in url:
                return TREASURY_FIXTURE.encode()
            if "data-api.ecb" in url:
                return ECB_FIXTURE.encode()
            raise AssertionError(url)

        original = market_data.fetch_bytes
        market_data.fetch_bytes = fake_fetch
        try:
            args = type("Args", (), {"briefing_date": "2026-09-14", "timeout": 1})()
            envelope = market_data.build_snapshot_envelope(args)
        finally:
            market_data.fetch_bytes = original
        self.assertEqual(
            envelope["sessions"],
            {"us_overnight": "2026-09-10", "korea_previous": "2026-09-11"},
        )

    def test_one_source_failure_does_not_abort_snapshot(self):
        def fake_fetch(url, timeout=market_data.DEFAULT_TIMEOUT):
            if "VIX_History" in url:
                raise urllib.error.URLError("offline")
            if "ecos.bok" in url:
                return ECOS_FIXTURE.encode()
            raise urllib.error.URLError("offline")

        original = market_data.fetch_bytes
        market_data.fetch_bytes = fake_fetch
        try:
            args = type("Args", (), {"briefing_date": "2026-09-14", "timeout": 1})()
            envelope = market_data.build_snapshot_envelope(args)
        finally:
            market_data.fetch_bytes = original
        self.assertIsNone(envelope["sessions"]["us_overnight"])
        self.assertEqual(envelope["sessions"]["korea_previous"], "2026-09-11")
        self.assertTrue(envelope["failures"])


class CurveTests(unittest.TestCase):
    def test_classification(self):
        cases = [
            (4.0, 3.0, "bear_flattening", "Bear Flattening"),
            (3.0, 4.0, "bear_steepening", "Bear Steepening"),
            (-4.0, -3.0, "bull_steepening", "Bull Steepening"),
            (-3.0, -4.0, "bull_flattening", "Bull Flattening"),
            (3.0, -2.0, "mixed", "Mixed"),
            (0.0, 0.0, "flat", "Flat"),
            (2.0, 2.0, "flat", "Flat"),
        ]
        for delta_2y, delta_10y, expected_key, expected_label in cases:
            with self.subTest(delta_2y=delta_2y, delta_10y=delta_10y):
                self.assertEqual(
                    market_data.classify_curve(delta_2y, delta_10y),
                    (expected_key, expected_label),
                )

    def test_none_input_returns_none(self):
        self.assertEqual(market_data.classify_curve(None, 1.0), (None, None))
        self.assertEqual(market_data.classify_curve(1.0, None), (None, None))


class YieldRowTests(unittest.TestCase):
    def test_spread_and_changes_use_raw_values(self):
        records = [
            {"date": "2026-09-14", "y2": 4.651, "y10": 4.985, "y30": 5.34},
            {"date": "2026-09-15", "y2": 4.655, "y10": 4.990, "y30": 5.36},
        ]
        rows = market_data.compute_yield_rows(records)

        self.assertIsNone(rows[0]["d_y2_bp"])
        self.assertIsNone(rows[0]["curve"])
        self.assertEqual(rows[0]["spread_2s10s_bp"], 33.4)

        self.assertEqual(rows[1]["d_y2_bp"], 0.4)
        self.assertEqual(rows[1]["d_y10_bp"], 0.5)
        self.assertEqual(rows[1]["d_spread_2s10s_bp"], 0.1)
        self.assertEqual(rows[1]["spread_2s10s_bp"], 33.5)
        self.assertEqual(rows[1]["curve"], "bear_steepening")

    def test_missing_yield_does_not_break_spread(self):
        records = [
            {"date": "2026-09-14", "y2": None, "y10": 4.985, "y30": None},
            {"date": "2026-09-15", "y2": 4.655, "y10": None, "y30": None},
        ]
        rows = market_data.compute_yield_rows(records)
        self.assertIsNone(rows[0]["spread_2s10s_bp"])
        self.assertIsNone(rows[1]["spread_2s10s_bp"])
        self.assertIsNone(rows[1]["d_spread_2s10s_bp"])


class StalenessTests(unittest.TestCase):
    def test_lag_detection(self):
        self.assertEqual(
            market_data.assess_staleness("2026-09-11", "2026-09-15"), (True, 4)
        )
        self.assertEqual(
            market_data.assess_staleness("2026-09-15", "2026-09-15"), (False, 0)
        )
        self.assertEqual(
            market_data.assess_staleness("2026-09-16", "2026-09-15"), (False, 0)
        )
        self.assertEqual(market_data.assess_staleness(None, "2026-09-15"), (False, 0))
        self.assertEqual(market_data.assess_staleness("2026-09-11", None), (False, 0))

    def test_summary_skips_trailing_missing_values(self):
        _, rows = market_data.parse_fred_csv(FRED_FIXTURE)
        summary = market_data.summarize_series(rows, "DEXKOUS", "2026-09-15")
        self.assertEqual(summary["latest_date"], "2026-09-14")
        self.assertEqual(summary["latest_value"], 1385.09)
        self.assertEqual((summary["stale"], summary["lag_days"]), (True, 1))

    def test_summary_is_fresh_when_session_matches(self):
        _, rows = market_data.parse_fred_csv(FRED_FIXTURE)
        summary = market_data.summarize_series(rows, "SP500", "2026-09-15")
        self.assertEqual((summary["stale"], summary["lag_days"]), (False, 0))


class TrimTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"date": "2026-09-{:02d}".format(day)} for day in (10, 11, 14, 15)]

    def test_last(self):
        self.assertEqual(
            [row["date"] for row in market_data.trim_rows(self.rows, last=2)],
            ["2026-09-14", "2026-09-15"],
        )

    def test_start_and_end(self):
        self.assertEqual(
            [
                row["date"]
                for row in market_data.trim_rows(
                    self.rows, start="2026-09-11", end="2026-09-14"
                )
            ],
            ["2026-09-11", "2026-09-14"],
        )


class CliTests(unittest.TestCase):
    def test_http_failure_returns_error_envelope_and_exit_code(self):
        def boom(url, timeout=market_data.DEFAULT_TIMEOUT):
            raise urllib.error.URLError("connection refused")

        original = market_data.fetch_bytes
        market_data.fetch_bytes = boom
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = market_data.main(["series", "--ids", "SP500"])
        finally:
            market_data.fetch_bytes = original

        self.assertEqual(exit_code, 1)
        envelope = json.loads(stderr.getvalue())
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["source"], "fred")

    def test_yields_envelope_never_overwrites_observation_dates(self):
        payload = TREASURY_FIXTURE.encode("utf-8")
        original = market_data.fetch_bytes
        market_data.fetch_bytes = lambda url, timeout=market_data.DEFAULT_TIMEOUT: (
            payload
        )
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                exit_code = market_data.main(
                    ["yields", "--last", "2", "--session", "2026-09-16"]
                )
        finally:
            market_data.fetch_bytes = original

        self.assertEqual(exit_code, 0)
        envelope = json.loads(stdout.getvalue())
        self.assertEqual(
            [row["date"] for row in envelope["rows"]], ["2026-09-14", "2026-09-15"]
        )
        self.assertTrue(envelope["warnings"])
        self.assertEqual(envelope["rows"][1]["curve_label"], "Bear Steepening")
        self.assertEqual(envelope["rows"][1]["d_spread_2s10s_bp"], 1.0)

    def test_missing_requested_series_is_reported(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "sp500.csv", "observation_date,SP500\n2026-09-15,7585.73\n"
            )
        payload = buffer.getvalue()

        original = market_data.fetch_bytes
        market_data.fetch_bytes = lambda url, timeout=market_data.DEFAULT_TIMEOUT: (
            payload
        )
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                exit_code = market_data.main(
                    ["series", "--ids", "SP500,VIXCLS", "--last", "1"]
                )
        finally:
            market_data.fetch_bytes = original

        self.assertEqual(exit_code, 0)
        envelope = json.loads(stdout.getvalue())
        self.assertEqual([item["id"] for item in envelope["series"]], ["SP500"])
        self.assertTrue(any("VIXCLS" in warning for warning in envelope["warnings"]))

    def test_timeout_is_typed_and_actionable(self):
        def slow(url, timeout=market_data.DEFAULT_TIMEOUT):
            raise TimeoutError("simulated timeout")

        original = market_data.fetch_bytes
        market_data.fetch_bytes = slow
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = market_data.main(["yields"])
        finally:
            market_data.fetch_bytes = original

        self.assertEqual(exit_code, 1)
        envelope = json.loads(stderr.getvalue())
        self.assertEqual(envelope["error"]["code"], "TIMEOUT")
        self.assertIn("--timeout", envelope["error"]["message"])

    def test_no_subcommand_is_usage_error(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(market_data.main([]), 2)


class NoNetworkTests(unittest.TestCase):
    def test_pure_functions_do_not_touch_network(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("pure functions must not open the network")

        original = market_data.urllib.request.urlopen
        market_data.urllib.request.urlopen = forbidden
        try:
            records = market_data.parse_treasury_csv(TREASURY_FIXTURE)
            market_data.compute_yield_rows(records)
            market_data.parse_fred_csv(FRED_FIXTURE)
            market_data.assess_staleness("2026-09-11", "2026-09-15")
        finally:
            market_data.urllib.request.urlopen = original


class FakeResponse:
    def __init__(self, body, declared=None):
        self.body = body
        self.headers = {} if declared is None else {"Content-Length": str(declared)}
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size=-1):
        self.read_sizes.append(size)
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


class HttpSafetyTests(unittest.TestCase):
    def test_declared_oversized_response_is_rejected_before_read(self):
        response = FakeResponse(b"x", market_data.MAX_RESPONSE_BYTES + 1)
        with patch("market_data.urllib.request.urlopen", return_value=response):
            with self.assertRaises(market_data.DataError) as context:
                market_data.fetch_bytes("https://example.com")
        self.assertEqual(context.exception.code, "LIMIT")
        self.assertEqual(response.read_sizes, [])

    def test_streamed_oversized_response_uses_bounded_reads(self):
        response = FakeResponse(b"x" * (market_data.MAX_RESPONSE_BYTES + 1))
        with patch("market_data.urllib.request.urlopen", return_value=response):
            with self.assertRaises(market_data.DataError) as context:
                market_data.fetch_bytes("https://example.com")
        self.assertEqual(context.exception.code, "LIMIT")
        self.assertTrue(all(0 < size <= 64 * 1024 for size in response.read_sizes))


class BriefingContractTests(unittest.TestCase):
    def test_golden_briefing_has_title_sections_links_and_memo_tone(self):
        fixture = Path(__file__).with_name("fixtures") / "sample_briefing.md"
        text = fixture.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertRegex(lines[0], r"^\d{4}\.\d{2}\.\d{2} Morning Market Briefing$")
        headings = [line for line in lines if re.match(r"^\d+\. ", line)]
        self.assertEqual(
            headings,
            [
                "1. Summary",
                "2. Rates",
                "3. FX",
                "4. Commodity",
                "5. Equity, Vol",
                "6. 한국 증시",
                "7. 주요 일정",
            ],
        )
        bullets = [line for line in lines if line.startswith("•")]
        self.assertEqual(len(bullets), 7)
        self.assertTrue(
            all(re.search(r"\[[^]]+\]\(https://[^)]+\)$", line) for line in bullets)
        )
        self.assertFalse(re.search(r"(?i)(^|\s)by(?:\s|$)", text))
        self.assertTrue(
            all(
                not re.search(r"(입니다|했습니다|이다|했다|합니다|한다)\.?\s*\[", line)
                for line in bullets
            )
        )


if __name__ == "__main__":
    unittest.main()
