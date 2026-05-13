import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catmaster_backpack import mcp_gateway


class McpGatewayTests(unittest.TestCase):
    def test_tools_list_exposes_backpack_gateways(self):
        response = mcp_gateway.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(response["id"], 1)
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertEqual(tools["tool_backpack"]["description"], "Tool gateway.")
        self.assertEqual(tools["skill_backpack"]["description"], "Skill gateway.")

    def test_tool_backpack_blocks_ordinary_index_and_empty_requests(self):
        index_response = mcp_gateway.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "tool_backpack", "arguments": {"request": "index"}},
            }
        )
        index_payload = json.loads(index_response["result"]["content"][0]["text"])
        self.assertEqual(index_payload["status"], "blocked")
        self.assertEqual(index_payload["decision"], "catalog_requires_explicit_mode")

        empty_response = mcp_gateway.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "tool_backpack", "arguments": {"request": ""}},
            }
        )
        empty_payload = json.loads(empty_response["result"]["content"][0]["text"])
        self.assertEqual(empty_payload["status"], "blocked")
        self.assertEqual(empty_payload["decision"], "needs_selection")

    def test_tool_backpack_returns_catalog_only_in_explicit_catalog_mode(self):
        index_response = mcp_gateway.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "tool_backpack", "arguments": {"request": "index", "catalog_mode": True}},
            }
        )
        index_payload = json.loads(index_response["result"]["content"][0]["text"])
        self.assertEqual(index_payload["decision"], "tool_index")
        self.assertIn([101, "search_files", "search names/content"], index_payload["tools"])

    def test_tool_backpack_returns_selection_decisions(self):

        select_response = mcp_gateway.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "tool_backpack", "arguments": {"request": "select 101"}},
            }
        )
        select_payload = json.loads(select_response["result"]["content"][0]["text"])
        self.assertEqual(select_payload["decision"], "select_tool")
        self.assertEqual(select_payload["id"], 101)
        self.assertEqual(select_payload["tool"], "search_files")
        self.assertIn("does not execute", select_payload["note"])

    def test_skill_backpack_catalog_requires_explicit_catalog_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            tree_root = Path(directory) / "skill-tree"
            module = tree_root / "modules" / "debug-helper"
            module.mkdir(parents=True)
            module.joinpath("SKILL.md").write_text(
                "---\nname: debug-helper\ndescription: Use when debugging tests.\n---\n\n# Debug Helper\n",
                encoding="utf-8",
            )
            tree_root.joinpath("manifest.json").write_text(
                json.dumps(
                    {
                        "tree": "test-tree",
                        "modules": {
                            "debug-helper": {
                                "status": "enabled",
                                "path": "modules/debug-helper/SKILL.md",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            index_response = mcp_gateway.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "skill_backpack",
                        "arguments": {"request": "index", "tree_root": str(tree_root)},
                    },
                }
            )
            index_payload = json.loads(index_response["result"]["content"][0]["text"])
            self.assertEqual(index_payload["status"], "blocked")
            self.assertEqual(index_payload["decision"], "catalog_requires_explicit_mode")

            catalog_response = mcp_gateway.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {
                        "name": "skill_backpack",
                        "arguments": {"request": "index", "tree_root": str(tree_root), "catalog_mode": True},
                    },
                }
            )
            catalog_payload = json.loads(catalog_response["result"]["content"][0]["text"])
            self.assertEqual(catalog_payload["decision"], "skill_index")
            self.assertEqual(catalog_payload["skills"], [[1, "debug-helper", "Use when debugging tests."]])

    def test_skill_backpack_selects_manifest_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            tree_root = Path(directory) / "skill-tree"
            module = tree_root / "modules" / "debug-helper"
            module.mkdir(parents=True)
            module.joinpath("SKILL.md").write_text(
                "---\nname: debug-helper\ndescription: Use when debugging tests.\n---\n\n# Debug Helper\n",
                encoding="utf-8",
            )
            tree_root.joinpath("manifest.json").write_text(
                json.dumps(
                    {
                        "tree": "test-tree",
                        "modules": {
                            "debug-helper": {
                                "status": "enabled",
                                "path": "modules/debug-helper/SKILL.md",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            select_response = mcp_gateway.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {
                        "name": "skill_backpack",
                        "arguments": {"request": "select 1", "tree_root": str(tree_root)},
                    },
                }
            )
            select_payload = json.loads(select_response["result"]["content"][0]["text"])
            self.assertEqual(select_payload["decision"], "select_skill")
            self.assertEqual(select_payload["skill"], "debug-helper")
            self.assertIn("# Debug Helper", select_payload["content"])

    def test_skill_backpack_catalog_mode_indexes_manifest_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            tree_root = Path(directory) / "skill-tree"
            module = tree_root / "modules" / "debug-helper"
            module.mkdir(parents=True)
            module.joinpath("SKILL.md").write_text(
                "---\nname: debug-helper\ndescription: Use when debugging tests.\n---\n\n# Debug Helper\n",
                encoding="utf-8",
            )
            tree_root.joinpath("manifest.json").write_text(
                json.dumps(
                    {
                        "tree": "test-tree",
                        "modules": {
                            "debug-helper": {
                                "status": "enabled",
                                "path": "modules/debug-helper/SKILL.md",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            index_response = mcp_gateway.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {
                        "name": "skill_backpack",
                        "arguments": {"request": "index", "tree_root": str(tree_root), "catalog_mode": True},
                    },
                }
            )
            index_payload = json.loads(index_response["result"]["content"][0]["text"])
            self.assertEqual(index_payload["decision"], "skill_index")
            self.assertEqual(index_payload["skills"], [[1, "debug-helper", "Use when debugging tests."]])

    def test_skill_backpack_blocks_manifest_paths_that_escape_tree_root(self):
        with tempfile.TemporaryDirectory() as directory:
            tree_root = Path(directory) / "skill-tree"
            outside = Path(directory) / "outside"
            outside.mkdir()
            outside.joinpath("SKILL.md").write_text("# Outside\n", encoding="utf-8")
            tree_root.mkdir()
            tree_root.joinpath("manifest.json").write_text(
                json.dumps(
                    {
                        "tree": "test-tree",
                        "modules": {
                            "escaped": {
                                "status": "enabled",
                                "path": "../outside/SKILL.md",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            index_response = mcp_gateway.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "skill_backpack",
                        "arguments": {"request": "index", "tree_root": str(tree_root), "catalog_mode": True},
                    },
                }
            )
            index_payload = json.loads(index_response["result"]["content"][0]["text"])
            self.assertEqual(index_payload["status"], "blocked")
            self.assertEqual(index_payload["decision"], "invalid_module_path")

            select_response = mcp_gateway.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {
                        "name": "skill_backpack",
                        "arguments": {"request": "select 1", "tree_root": str(tree_root)},
                    },
                }
            )
            select_payload = json.loads(select_response["result"]["content"][0]["text"])
            self.assertEqual(select_payload["status"], "blocked")
            self.assertEqual(select_payload["decision"], "invalid_module_path")


if __name__ == "__main__":
    unittest.main()
