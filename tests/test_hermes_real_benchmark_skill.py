from __future__ import annotations

import re
import unittest
from pathlib import Path


SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills/hermes/hermes-real-benchmark-testing/SKILL.md"
)


class HermesRealBenchmarkSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = SKILL_PATH.read_text(encoding="utf-8")

    def test_skill_has_discoverable_frontmatter(self) -> None:
        self.assertIn("name: hermes-real-benchmark-testing", self.content)
        self.assertRegex(
            self.content,
            r"description: Use when .*Hermes.*(Tool Backpack|tool_backpack|tool_repo|lazy tool surface)",
        )

    def test_skill_requires_fresh_real_llm_benchmark_for_hermes_optimizations(self) -> None:
        required_phrases = [
            "fresh real Hermes LLM benchmark",
            "historical JSONL is comparison evidence only",
            "Do not claim Hermes optimization is complete",
            "run-simple-tool-round.py",
            "benchmarks/accuracy-fixture",
            "answer_correct",
            "tool_calls",
            "initial_visible_tool_count",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.content)

    def test_skill_includes_runnable_standard_hm_benchmark_commands(self) -> None:
        self.assertIn("HERMES_HOME=/home/k/.hermes", self.content)
        self.assertIn("standard hm benchmark", self.content)
        self.assertIn("PYTHONPATH=/home/k/cccx/hermes/repos/hermes-agent", self.content)
        self.assertIn("--env hm-backpack", self.content)
        self.assertIn("--env hm-full", self.content)
        self.assertIn("--output", self.content)

    def test_skill_requires_matching_or_creating_comparison_groups(self) -> None:
        required_phrases = [
            "Before every benchmark, inspect the requested comparison surface",
            "Use standard `hm` configuration for production claims",
            "choose existing comparison groups that match the user request",
            "ask before deleting comparison groups",
            "create the missing comparison group",
            "validate each new Hermes home with a real chat response",
            "Do not run benchmark comparisons against mismatched groups",
            "/home/k/.hermes",
            "hm-backpack",
            "hm-full",
            "/home/k/cccx/tool/experiments/hermes-skill-ab/skill-backpack/.hermes",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.content)

    def test_skill_covers_production_hm_and_hm_full_backpack_smoke(self) -> None:
        required_phrases = [
            "Production hm Smoke",
            "/home/k/.local/bin/hm",
            "/home/k/.local/bin/hermes-main",
            "hm-full",
            "/home/k/cccx/tool/experiments/hermes-test/full-hm/bin/hm-full",
            "skill_backpack({\"request\":\"select <skill-name>\"})",
            "tool_backpack({\"request\":\"select <id|tool_name>\"})",
            "session JSON",
            "visible tool count",
            "final marker",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.content)

    def test_skill_requires_session_tool_call_evidence_for_hm_comparisons(self) -> None:
        required_phrases = [
            "Do not accept final text alone",
            "tool_backpack select",
            "skill_backpack select",
            "hm should start Backpack-only",
            "hm-full should not use Backpack gateways",
            "session path",
            "tool calls",
            "rough schema tokens",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.content)

    def test_frontmatter_description_stays_trigger_only(self) -> None:
        match = re.search(r"^description: (.+)$", self.content, re.MULTILINE)
        self.assertIsNotNone(match)
        description = match.group(1)
        self.assertTrue(description.startswith("Use when "))
        self.assertNotIn("run ", description.lower())
        self.assertLess(len(description), 500)


if __name__ == "__main__":
    unittest.main()
