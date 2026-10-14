import hashlib
import importlib.util
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ENTRY = Path(__file__).resolve().parents[1] / "adapters/codex/market_gateway.py"
sys.path.insert(0, str(ENTRY.parent))
SPEC = importlib.util.spec_from_file_location("market_gateway", ENTRY)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


class Base:
    def __init__(self, data):
        self.data = data

    def _choose(self, need, candidates, purpose="skill"):
        return {"delegated": purpose}

    def request(self, operation, arguments):
        if arguments.get("revoked"):
            raise ValueError("access_revoked")
        return {"status": "none"}


class MarketGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.route = Mock(return_value={"status": "uncertain", "confidence": 0.4, "skill": None})
        self.config = {"version": 1, "minimum_confidence": 0.6}
        self.rows = {"abc": {"enabled": True, "snapshot": {"name": "Vercel", "repo": "vercel-labs/agent-skills"},
                             "skills": [{"path": "skills/react"}]} }
        self.module = SimpleNamespace(
            runtime=SimpleNamespace(Skill=lambda name, description, path: SimpleNamespace(name=name, description=description, path=path), _route=self.route),
            external_skills=SimpleNamespace(registry=lambda data: {"sources": self.rows}, sources=SimpleNamespace(
                BUILTINS=[{"repo": "vercel-labs/agent-skills", "about": "React and web development"}])),
            public_access=SimpleNamespace(owner_json=lambda path: self.config),
            backpack_provider_environment=SimpleNamespace(load=lambda data: {"XDG_CONFIG_HOME": "/provider"}),
        )
        self.router = gateway.make_router(Base, self.module)(self.data)

    def candidate(self, name="external-a", description="react: performance"):
        return self.module.runtime.Skill(name, description, Path("SKILL.md"))

    def test_directory_keeps_identity_order_members_and_describes_source(self):
        identity = "group-" + hashlib.sha256(b"abc:skills").hexdigest()[:48]
        rows = [self.candidate(identity, "skills: react, writing"), self.candidate("group-saved", "saved: local")]
        with patch("market_routing.route", return_value={"status": "uncertain"}) as select:
            answer = self.router._choose("review React", rows)
        args, kwargs = select.call_args
        self.assertEqual([r.name for r in args[2]], [r.name for r in rows])
        self.assertEqual(args[2][0].description, "Vercel (vercel-labs/agent-skills); React and web development; skills: react, writing")
        self.assertEqual(args[2][1].description, rows[1].description)
        self.assertEqual(args[3]["minimum_confidence"], 0.1)
        self.assertEqual(answer["selection_stage"], "directory")
        self.assertEqual(answer["status"], "uncertain")

    def test_final_stage_is_strict_and_retains_provider_environment(self):
        self.router._choose("review React", [self.candidate()])
        config = self.route.call_args.kwargs["config"]
        self.assertEqual(config["minimum_confidence"], 0.7)
        self.assertEqual(config["provider_environment"], {"XDG_CONFIG_HOME": "/provider"})

    def test_stricter_existing_threshold_is_preserved(self):
        (self.data / "config.json").touch()
        self.config["minimum_confidence"] = 0.9
        self.router._choose("review React", [self.candidate()])
        self.assertEqual(self.route.call_args.kwargs["config"]["minimum_confidence"], 0.9)

    def test_disabled_source_adds_no_description(self):
        self.rows["abc"]["enabled"] = False
        self.assertEqual(gateway.source_directory_descriptions(self.module, self.data), {})

    def test_mcp_and_resource_selection_remain_with_existing_gateway(self):
        for purpose in ("mcp-server", "mcp-tool", "resource"):
            self.assertEqual(self.router._choose("need", [self.candidate()], purpose), {"delegated": purpose})
        self.route.assert_not_called()

    def test_receipt_and_access_errors_are_not_bypassed(self):
        with self.assertRaisesRegex(ValueError, "access_revoked"):
            self.router.request("acquire", {"revoked": True})
        self.assertEqual(self.router.request("acquire", {})["routing_policy"], gateway.POLICY)
        with self.assertRaisesRegex(ValueError, "invalid_arguments"):
            self.router.request("resource", {})

    def test_invalid_threshold_stops_before_provider(self):
        (self.data / "config.json").touch()
        for key in ("minimum_confidence", "skill_minimum_confidence"):
            for value in (float("nan"), float("inf"), -1, 2):
                self.config = {"version": 1, "minimum_confidence": 0.6, key: value}
                with self.assertRaisesRegex(ValueError, "invalid_minimum_confidence"):
                    self.router._choose("need", [self.candidate()])
        self.route.assert_not_called()

    def test_launcher_loads_runtime_sibling_dependencies(self):
        scripts = self.data / "scripts"
        scripts.mkdir()
        (scripts / "market_probe_sibling.py").write_text("VALUE = 17\n")
        (scripts / "backpack_public_mcp.py").write_text(
            "import market_probe_sibling\nclass Router: pass\nVALUE = market_probe_sibling.VALUE\n"
        )
        before = list(sys.path)
        try:
            loaded = gateway.load_gateway(self.data)
            self.assertEqual(loaded.VALUE, 17)
            self.assertEqual(loaded.Router.__name__, "MarketRouter")
        finally:
            sys.path[:] = before
            sys.modules.pop("market_probe_sibling", None)
            sys.modules.pop("catmaster_market_base_gateway", None)


if __name__ == "__main__":
    unittest.main()
