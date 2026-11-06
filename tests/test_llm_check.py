# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""Offline tests for judge voting and caching."""

import hashlib
import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

judge = importlib.import_module("prompt_injection_benchmark.core.evaluation.llm_check")


class LLMCheckTests(unittest.TestCase):
    def setUp(self):
        cache = TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.cache_dir = Path(cache.name)
        env = patch.dict(os.environ, {
            "LLM_CHECK_MODEL": "mockllm/judge-a",
            "LLM_CHECK_VOTES": "3",
            "LLM_CHECK_CACHE_DIR": cache.name,
        })
        env.start()
        self.addCleanup(env.stop)
        judge.clear_cache()
        self.addCleanup(judge.clear_cache)

    def test_cache_separates_judges(self):
        for disk in (False, True):
            with self.subTest(disk=disk), patch.object(
                judge, "_single_call", side_effect=lambda model, prompt: model.endswith("a")
            ) as call:
                text = f"judge isolation {disk}"
                self.assertTrue(judge.llm_check(text, "Does it match?"))
                if disk:
                    judge.clear_cache()
                with patch.dict(os.environ, {"LLM_CHECK_MODEL": "mockllm/judge-b"}):
                    self.assertFalse(judge.llm_check(text, "Does it match?"))
                self.assertEqual([args.args[0] for args in call.call_args_list],
                                 ["mockllm/judge-a"] * 2 + ["mockllm/judge-b"] * 2)

    def test_cache_separates_vote_counts(self):
        for disk in (False, True):
            with self.subTest(disk=disk), patch.object(
                judge, "_single_call", side_effect=[True, True, False]
            ) as call:
                text = f"vote isolation {disk}"
                self.assertTrue(judge.llm_check(text, "Does it match?"))
                if disk:
                    judge.clear_cache()
                with patch.dict(os.environ, {"LLM_CHECK_VOTES": "1"}):
                    self.assertFalse(judge.llm_check(text, "Does it match?"))
                self.assertEqual(call.call_count, 3)

    def test_matching_configuration_reuses_true_and_false_results(self):
        for result in (False, True):
            with self.subTest(result=result), patch.object(
                judge, "_single_call", return_value=result
            ) as call:
                text = f"reuse {result}"
                self.assertEqual(judge.llm_check(text, "Does it match?"), result)
                self.assertEqual(judge.llm_check(text, "Does it match?"), result)
                judge.clear_cache()
                self.assertEqual(judge.llm_check(text, "Does it match?"), result)
                self.assertEqual(call.call_count, 2)

    def test_cache_separates_text_and_criterion(self):
        with patch.object(judge, "_single_call", return_value=True) as call:
            for text, criterion in (("a", "b"), ("a", "c"), ("b", "b")):
                self.assertTrue(judge.llm_check(text, criterion))
            self.assertEqual(call.call_count, 6)
        self.assertNotEqual(judge._cache_key("prompt one", "mockllm/judge-a", 3),
                            judge._cache_key("prompt two", "mockllm/judge-a", 3))

    def test_invalid_votes_fail_before_cache_lookup_or_judge_call(self):
        for votes in ("0", "-1", "-2", "2", "4", "abc", "1.5", ""):
            with self.subTest(votes=votes), patch.dict(os.environ, {"LLM_CHECK_VOTES": votes}):
                with patch.object(judge, "_read_cache") as read, patch.object(judge, "_single_call") as call:
                    with self.assertRaisesRegex(ValueError, "positive odd integer"):
                        judge.llm_check("text", "Does it match?")
                    read.assert_not_called()
                    call.assert_not_called()

    def test_model_required_before_cache_lookup_and_explicit_override_works(self):
        with patch.dict(os.environ, {"LLM_CHECK_MODEL": ""}):
            with patch.object(judge, "_read_cache") as read:
                with self.assertRaisesRegex(RuntimeError, "no judge model"):
                    judge.llm_check("text", "Does it match?")
                read.assert_not_called()
            with patch.object(judge, "_single_call", return_value=True) as call:
                self.assertTrue(judge.llm_check("text", "Does it match?", model="mockllm/override"))
                self.assertEqual([args.args[0] for args in call.call_args_list],
                                 ["mockllm/override"] * 2)

    def test_legacy_disk_cache_is_ignored_and_preserved(self):
        text, criterion = "text", "Does it match?"
        key = hashlib.sha256(f"{criterion}\n---\n{text}".encode()).hexdigest()
        old_entry = self.cache_dir / f"{key}.json"
        contents = json.dumps({"result": True})
        old_entry.write_text(contents)
        with patch.object(judge, "_single_call", return_value=False) as call:
            self.assertFalse(judge.llm_check(text, criterion))
            self.assertEqual(call.call_count, 2)
        self.assertEqual(old_entry.read_text(), contents)

    def test_majority_voting_and_early_stop(self):
        with patch.dict(os.environ), patch.object(
            judge, "_single_call", side_effect=[True, False, True]
        ) as call:
            os.environ.pop("LLM_CHECK_VOTES", None)
            self.assertTrue(judge.llm_check("default votes", "Does it match?"))
            self.assertEqual(call.call_count, 3)
        cases = [
            (1, [True], True, 1),
            (3, [True, True, False], True, 2),
            (3, [False, False, True], False, 2),
            (3, [True, False, True], True, 3),
            (3, [False, True, False], False, 3),
            (5, [True, False, True, False, True], True, 5),
        ]
        for index, (votes, answers, result, calls) in enumerate(cases):
            with self.subTest(votes=votes, answers=answers), patch.dict(
                os.environ, {"LLM_CHECK_VOTES": str(votes)}
            ), patch.object(judge, "_single_call", side_effect=answers) as call:
                self.assertEqual(judge.llm_check(f"text {index}", "Does it match?"), result)
                self.assertEqual(call.call_count, calls)


if __name__ == "__main__":
    unittest.main()
