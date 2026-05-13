from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SNAPSHOT_ROOT = Path(__file__).resolve().parents[1] / "adapters/hermes/tool-repo-snapshot"
sys.path.insert(0, str(SNAPSHOT_ROOT))

from agent.tool_repo import build_tool_prompt_index, build_tool_repo_schema, run_tool_repo_action  # noqa: E402
from agent.tool_repo_catalog import capabilities_for_tool  # noqa: E402


class ToolRepoActionTests(unittest.TestCase):
    def test_entry_tool_schema_uses_tool_backpack_name(self) -> None:
        schema = build_tool_repo_schema()

        self.assertEqual(schema["function"]["name"], "tool_backpack")
        self.assertEqual(schema["function"]["description"], "Tool gateway.")
        self.assertEqual(
            schema["function"]["parameters"]["properties"]["request"]["description"],
            "Use select <id|tool_name>[,<id|tool_name>...] only.",
        )

    def test_prompt_index_lists_selectable_tools(self) -> None:
        prompt_index = build_tool_prompt_index({"search_files", "read_file"})

        self.assertIn("Tool Backpack index:", prompt_index)
        self.assertIn("101: search_files", prompt_index)
        self.assertIn("102: read_file", prompt_index)
        self.assertNotIn("201: patch", prompt_index)
        self.assertIn("select <id|tool_name>[,<id|tool_name>...]", prompt_index)

    def test_repo_search_request_is_blocked_because_prompt_index_is_visible(self) -> None:
        response = run_tool_repo_action({"request": "search repo files"})

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["decision"], "blocked")
        self.assertIn("index is already visible", response["message"])
        self.assertNotIn("capability_id", response)
        self.assertNotIn("next_tools", response)

    def test_tool_index_includes_installed_catalog_tools(self) -> None:
        class Card:
            def __init__(self, name: str, installed: bool = True) -> None:
                self.name = name
                self.installed = installed

        class Catalog:
            def cards(self) -> list[Card]:
                return [Card("dynamic_tool"), Card("disabled_tool", installed=False)]

        with patch("agent.tool_repo.build_tool_catalog", return_value=Catalog()):
            prompt_index = build_tool_prompt_index()

        self.assertIn("dynamic_tool", prompt_index)
        self.assertNotIn("disabled_tool", prompt_index)

    def test_tool_index_omits_gateway_and_direct_skill_tools(self) -> None:
        class Card:
            def __init__(self, name: str, installed: bool = True) -> None:
                self.name = name
                self.installed = installed

        class Catalog:
            def cards(self) -> list[Card]:
                return [
                    Card("tool_backpack"),
                    Card("skill_backpack"),
                    Card("skill" + "_view"),
                    Card("skills" + "_list"),
                    Card("skill" + "_manage"),
                    Card("dynamic_tool"),
                ]

        with patch("agent.tool_repo.build_tool_catalog", return_value=Catalog()):
            prompt_index = build_tool_prompt_index()

        rows = prompt_index.splitlines()[1:]
        self.assertFalse(any(": tool_backpack " in row for row in rows))
        self.assertFalse(any(": skill_backpack " in row for row in rows))
        self.assertFalse(any(": " + "skill" + "_view " in row for row in rows))
        self.assertFalse(any(": " + "skills" + "_list " in row for row in rows))
        self.assertFalse(any(": " + "skill" + "_manage " in row for row in rows))
        self.assertIn("dynamic_tool", prompt_index)

    def test_select_tool_id_returns_selected_tool_name(self) -> None:
        response = run_tool_repo_action({"request": "select 101"})

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["decision"], "select_tool")
        self.assertEqual(response["d"], "selected")
        self.assertEqual(response["id"], 101)
        self.assertEqual(response["tool"], "search_files")
        self.assertEqual(response["next"], "call search_files")

    def test_select_tool_name_returns_selected_tool_name(self) -> None:
        response = run_tool_repo_action({"request": "select search_files"})

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["decision"], "select_tool")
        self.assertEqual(response["d"], "selected")
        self.assertEqual(response["tool"], "search_files")
        self.assertEqual(response["next"], "call search_files")

    def test_bare_tool_id_returns_selected_tool_name(self) -> None:
        response = run_tool_repo_action({"request": "101"})

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["decision"], "select_tool")
        self.assertEqual(response["tool"], "search_files")

    def test_multiple_bare_tool_ids_return_selected_tools(self) -> None:
        response = run_tool_repo_action({"request": "101,102"})

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["decision"], "select_tools")
        self.assertEqual(response["tools"], ["search_files", "read_file"])
        self.assertEqual(response["next"], "call selected tools")

    def test_direct_named_search_files_request_is_blocked_not_routed(self) -> None:
        response = run_tool_repo_action({"request": "search_files(pattern='OMEGA_RAVEN_314159')"})

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["decision"], "blocked")
        self.assertIn("select <id|tool_name>", response["message"])

    def test_shellish_listing_request_is_blocked_with_search_guidance(self) -> None:
        response = run_tool_repo_action({"request": "ls -R"})

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["decision"], "blocked")
        self.assertIn("select search_files", response["message"])

    def test_cat_request_is_blocked_with_read_guidance(self) -> None:
        response = run_tool_repo_action({"request": "cat README.md"})

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["decision"], "blocked")
        self.assertIn("select read_file", response["message"])

    def test_installer_requests_are_blocked_not_router_decisions(self) -> None:
        install = run_tool_repo_action({"request": "install search_files"})
        remove = run_tool_repo_action({"request": "remove read_file"})

        self.assertEqual(install["decision"], "blocked")
        self.assertEqual(remove["decision"], "blocked")

    def test_host_orchestration_tool_stays_unknown_even_with_repo_schema(self) -> None:
        schema = {
            "description": "Delegate task to an agent that can search files in the workspace.",
            "parameters": {
                "properties": {
                    "goal": {"description": "Search repo files and report results."},
                }
            },
        }

        self.assertEqual(capabilities_for_tool("delegate_task", schema), ["unknown"])

    def test_protocol_records_advisor_selectors_do_not_route_semantically(self) -> None:
        protocol = (Path(__file__).resolve().parents[1] / "core/protocol.md").read_text()

        self.assertIn("## Advisor Selectors", protocol)
        self.assertIn("`select <tool_name>`", protocol)
        self.assertIn("`select search_files`", protocol)
        self.assertIn("Do not call index/list or guess selector names", protocol)
        self.assertIn("Do not semantically route requests inside `tool_backpack`", protocol)
        self.assertIn("In advisor-selector mode, block non-selection requests", protocol)
        self.assertIn("Do not expose indexed tools after an optional `tool_index`", protocol)
        self.assertIn("\"decision\": \"select_tools\"", protocol)

    def test_show_tools_is_blocked_because_prompt_index_is_visible(self) -> None:
        response = run_tool_repo_action({"request": "show tools"})

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["decision"], "blocked")
        self.assertIn("index is already visible", response["message"])

    def test_uninstall_request_is_blocked(self) -> None:
        response = run_tool_repo_action({"request": "remove playwright"})

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["decision"], "blocked")


if __name__ == "__main__":
    unittest.main()
