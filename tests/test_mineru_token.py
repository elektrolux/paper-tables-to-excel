"""Offline tests for token input; no real credentials or network calls."""

import contextlib
import io
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import mineru_convert as single
import mineru_batch_convert as batch


FAKE_TOKEN = "test-only-not-a-real-mineru-token"


class TokenInputTests(unittest.TestCase):
    def test_stdin_reads_one_line_without_prompt_or_echo(self):
        output = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(FAKE_TOKEN + "\n")), \
                mock.patch.object(single, "prompt_token") as prompt, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(single.read_token(True), FAKE_TOKEN)
        prompt.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_default_still_prompts(self):
        with mock.patch.object(single, "prompt_token", return_value=FAKE_TOKEN) as prompt:
            self.assertEqual(single.read_token(), FAKE_TOKEN)
        prompt.assert_called_once_with()

    def test_stdin_rejects_invalid_tokens_without_echo(self):
        for value in ("", "\n", "Bearer " + FAKE_TOKEN, FAKE_TOKEN + " invalid"):
            with self.subTest(value=value), \
                    mock.patch.object(sys, "stdin", io.StringIO(value)), \
                    mock.patch.object(single, "prompt_token") as prompt:
                with self.assertRaises(RuntimeError) as caught:
                    single.read_token(True)
                self.assertNotIn(FAKE_TOKEN, str(caught.exception))
                prompt.assert_not_called()

    def test_stdin_rejects_interactive_terminal(self):
        terminal = mock.Mock()
        terminal.isatty.return_value = True
        with mock.patch.object(sys, "stdin", terminal), self.assertRaises(RuntimeError):
            single.read_token(True)
        terminal.readline.assert_not_called()

    def test_single_cli_passes_stdin_token_to_converter(self):
        output = io.StringIO()
        argv = ["mineru_convert.py", "paper.pdf", "--output", "unused", "--token-stdin"]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sys, "stdin", io.StringIO(FAKE_TOKEN + "\n")), \
                mock.patch.object(single, "validate_input"), \
                mock.patch.object(single, "prompt_token") as prompt, \
                mock.patch.object(single, "convert_input", return_value={}) as convert, \
                contextlib.redirect_stdout(output):
            self.assertEqual(single.main(), 0)
        self.assertEqual(convert.call_args.args[2], FAKE_TOKEN)
        prompt.assert_not_called()
        self.assertNotIn(FAKE_TOKEN, output.getvalue())

    def test_batch_cli_reuses_one_stdin_line(self):
        stdin = io.StringIO(FAKE_TOKEN + "\nunused-second-line\n")
        output = io.StringIO()
        argv = ["mineru_batch_convert.py", "main.pdf", "supp.pdf", "--output-root", "unused", "--token-stdin"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", stdin), \
                mock.patch.object(batch, "validate_input"), \
                mock.patch.object(pathlib.Path, "mkdir"), \
                mock.patch.object(single, "prompt_token") as prompt, \
                mock.patch.object(batch, "convert_input", return_value={}) as convert, \
                contextlib.redirect_stdout(output):
            self.assertEqual(batch.main(), 0)
        self.assertEqual(convert.call_count, 2)
        self.assertTrue(all(call.args[2] == FAKE_TOKEN for call in convert.call_args_list))
        self.assertEqual(stdin.readline(), "unused-second-line\n")
        prompt.assert_not_called()
        self.assertNotIn(FAKE_TOKEN, output.getvalue())

    def test_empty_stdin_stops_both_clis_before_conversion(self):
        cases = [(single, ["paper.pdf", "--output", "unused"]),
                 (batch, ["paper.pdf", "--output-root", "unused"])]
        for module, args in cases:
            with self.subTest(module=module.__name__), \
                    mock.patch.object(sys, "argv", ["script.py", *args, "--token-stdin"]), \
                    mock.patch.object(sys, "stdin", io.StringIO()), \
                    mock.patch.object(module, "validate_input"), \
                    mock.patch.object(module, "convert_input") as convert, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 2)
                convert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
