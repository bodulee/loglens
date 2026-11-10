"""End-to-end contracts using real files and real subprocesses."""

import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMON = '192.0.2.1 - - [11/Nov/2026:10:00:00 +0000] "GET /search?q=linux HTTP/1.1" 200 100\n'
COMBINED = '192.0.2.2 - - [11/Nov/2026:10:00:01 +0000] "POST /api HTTP/1.1" 500 50 "-" "curl/8.0"\n'
NOT_FOUND = '192.0.2.1 - - [11/Nov/2026:10:00:02 +0000] "GET /search?q=python HTTP/2.0" 404 -\n'


class CliTests(unittest.TestCase):
    def run_cli(self, *args, data=None):
        return subprocess.run(
            [sys.executable, "-m", "loglens", *map(str, args)],
            input=data, text=True, encoding="utf-8", capture_output=True,
            cwd=ROOT, timeout=15,
        )

    def report(self, data, *args):
        result = self.run_cli("-", "--json", *args, data=data)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_common_combined_and_query_grouping(self):
        report = self.report(COMMON + COMBINED + NOT_FOUND)
        self.assertEqual(report["requests"], 3)
        self.assertEqual(report["bytes_sent"], 150)
        self.assertEqual(report["unknown_size_requests"], 1)
        self.assertEqual(report["errors"], 2)
        self.assertAlmostEqual(report["error_rate_percent"], 66.67, places=2)
        self.assertEqual(report["status_codes"], {"200": 1, "404": 1, "500": 1})
        self.assertEqual(report["methods"], {"GET": 2, "POST": 1})
        self.assertEqual(report["top_paths"], [{"value": "/search", "count": 2}, {"value": "/api", "count": 1}])
        self.assertEqual(report["unique_clients"], 2)
        self.assertEqual(report["top_clients"][0], {"value": "192.0.2.1", "count": 2})

    def test_keep_query_is_explicit(self):
        report = self.report(COMMON + NOT_FOUND, "--keep-query")
        self.assertEqual([x["value"] for x in report["top_paths"]], ["/search?q=linux", "/search?q=python"])

    def test_malformed_and_blank_lines_are_counted_separately(self):
        report = self.report(COMMON + "invalid\n\n")
        self.assertEqual((report["lines_read"], report["requests"], report["malformed_lines"], report["blank_lines"]), (3, 1, 1, 1))

    def test_all_invalid_input_has_nonzero_exit_and_report(self):
        result = self.run_cli("-", "--json", data="not an access log\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(result.stdout, result.stderr)
        self.assertEqual(json.loads(result.stdout)["malformed_lines"], 1)

    def test_empty_input_is_a_zero_report(self):
        report = self.report("")
        self.assertEqual((report["requests"], report["error_rate_percent"]), (0, 0.0))
        self.assertEqual(report["top_paths"], [])

    def test_gzip_and_plain_files_are_aggregated(self):
        with tempfile.TemporaryDirectory() as folder:
            plain = Path(folder) / "access.log"
            zipped = Path(folder) / "access.log.1.gz"
            plain.write_text(COMMON, encoding="utf-8")
            with gzip.open(zipped, "wt", encoding="utf-8") as stream:
                stream.write(COMBINED)
            result = self.run_cli(plain, zipped, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["requests"], 2)

    def test_missing_file_fails_without_partial_report(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_cli(Path(folder) / "missing.log", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    def test_corrupt_gzip_is_a_read_error(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "broken.gz"
            bad.write_bytes(b"not gzip")
            result = self.run_cli(bad)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    def test_truncated_gzip_is_a_read_error(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "truncated.gz"
            bad.write_bytes(gzip.compress(COMMON.encode())[:-5])
            result = self.run_cli(bad)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    def test_top_limit_has_stable_alphabetical_ties(self):
        report = self.report(COMMON + COMBINED, "--top", "1")
        self.assertEqual(report["top_paths"], [{"value": "/api", "count": 1}])
        self.assertEqual(len(report["top_clients"]), 1)
        self.assertEqual(report["requests"], 2)

    def test_invalid_top_is_rejected(self):
        for value in ("0", "-1", "abc"):
            with self.subTest(value=value):
                result = self.run_cli("-", "--top", value, data=COMMON)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)

    def test_ipv6_and_missing_request_are_preserved(self):
        line = '2001:db8::1 - - [11/Nov/2026:10:00:03 +0000] "-" 400 -\n'
        report = self.report(line)
        self.assertEqual(report["requests"], 1)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["top_clients"], [{"value": "2001:db8::1", "count": 1}])
        self.assertEqual(report["top_paths"], [{"value": "-", "count": 1}])

    def test_escaped_quotes_in_user_agent_are_accepted(self):
        line = COMBINED.replace('curl/8.0', r'agent\"quoted\"')
        self.assertEqual(self.report(line)["requests"], 1)

    def test_unknown_trailing_fields_and_invalid_status_are_malformed(self):
        bad = COMMON.replace(" 200 100", " 999 100") + COMMON.rstrip() + " unexpected\n"
        report = self.report(COMMON + bad)
        self.assertEqual(report["requests"], 1)
        self.assertEqual(report["malformed_lines"], 2)

    def test_text_report_escapes_terminal_control_characters(self):
        result = self.run_cli("-", data=COMMON.replace("/search?q=linux", "/\x1b[31mred"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("\x1b", result.stdout)
        self.assertIn(r"\x1b", result.stdout)

    def test_text_report_has_human_readable_summary(self):
        result = self.run_cli("-", data=COMMON + COMBINED)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Requests: 2", result.stdout)
        self.assertIn("50.00%", result.stdout)
        self.assertIn("/search", result.stdout)
        self.assertIn("500", result.stdout)

    def test_duplicate_stdin_is_rejected(self):
        result = self.run_cli("-", "-", data=COMMON)
        self.assertEqual(result.returncode, 2)

    def test_no_files_shows_usage_instead_of_waiting(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr.lower())

    def test_closed_output_pipe_exits_without_traceback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "many.log"
            path.write_text("".join(COMMON.replace("/search?q=linux", f"/item/{i}") for i in range(5000)), encoding="utf-8")
            process = subprocess.Popen(
                [sys.executable, "-m", "loglens", str(path), "--top", "5000"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", cwd=ROOT,
            )
            try:
                process.stdout.readline()
                process.stdout.close()
                process.wait(timeout=15)
                error = process.stderr.read()
                self.assertEqual(process.returncode, 0, error)
                self.assertNotIn("Traceback", error)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
