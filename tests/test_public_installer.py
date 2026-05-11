import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


class PublicInstallerTests(unittest.TestCase):
    def test_package_exposes_public_cli(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["scripts"]["catmaster-backpack"], "catmaster_backpack.installer:main")
        self.assertIn("README.md", pyproject["project"]["readme"])
        self.assertEqual(pyproject["project"]["license"]["text"], "MIT")

    def test_readme_documents_public_install_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Public Install", readme)
        self.assertIn("pip install -e .", readme)
        self.assertIn("catmaster-backpack install-skill-plugin", readme)
        self.assertIn("Hermes full runtime integration is not a pure plugin", readme)

    def test_github_landing_page_materials_exist(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for section in [
            "## Why It Exists",
            "## Quick Demo",
            "## Supported Hosts",
            "## Architecture",
            "## Limitations",
        ]:
            self.assertIn(section, readme)
        self.assertIn("tool_backpack -> search_files/read_file", readme)
        self.assertIn("docs/demo.md", readme)
        self.assertIn("docs/outreach.md", readme)
        self.assertTrue((ROOT / "docs" / "demo.md").exists())
        self.assertTrue((ROOT / "docs" / "outreach.md").exists())

    def test_readme_explains_value_and_measured_context_savings(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## What It Saves", readme)
        self.assertIn("655", readme)
        self.assertIn("25,514", readme)
        self.assertIn("97.4%", readme)
        self.assertIn("reduces visible tool and skill surface area", readme)
        self.assertIn("less context describing capabilities", readme)

    def test_latest_current_benchmark_is_the_published_measurement(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        latest = ROOT / "benchmarks" / "results" / "current-hermes-surface-2026-05-11.md"

        self.assertTrue(latest.exists())
        latest_text = latest.read_text(encoding="utf-8")
        self.assertIn("655", latest_text)
        self.assertIn("25,514", latest_text)
        self.assertIn("97.4%", latest_text)
        self.assertIn("HTTP 403", latest_text)
        self.assertIn("current-hermes-surface-2026-05-11.md", readme)
        self.assertNotIn("Historical token benchmark", readme)

    def test_fresh_real_benchmark_result_is_published_with_caveats(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        benchmark_index = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
        result = ROOT / "benchmarks" / "results" / "current-hermes-real-benchmark-2026-05-11.md"

        self.assertTrue(result.exists())
        result_text = result.read_text(encoding="utf-8")
        self.assertIn("12/12", result_text)
        self.assertIn("62,303", result_text)
        self.assertIn("197,261", result_text)
        self.assertIn("68.4% fewer total tokens", result_text)
        self.assertIn("47.5% slower", result_text)
        self.assertIn("hm-backpack-real-llm-20260511.jsonl", result_text)
        self.assertIn("hm-full-real-llm-20260511.jsonl", result_text)
        self.assertIn("current-hermes-real-benchmark-2026-05-11.md", readme)
        self.assertIn("current-hermes-real-benchmark-2026-05-11.md", benchmark_index)

    def test_github_landing_page_has_promotional_pitch_and_tradeoff(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Why Share It", readme)
        self.assertIn("Agent tools are eating the context window", readme)
        self.assertIn("68.4% fewer total tokens", readme)
        self.assertIn("68.8% fewer prompt tokens", readme)
        self.assertIn("92.0% fewer initially visible tools", readme)
        self.assertIn("Tradeoff", readme)
        self.assertIn("47.5% slower", readme)

    def test_github_landing_page_has_designed_hero_and_signal_board(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Lazy capability surface for agent runtimes", readme)
        self.assertIn("## Signal Board", readme)
        self.assertIn("<table>", readme)
        self.assertIn("68.4% fewer total tokens", readme)
        self.assertIn("97.4% fewer initial tool-schema chars", readme)
        self.assertIn("## Use It When", readme)
        self.assertIn("tool catalogs are crowding the prompt", readme)
        self.assertIn("## Tradeoff", readme)
        self.assertIn("explicit gateway-selection round", readme)

    def test_github_landing_page_typography_is_polished_for_readme_limits(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("<sub>FOR RUNTIME MAINTAINERS", readme)
        self.assertIn("<h1 align=\"center\">CatMaster Backpack</h1>", readme)
        self.assertIn("<img alt=\"Status: Hermes prototype\"", readme)
        self.assertIn("<img alt=\"Benchmark: 68.4% fewer tokens\"", readme)
        self.assertIn("<th align=\"left\">Metric</th>", readme)
        self.assertIn("<code>tool_backpack</code> / <code>skill_backpack</code>", readme)
        self.assertIn("<sup>Measured on standard hm configuration", readme)

    def test_readme_uses_conservative_adapter_roadmap(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Adapter Roadmap", readme)
        self.assertIn("CatMaster Backpack is currently validated on Hermes Agent", readme)
        self.assertIn("| OpenCode | Portable protocol and skill package only |", readme)
        self.assertIn("| Claude Code | Portable protocol and skill package only |", readme)
        self.assertIn("| OpenClaw | Not implemented |", readme)
        self.assertIn("Do not treat non-Hermes hosts as Hermes-equivalent lazy native tool runtimes yet", readme)
        self.assertNotIn("## Package Direction", readme)
        self.assertNotIn("catmaster-backpack-opencode", readme)
        self.assertNotIn("catmaster-backpack-claude-code", readme)

    def test_outreach_templates_include_current_benchmark_claims(self):
        outreach = (ROOT / "docs" / "outreach.md").read_text(encoding="utf-8")

        self.assertIn("68.4% fewer total tokens", outreach)
        self.assertIn("68.8% fewer prompt tokens", outreach)
        self.assertIn("2 vs 25 initial visible tools", outreach)
        self.assertIn("47.5% slower", outreach)
        self.assertIn("standard hm configuration", outreach)
        self.assertIn("Show HN", outreach)

    def test_old_benchmark_records_are_not_published(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        benchmark_index = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")

        self.assertFalse((ROOT / "benchmarks" / "results" / "cat-master-toolkit-v1-final.md").exists())
        self.assertFalse((ROOT / "benchmarks" / "results" / "skill-backpack-comparison-2026-04-28.md").exists())
        for text in [readme, benchmark_index]:
            self.assertNotIn("2026-04-25", text)
            self.assertNotIn("2026-04-28", text)
            self.assertNotIn("cat-master-toolkit-v1-final.md", text)
            self.assertNotIn("skill-backpack-comparison-2026-04-28.md", text)
            self.assertNotIn("28,673", text)
            self.assertNotIn("13,602", text)
            self.assertNotIn("52.6%", text)
            self.assertNotIn("62.7%", text)

    def test_readme_leads_with_latest_local_experiment_conclusion(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Latest Local Experiment Conclusion", readme)
        self.assertIn("latest standard Hermes benchmark shows both context reduction and real token savings", readme)
        self.assertIn("68.4% fewer total tokens", readme)
        self.assertIn("standard `hm` Backpack matched `hm-full` accuracy at 12/12", readme)
        self.assertIn("47.5% slower", readme)

    def test_skill_plugin_dry_run_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing public install.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "opencode",
                    "--project-root",
                    str(project),
                    "--source",
                    str(source.parent),
                    "--dry-run",
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["agent"], "opencode")
            self.assertIn("install_parent_skill", payload["operations"])
            self.assertFalse((project / ".opencode").exists())

    def test_skill_plugin_install_writes_project_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing public install.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "claude-code",
                    "--project-root",
                    str(project),
                    "--source",
                    str(source.parent),
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "installed")
            self.assertEqual(payload["agent"], "claude-code")
            self.assertTrue((project / ".claude" / "skills" / "skill-backpack" / "SKILL.md").exists())
            manifest = json.loads((project / ".claude" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])

    def test_hermes_runtime_plan_is_explicit_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes_root = Path(directory) / "hermes-agent"
            hermes_home = Path(directory) / ".hermes"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "hermes-plan",
                    "--hermes-agent-root",
                    str(hermes_root),
                    "--hermes-home",
                    str(hermes_home),
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "manual_integration_required")
            self.assertEqual(payload["adapter"], "hermes")
            self.assertIn("tools/tool_backpack.py", payload["runtime_files"])
            self.assertIn("agent/backpack_advisor.py", payload["runtime_files"])
            self.assertFalse(hermes_root.exists())
            self.assertFalse(hermes_home.exists())


if __name__ == "__main__":
    unittest.main()
