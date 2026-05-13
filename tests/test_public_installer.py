import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
sys.path.insert(0, str(ROOT / "src"))


class PublicInstallerTests(unittest.TestCase):
    def test_package_exposes_public_cli(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["scripts"]["catmaster-backpack"], "catmaster_backpack.installer:main")
        self.assertIn("README.md", pyproject["project"]["readme"])
        self.assertEqual(pyproject["project"]["license"]["text"], "MIT")
        package_data = pyproject["tool"]["setuptools"]["package-data"]["catmaster_backpack"]
        self.assertIn("data/skills/skill-backpack/SKILL.md", package_data)
        self.assertIn("data/skills/skill-backpack/tools/*.py", package_data)
        self.assertIn("data/adapters/*/*", package_data)

    def test_skill_plugin_install_uses_packaged_assets_without_source_checkout(self):
        from catmaster_backpack import installer

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing packaged assets.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "codex",
                    "--project-root",
                    str(project),
                    "--source",
                    str(source.parent),
                ],
                cwd=ROOT,
                env={**ENV, "CATMASTER_BACKPACK_FORCE_PACKAGED_ASSETS": "1"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["agent"], "codex")
            self.assertEqual(payload["asset_source"], "packaged")
            self.assertTrue((project / ".codex" / "skills" / "skill-backpack" / "SKILL.md").exists())
            self.assertTrue((project / ".codex" / "skills" / "skill-backpack" / "tools" / "skill_backpack.py").exists())
            self.assertIn("# CatMaster Backpack For Codex", (project / "AGENTS.md").read_text(encoding="utf-8"))
            manifest = json.loads((project / ".codex" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])

    def test_hermes_install_preserves_canonical_home_source_path(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            hermes_home = Path(directory) / ".hermes"
            source = hermes_home / "skills"
            skill = source / "mcp" / "tool-installer" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: tool-installer\ndescription: Use when installing MCP tools.\n---\n\n# Tool Installer\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "hermes",
                    "--project-root",
                    str(project),
                    "--source",
                    str(source),
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((project / ".hermes" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["modules"]["tool-installer"]["source_path"], "skills/mcp/tool-installer/SKILL.md")

    def test_hermes_install_keeps_explicit_source_path_relative_to_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "skills-src"
            skill = source / "debug-helper" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: debug-helper\ndescription: Use when debugging explicit source imports.\n---\n\n# Debug Helper\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "hermes",
                    "--project-root",
                    str(project),
                    "--source",
                    str(source),
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((project / ".hermes" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["modules"]["debug-helper"]["source_path"], "debug-helper/SKILL.md")

    def test_readme_documents_public_install_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Public Install", readme)
        self.assertIn("pip install -e .", readme)
        self.assertIn("catmaster-backpack install-skill-plugin", readme)
        self.assertIn("catmaster-backpack-mcp", readme)
        self.assertIn("packaged adapter assets", readme)
        self.assertIn("Agent/runtime protocol flow", readme)
        self.assertIn("End users do not run index/select manually", readme)
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
        self.assertIn("docs/host-adapter-verification-notes.md", readme)
        self.assertTrue((ROOT / "docs" / "demo.md").exists())
        self.assertTrue((ROOT / "docs" / "outreach.md").exists())
        self.assertTrue((ROOT / "docs" / "host-adapter-verification-notes.md").exists())

    def test_host_adapter_verification_notes_record_unvalidated_hosts(self):
        path = ROOT / "docs" / "host-adapter-verification-notes.md"

        self.assertTrue(path.exists())
        notes = path.read_text(encoding="utf-8")

        self.assertIn("# Host Adapter Verification Notes", notes)
        self.assertIn("As of 2026-05-12", notes)
        self.assertIn("packaged adapter assets and portable protocol guidance", notes)
        self.assertIn("not been validated with real runtime E2E smoke tests yet", notes)
        self.assertIn("Non-Hermes hosts must not be described as Hermes-equivalent", notes)
        self.assertIn("OpenClaw real testing is blocked", notes)

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

    def test_github_landing_page_publishes_backpack_v0(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        protocol = (ROOT / "core" / "protocol.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "skill-backpack" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Backpack System: v0", readme)
        self.assertIn("System version: v0", protocol)
        self.assertNotIn("native Hermes tool", skill)
        self.assertIn("host adapter provides a native `skill_backpack` tool", skill)
        self.assertNotIn("grouped-hints-v1", readme)
        self.assertNotIn("Advisor strategy version", protocol)
        self.assertNotIn("grouped-hints-v1", protocol)

    def test_readme_uses_conservative_adapter_roadmap(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Adapter Roadmap", readme)
        self.assertIn("CatMaster Backpack is currently validated on Hermes Agent", readme)
        self.assertIn("| OpenCode | Portable protocol and skill package only |", readme)
        self.assertIn("| Claude Code | Portable protocol and skill package only |", readme)
        self.assertIn("| Codex-style runtimes | Portable protocol and skill package only |", readme)
        self.assertIn("| OpenClaw | Portable protocol and skill package only |", readme)
        self.assertIn("Do not treat non-Hermes hosts as Hermes-equivalent lazy native tool runtimes yet", readme)
        self.assertNotIn("## Package Direction", readme)
        self.assertNotIn("catmaster-backpack-opencode", readme)
        self.assertNotIn("catmaster-backpack-claude-code", readme)

    def test_opencode_adapter_includes_portable_project_guidance(self):
        snippet = ROOT / "adapters" / "opencode" / "AGENTS.md"
        tool_template = ROOT / "adapters" / "opencode" / "tools" / "tool_backpack.ts"

        self.assertTrue(snippet.exists())
        text = snippet.read_text(encoding="utf-8")
        self.assertIn(".opencode/skills/skill-backpack/", text)
        self.assertIn(".opencode/skill-backpack-tree/", text)
        self.assertIn("agent/runtime protocol flow", text)
        self.assertIn("Do not present index/select as an end-user workflow", text)
        self.assertIn("deterministic grouped advisor hints", text)
        self.assertIn("not Hermes-equivalent", text)
        self.assertIn("Do not claim dynamic native tool hiding", text)
        self.assertTrue(tool_template.exists())
        tool_text = tool_template.read_text(encoding="utf-8")
        self.assertIn("Tool gateway.", tool_text)
        self.assertIn("tool.schema.string()", tool_text)
        self.assertIn('decision: "tool_index"', tool_text)
        self.assertIn('decision: "select_tool"', tool_text)
        self.assertIn("id: selectedEntry.id", tool_text)
        self.assertIn("does not hide native OpenCode tools", tool_text)

    def test_claude_code_adapter_includes_portable_project_guidance(self):
        snippet = ROOT / "adapters" / "claude-code" / "CLAUDE.md"

        self.assertTrue(snippet.exists())
        text = snippet.read_text(encoding="utf-8")
        self.assertIn(".claude/skills/skill-backpack/", text)
        self.assertIn(".claude/skill-backpack-tree/", text)
        self.assertIn("agent/runtime protocol flow", text)
        self.assertIn("Do not present index/select as an end-user workflow", text)
        self.assertIn("optional MCP gateway", text)
        self.assertIn("optional hook guards", text)
        self.assertIn("not Hermes-equivalent", text)
        self.assertIn("Do not claim dynamic native tool hiding", text)

    def test_codex_adapter_includes_portable_project_guidance(self):
        snippet = ROOT / "adapters" / "codex" / "AGENTS.md"

        self.assertTrue(snippet.exists())
        text = snippet.read_text(encoding="utf-8")
        self.assertIn(".codex/skills/skill-backpack/", text)
        self.assertIn(".codex/skill-backpack-tree/", text)
        self.assertIn("agent/runtime protocol flow", text)
        self.assertIn("Do not present index/select as an end-user workflow", text)
        self.assertIn("Codex desktop", text)
        self.assertIn("optional MCP gateway", text)
        self.assertIn("optional plugin", text)
        self.assertIn("not Hermes-equivalent", text)
        self.assertIn("Do not claim dynamic native tool hiding", text)

    def test_openclaw_adapter_includes_portable_project_guidance(self):
        snippet = ROOT / "adapters" / "openclaw" / "AGENTS.md"

        self.assertTrue(snippet.exists())
        text = snippet.read_text(encoding="utf-8")
        self.assertIn(".openclaw/skills/skill-backpack/", text)
        self.assertIn(".openclaw/skill-backpack-tree/", text)
        self.assertIn("agent/runtime protocol flow", text)
        self.assertIn("Do not present index/select as an end-user workflow", text)
        self.assertIn("OpenClaw Tool Search", text)
        self.assertIn("optional plugin", text)
        self.assertIn("not Hermes-equivalent", text)
        self.assertIn("Do not claim dynamic native tool hiding", text)

    def test_readme_documents_hermes_runtime_manifest_as_single_package_entrypoint(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        adapter_readme = (ROOT / "adapters" / "hermes" / "README.md").read_text(encoding="utf-8")

        self.assertIn("## One-Repo Runtime Package", readme)
        self.assertIn("adapters/hermes/runtime-manifest.json", readme)
        self.assertIn("backpack-advisor-gateway", readme)
        self.assertIn("Tool Backpack + Skill Backpack + deterministic grouped advisor hints", readme)
        self.assertIn("runtime-manifest.json", adapter_readme)
        self.assertIn("d8e7b8be8e2ae1a41020a9d8ce518eb580dfd069", adapter_readme)

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
            self.assertIn("install_opencode_adapter_guidance", payload["operations"])
            self.assertIn("install_opencode_tool_backpack", payload["operations"])
            self.assertFalse((project / ".opencode").exists())

    def test_claude_code_skill_plugin_dry_run_lists_adapter_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing Claude Code dry run.\n---\n\n# Demo\n", encoding="utf-8")

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
            self.assertEqual(payload["agent"], "claude-code")
            self.assertIn("install_claude_code_guidance", payload["operations"])
            self.assertFalse((project / ".claude").exists())

    def test_codex_skill_plugin_dry_run_lists_adapter_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing Codex dry run.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "codex",
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
            self.assertEqual(payload["agent"], "codex")
            self.assertIn("install_codex_guidance", payload["operations"])
            self.assertFalse((project / ".codex").exists())

    def test_openclaw_skill_plugin_dry_run_lists_adapter_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing OpenClaw dry run.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "openclaw",
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
            self.assertEqual(payload["agent"], "openclaw")
            self.assertIn("install_openclaw_guidance", payload["operations"])
            self.assertFalse((project / ".openclaw").exists())

    def test_opencode_install_writes_adapter_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing OpenCode adapter install.\n---\n\n# Demo\n", encoding="utf-8")

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
            self.assertEqual(payload["agent"], "opencode")
            self.assertTrue((project / ".opencode" / "skills" / "skill-backpack" / "SKILL.md").exists())
            self.assertEqual(payload["installed_opencode_guidance"], str(project / "AGENTS.md"))
            self.assertEqual(payload["installed_opencode_tool_backpack"], str(project / ".opencode" / "tools" / "tool_backpack.ts"))
            self.assertIn("not Hermes-equivalent", (project / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("Tool gateway.", (project / ".opencode" / "tools" / "tool_backpack.ts").read_text(encoding="utf-8"))
            manifest = json.loads((project / ".opencode" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])

    def test_opencode_install_appends_existing_agents_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("# Existing Project Rules\n\nKeep this line.\n", encoding="utf-8")
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing OpenCode adapter install.\n---\n\n# Demo\n", encoding="utf-8")

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
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            text = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Existing Project Rules", text)
            self.assertIn("Keep this line.", text)
            self.assertEqual(text.count("# CatMaster Backpack For OpenCode"), 1)

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
            self.assertEqual(payload["installed_claude_code_guidance"], str(project / "CLAUDE.md"))
            self.assertIn("not Hermes-equivalent", (project / "CLAUDE.md").read_text(encoding="utf-8"))
            manifest = json.loads((project / ".claude" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])

    def test_claude_code_install_appends_existing_project_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            (project / "CLAUDE.md").write_text("# Existing Claude Rules\n\nKeep this line.\n", encoding="utf-8")
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing Claude Code guidance append.\n---\n\n# Demo\n", encoding="utf-8")

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
            text = (project / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("# Existing Claude Rules", text)
            self.assertIn("Keep this line.", text)
            self.assertEqual(text.count("# CatMaster Backpack For Claude Code"), 1)

    def test_codex_install_writes_adapter_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing Codex adapter install.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "codex",
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
            self.assertEqual(payload["agent"], "codex")
            self.assertTrue((project / ".codex" / "skills" / "skill-backpack" / "SKILL.md").exists())
            self.assertEqual(payload["installed_codex_guidance"], str(project / "AGENTS.md"))
            self.assertIn("not Hermes-equivalent", (project / "AGENTS.md").read_text(encoding="utf-8"))
            manifest = json.loads((project / ".codex" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])

    def test_codex_install_appends_existing_agents_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("# Existing Codex Rules\n\nKeep this line.\n", encoding="utf-8")
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing Codex guidance append.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "codex",
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
            text = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Existing Codex Rules", text)
            self.assertIn("Keep this line.", text)
            self.assertEqual(text.count("# CatMaster Backpack For Codex"), 1)

    def test_openclaw_install_writes_adapter_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing OpenClaw adapter install.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "openclaw",
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
            self.assertEqual(payload["agent"], "openclaw")
            self.assertTrue((project / ".openclaw" / "skills" / "skill-backpack" / "SKILL.md").exists())
            self.assertEqual(payload["installed_openclaw_guidance"], str(project / "AGENTS.md"))
            self.assertIn("not Hermes-equivalent", (project / "AGENTS.md").read_text(encoding="utf-8"))
            manifest = json.loads((project / ".openclaw" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])

    def test_openclaw_install_appends_existing_agents_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("# Existing OpenClaw Rules\n\nKeep this line.\n", encoding="utf-8")
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing OpenClaw guidance append.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "openclaw",
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
            text = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Existing OpenClaw Rules", text)
            self.assertIn("Keep this line.", text)
            self.assertEqual(text.count("# CatMaster Backpack For OpenClaw"), 1)

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
            self.assertEqual(payload["runtime_manifest"], "adapters/hermes/runtime-manifest.json")
            self.assertEqual(payload["runtime_source"]["repository"], "https://github.com/kdoooh000h/hermes-agent.git")
            self.assertEqual(payload["runtime_source"]["branch"], "backpack-advisor-gateway")
            self.assertEqual(payload["runtime_source"]["backpack_system_version"], "v0")
            self.assertIn("tools/tool_backpack.py", payload["runtime_files"])
            self.assertIn("agent/backpack_advisor.py", payload["runtime_files"])
            self.assertFalse(hermes_root.exists())
            self.assertFalse(hermes_home.exists())

    def test_hermes_adapter_manifest_packages_full_backpack_v0_runtime(self):
        manifest_path = ROOT / "adapters" / "hermes" / "runtime-manifest.json"

        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["adapter"], "hermes")
        self.assertEqual(manifest["backpack_system_version"], "v0")
        self.assertEqual(manifest["runtime_source"]["repository"], "https://github.com/kdoooh000h/hermes-agent.git")
        self.assertEqual(manifest["runtime_source"]["branch"], "backpack-advisor-gateway")
        self.assertEqual(manifest["runtime_source"]["commit"], "d8e7b8be8e2ae1a41020a9d8ce518eb580dfd069")
        self.assertEqual(
            manifest["integrated_parts"],
            ["tool_backpack", "skill_backpack", "deterministic_grouped_advisor_hints"],
        )
        self.assertIn("agent/backpack_advisor.py", manifest["runtime_files"])
        self.assertIn("tools/tool_backpack.py", manifest["runtime_files"])
        self.assertIn("tools/skill_backpack.py", manifest["runtime_files"])
        self.assertIn("tools/skills_sync.py", manifest["runtime_files"])

    def test_hermes_manifest_packaged_data_matches_adapter_manifest(self):
        source_manifest = ROOT / "adapters" / "hermes" / "runtime-manifest.json"
        packaged_manifest = ROOT / "src" / "catmaster_backpack" / "data" / "hermes" / "runtime-manifest.json"

        self.assertTrue(packaged_manifest.exists())
        self.assertEqual(
            json.loads(packaged_manifest.read_text(encoding="utf-8")),
            json.loads(source_manifest.read_text(encoding="utf-8")),
        )

    def test_hermes_plan_can_read_packaged_manifest_without_source_assets(self):
        from catmaster_backpack import installer

        with patch.object(installer, "_package_root", side_effect=RuntimeError("no source checkout")):
            manifest, reference = installer._load_hermes_runtime_manifest()

        self.assertEqual(manifest["adapter"], "hermes")
        self.assertEqual(reference, "catmaster_backpack:data/hermes/runtime-manifest.json")
        self.assertEqual(manifest["backpack_system_version"], "v0")
        self.assertIn("tools/tool_backpack.py", manifest["runtime_files"])

    def test_hermes_plan_falls_back_when_source_manifest_is_missing(self):
        from catmaster_backpack import installer

        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            with patch.object(installer, "_package_root", return_value=source_root):
                manifest, reference = installer._load_hermes_runtime_manifest()

        self.assertEqual(manifest["adapter"], "hermes")
        self.assertEqual(reference, "catmaster_backpack:data/hermes/runtime-manifest.json")

    def test_hermes_plan_reports_packaged_manifest_reference_for_fallback(self):
        from argparse import Namespace
        from contextlib import redirect_stdout
        from io import StringIO

        from catmaster_backpack import installer

        output = StringIO()
        with patch.object(installer, "_package_root", side_effect=RuntimeError("no source checkout")):
            with redirect_stdout(output):
                result = installer.hermes_plan(
                    Namespace(hermes_agent_root="/tmp/hermes-agent", hermes_home="/tmp/hermes-home")
                )

        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["runtime_manifest"], "catmaster_backpack:data/hermes/runtime-manifest.json")

    def test_hermes_adapter_readme_runtime_files_match_manifest(self):
        adapter_readme = (ROOT / "adapters" / "hermes" / "README.md").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "adapters" / "hermes" / "runtime-manifest.json").read_text(encoding="utf-8"))

        for runtime_file in manifest["runtime_files"]:
            self.assertIn(runtime_file, adapter_readme)
        self.assertNotIn("agent/tool_repo.py", adapter_readme)
        self.assertNotIn("agent/tool_repo_catalog.py", adapter_readme)
        self.assertNotIn("agent/tool_repo_registry.py", adapter_readme)


if __name__ == "__main__":
    unittest.main()
