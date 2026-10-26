import sys
import unittest

from twincheck.compare import CompareOptions, difference_kinds, minimize_input
from twincheck.runner import Observation, parse_command, run_program


class RunnerTests(unittest.TestCase):
    def test_command_parser_does_not_require_shell(self):
        self.assertEqual(parse_command('python -c "print(1)"'), ["python", "-c", "print(1)"])
        with self.assertRaises(ValueError):
            parse_command('python "unterminated')

    def test_stdin_is_delivered_to_process(self):
        result = run_program([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"], "hello", timeout=1)
        self.assertEqual(result.stdout, "HELLO")
        self.assertFalse(result.timed_out)
        self.assertEqual(result.returncode, 0)

    def test_argument_placeholder_is_replaced(self):
        result = run_program([sys.executable, "-c", "import sys; print(sys.argv[1])", "{input}"], "hi there", timeout=1)
        self.assertEqual(result.stdout, "hi there\n")

    def test_timeout_is_recorded(self):
        result = run_program([sys.executable, "-c", "import time; time.sleep(0.2)"], "", timeout=0.02)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.returncode)


class ComparisonTests(unittest.TestCase):
    def observation(self, *, returncode=0, stdout="out\n", stderr="", timed_out=False):
        return Observation(returncode, stdout, stderr, timed_out, 0.001)

    def test_each_difference_is_reported(self):
        reference = self.observation()
        candidate = self.observation(returncode=1, stdout="different\n", stderr="warning")
        self.assertEqual(
            difference_kinds(reference, candidate, CompareOptions()),
            ["exit_code", "stdout", "stderr"],
        )

    def test_normalization_options_are_respected(self):
        reference = self.observation(stdout="value  \r\n")
        candidate = self.observation(stdout="value\n")
        strict = difference_kinds(reference, candidate, CompareOptions())
        relaxed = difference_kinds(
            reference,
            candidate,
            CompareOptions(normalize_eol=True, ignore_trailing_whitespace=True),
        )
        self.assertEqual(strict, ["stdout"])
        self.assertEqual(relaxed, [])

    def test_ignore_flags_are_respected(self):
        reference = self.observation(returncode=0, stderr="reference")
        candidate = self.observation(returncode=2, stderr="candidate")
        self.assertEqual(
            difference_kinds(reference, candidate, CompareOptions(ignore_stderr=True, ignore_exit_code=True)),
            [],
        )

    def test_minimizer_keeps_the_small_trigger(self):
        minimized, trials, limit_reached = minimize_input(
            "noise-TRIGGER-noise", lambda value: "TRIGGER" in value
        )
        self.assertEqual(minimized, "TRIGGER")
        self.assertGreater(trials, 0)
        self.assertFalse(limit_reached)

    def test_minimizer_can_test_empty_input(self):
        minimized, _, _ = minimize_input("something", lambda value: value == "")
        self.assertEqual(minimized, "")


if __name__ == "__main__":
    unittest.main()
