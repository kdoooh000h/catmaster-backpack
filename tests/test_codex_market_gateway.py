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
        with patch("market_routing.route", return_value={"status": "none"}) as select:
            self.router._choose("review React", [self.candidate()])
        config = select.call_args.args[3]
        self.assertEqual(config["minimum_confidence"], 0.7)
        self.assertEqual(config["provider_environment"], {"XDG_CONFIG_HOME": "/provider"})
        self.assertEqual(select.call_args.args[4], "skill")

    def test_bound_single_plugin_uses_actual_guidance_once_at_strict_threshold(self):
        self.router.allowed={'bound-key'}
        self.router.market_guidance_context={}
        row=self.candidate('bound-key')
        evidence=self.module.runtime.Skill('bound-key','Complete selected plugin entrypoint',Path('SKILL.md'))
        with patch.object(gateway,'public_skill_evidence',return_value=[evidence]), \
                patch('market_routing.route',return_value={'status':'uncertain','confidence':.69}) as select:
            result=self.router._choose('Review a local file',[row])
        self.assertEqual(select.call_count,1)
        self.assertEqual(select.call_args.args[2],[evidence])
        self.assertEqual(select.call_args.args[3]['minimum_confidence'],.7)
        self.assertEqual(select.call_args.args[4],'plugin-ready')
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(result['evidence_mode'],'complete_bound_plugin_entrypoint')

    def test_bound_plugin_without_complete_evidence_does_not_fall_back_to_metadata(self):
        self.router.allowed={'bound-key'}
        self.router.market_guidance_context={}
        with patch.object(gateway,'public_skill_evidence',return_value=[]), \
                patch('market_routing.route') as select:
            result=self.router._choose('Review a file',[self.candidate('bound-key')])
        self.assertEqual(result['status'],'unsupported')
        select.assert_not_called()

    def test_exact_prepared_need_reuses_valid_fit_but_not_a_stricter_or_changed_need(self):
        self.router.allowed={'bound-key'}
        self.router.access=SimpleNamespace(scope='project')
        self.router._item=Mock(return_value=({},Path('.')))
        self.router.market_guidance_context={'keys':['bound-key'],'need':'same original task',
            'validation':{'status':'selected','confidence':.8}}
        row=self.candidate('bound-key')
        with patch('market_routing.route') as select:
            result=self.router._choose('same original task',[row])
        self.assertTrue(result['validation_reused'])
        select.assert_not_called()
        self.router._item.assert_called_once_with('bound-key','project')
        for need,minimum in [('changed purpose',.7),('same original task',.9)]:
            with self.subTest(need=need,minimum=minimum):
                (self.data/'config.json').touch();self.config['minimum_confidence']=minimum
                with patch.object(gateway,'public_skill_evidence',return_value=[row]), \
                        patch('market_routing.route',return_value={'status':'none','confidence':.95}) as select:
                    result=self.router._choose(need,[row])
                self.assertNotIn('validation_reused',result)
                self.assertEqual(select.call_args.args[3]['minimum_confidence'],minimum)

    def test_reused_fit_still_checks_access_before_disclosure(self):
        self.router.allowed={'bound-key'};self.router.access=SimpleNamespace(scope='project')
        self.router.market_guidance_context={'keys':['bound-key'],'need':'task',
            'validation':{'status':'selected','confidence':.8}}
        self.router._item=Mock(side_effect=ValueError('access_revoked'))
        with patch('market_routing.route') as select,self.assertRaisesRegex(ValueError,'access_revoked'):
            self.router._choose('task',[self.candidate('bound-key')])
        select.assert_not_called()

    def test_stricter_existing_threshold_is_preserved(self):
        (self.data / "config.json").touch()
        self.config["minimum_confidence"] = 0.9
        with patch("market_routing.route", return_value={"status": "none"}) as select:
            self.router._choose("review React", [self.candidate()])
        self.assertEqual(select.call_args.args[3]["minimum_confidence"], 0.9)

    def test_disabled_source_adds_no_description(self):
        self.rows["abc"]["enabled"] = False
        self.assertEqual(gateway.source_directory_descriptions(self.module, self.data), {})

    def test_mcp_and_resource_selection_remain_with_existing_gateway(self):
        for purpose in ("mcp-server", "mcp-tool", "resource"):
            self.assertEqual(self.router._choose("need", [self.candidate()], purpose), {"delegated": purpose})
        self.route.assert_not_called()

    def test_ambiguous_public_examples_require_actual_content_fit(self):
        resource=self.data/'public-cache/key/skill/themes/example.md';resource.parent.mkdir(parents=True)
        resource.write_text('Colors: #E2AC31, #171717, #FFF3D0. Use a readable body font.')
        self.module.public_access.safe=lambda path:path
        candidate=self.module.runtime.Skill('themes/example.md','Theme example',resource)
        with patch('market_routing.route',side_effect=[
            {'status':'selected','skill':candidate.name,'confidence':.33},
            {'status':'selected','skill':candidate.name,'confidence':.95}]) as select:
            result=self.router._choose('prepare several distinct themes',[candidate],purpose='resource')
        self.assertEqual(result['confidence'],.95)
        self.assertEqual(select.call_args_list[0].args[3]['minimum_confidence'],.1)
        self.assertEqual(select.call_args_list[1].args[3]['minimum_confidence'],.7)
        self.assertIn('#E2AC31',select.call_args_list[1].args[2][0].description)

    def test_evidence_refinement_never_truncates_a_large_shortlist(self):
        self.assertEqual(gateway.public_skill_evidence(self.router,self.module,[],list('abcdefghi')),[])

    def test_binary_resource_uses_bounded_extracted_text_and_containing_guide(self):
        resource=self.data/'public-cache/key/skill/showcase.pdf';resource.parent.mkdir(parents=True)
        resource.write_bytes(b'%PDF-1.7\x80')
        (resource.parent/'SKILL.md').write_text('Show showcase.pdf for theme examples.')
        self.module.public_access.safe=lambda path:path
        candidate=self.module.runtime.Skill('showcase.pdf','Theme showcase',resource)
        def extract(argv, **kwargs):
            self.assertEqual(argv[1:], [str(resource), '-'])
            self.assertEqual(kwargs['timeout'],5)
            kwargs['stdout'].write(b'Autumn theme: warm amber and dark brown.')
            return SimpleNamespace(returncode=0)
        with patch('market_routing.route',side_effect=[
            {'status':'selected','skill':candidate.name,'confidence':.4},
            {'status':'selected','skill':candidate.name,'confidence':.9}]) as select, \
                patch.object(gateway.shutil,'which',return_value='/local/pdftotext'), \
                patch.object(gateway.subprocess,'run',side_effect=extract):
            self.router._choose('Get the local showcase path',[candidate],purpose='resource')
        evidence=select.call_args.args[2][0].description
        self.assertIn('Autumn theme',evidence)
        self.assertIn('Show showcase.pdf',evidence)
        self.assertIn('Verified local file',evidence)
        self.assertEqual(resource.read_bytes(),b'%PDF-1.7\x80')

    def test_binary_extractor_failure_does_not_invent_resource_content(self):
        resource=self.data/'public-cache/key/skill/showcase.pdf';resource.parent.mkdir(parents=True)
        resource.write_bytes(b'%PDF-1.7\x80')
        self.module.public_access.safe=lambda path:path
        candidate=self.module.runtime.Skill('showcase.pdf','Theme showcase',resource)
        with patch('market_routing.route',side_effect=[
            {'status':'selected','skill':candidate.name,'confidence':.4},
            {'status':'uncertain','skill':None,'confidence':.4}]) as select, \
                patch.object(gateway.shutil,'which',return_value='/local/pdftotext'), \
                patch.object(gateway.subprocess,'run',side_effect=gateway.subprocess.TimeoutExpired('pdftotext',5)):
            result=self.router._choose('Find a theme palette',[candidate],purpose='resource')
        self.assertEqual(result['status'],'uncertain')
        self.assertNotIn('extracted_pdf_text',select.call_args.args[2][0].description)

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
