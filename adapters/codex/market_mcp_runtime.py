"""Stage-aware MCP selection atop the existing receipt/execution runtime.

This changes discovery only. The original runtime owns clients, grants, call
receipts, unknown outcomes and shutdown; business dispatch is not reimplemented.
"""
import argparse
from contextvars import ContextVar
import importlib.util
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

POLICY = 'market-mcp-staged-v1'
MAX_TOOL_VALIDATIONS = 3
TOOL_SELECTION_BUDGET_SECONDS = 40


def configuration(data, module, *, final):
    path = Path(data)/'config.json'
    config = module.public_access.owner_json(path) if path.exists() else {
        'version':1, 'provider':'jev-cli', 'executable':shutil.which('jev'),
        'jev_provider':'typesafe', 'minimum_confidence':.6, 'timeout_seconds':15}
    if config.get('version') != 1:
        raise ValueError('invalid_config')
    values = [float(config.get(key, default)) for key, default in (
        ('directory_minimum_confidence',.1), ('minimum_confidence',.6), ('skill_minimum_confidence',.7))]
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError('invalid_minimum_confidence')
    config = {**config, 'minimum_confidence':max(.7,*values[1:]) if final else values[0],
              'timeout_seconds':min(15,float(config.get('timeout_seconds',15)))}
    import backpack_provider_environment
    environment = backpack_provider_environment.load(data)
    if environment is not None:
        config['provider_environment'] = environment
    return config


def validation_binding(need, result):
    value = {'need':need, **{key:result.get(key) for key in ('selection','server','tool')}}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def reusable_validation(need, result, minimum):
    fit = result.get('validation', {})
    return (result.get('routing_policy') == POLICY
        and result.get('validation_binding') == validation_binding(need,result)
        and isinstance(fit,dict) and fit.get('status') == 'selected'
        and isinstance(fit.get('confidence'),(float,int)) and math.isfinite(fit['confidence'])
        and minimum <= fit['confidence'] <= 1
        and isinstance(fit.get('minimum_confidence'),(float,int))
        and minimum <= fit['minimum_confidence'] <= 1)


def install_selection(module):
    from market_routing import route
    base_router, base_runtime = module.Router, module.Runtime
    inspected_tools = ContextVar('market_inspected_mcp_tools', default=None)

    class BoundedRuntime:
        # The fallback budget belongs to this request, not mutable global runtime
        # settings. Provider failures stop this search instead of trying a leaf.
        MAX_PROVIDER_ATTEMPTS = 1
        def __init__(self, remaining):
            self.ROUTING_BUDGET_SECONDS = remaining
        def __getattr__(self, name):
            return getattr(module.runtime,name)

    class InspectingClient:
        def __init__(self,client):
            self.client = client
        def tools(self):
            tools = self.client.tools()
            inspected_tools.get()['tools'] = tools
            return tools
        def __getattr__(self,name):
            return getattr(self.client,name)

    class Router(base_router):
        def validated_tool(self, need, candidates, tools, state):
            remaining = list(candidates)
            rejected = []
            deadline = time.monotonic()+TOOL_SELECTION_BUDGET_SECONDS
            provisional = configuration(self.data,module,final=False)
            strict = configuration(self.data,module,final=True)

            def search_result(result, *, budget=False):
                return {**result, 'phase':'actual_tool_validation', 'execution':'not_performed',
                        'rejected_tools':rejected, 'remaining_candidates':len(remaining),
                        'search_exhausted':not remaining, 'unexhausted':bool(remaining),
                        **({'reason':'tool_validation_budget_exhausted'} if budget else {})}

            def decide(rows, config, stage):
                seconds = deadline-time.monotonic()
                if seconds <= 0:
                    return None
                return route(BoundedRuntime(seconds),need,rows,
                    {**config,'timeout_seconds':min(config['timeout_seconds'],seconds)},stage)

            while remaining and len(rejected) < MAX_TOOL_VALIDATIONS:
                ranking = decide(remaining,provisional,'mcp-tool-preview')
                if ranking is None:
                    return search_result({'status':'uncertain'},budget=True)
                if ranking.get('status') != 'selected':
                    return search_result(ranking)
                selected = next((row for row in remaining if row.name == ranking.get('skill')),None)
                if selected is None:
                    raise ValueError('invalid_tool_choice')
                tool = tools[selected.name]
                description = json.dumps({'server':state.get('server'),'tool':tool},ensure_ascii=False)
                if len(description) > 24000:
                    fit = {'status':'unsupported','reason':'tool_schema_too_large'}
                else:
                    fit = decide([module.runtime.Skill('tool',description,Path('.'))],strict,'mcp-fit')
                    if fit is None:
                        return search_result({'status':'uncertain'},budget=True)
                    fit = {key:value for key,value in fit.items() if key != 'skill'}
                    fit['minimum_confidence'] = strict['minimum_confidence']
                if fit.get('status') == 'selected':
                    state['validation'] = {'tool':tool,'fit':fit,'rejected_tools':rejected}
                    return ranking
                # Only a completed negative fit rejects this leaf. Unknown or
                # failed provider outcomes never trigger another provider call.
                if fit.get('status') not in {'none','uncertain','unsupported'}:
                    return search_result(fit)
                remaining = [row for row in remaining if row.name != selected.name]
                rejected.append({'tool':selected.name,**fit})
            return search_result({'status':'uncertain','confidence':0},budget=bool(remaining))

        def _choose(self, need, candidates, purpose='skill'):
            if purpose not in {'mcp-server','mcp-tool'}:
                return super()._choose(need,candidates,purpose)
            if purpose == 'mcp-tool' and inspected_tools.get() is not None:
                tools = {t['name']:t for t in inspected_tools.get().get('tools',[])}
                if set(tools).issuperset(row.name for row in candidates):
                    candidates = [module.runtime.Skill(row.name,json.dumps(tools[row.name],ensure_ascii=False),row.path)
                                  for row in candidates]
                    if sum(len(row.description) for row in candidates) > 96000:
                        return {'status':'unsupported','reason':'tool_catalog_too_large','execution':'not_performed'}
                    return self.validated_tool(need,candidates,tools,inspected_tools.get())
            stage = 'mcp-discovery' if purpose == 'mcp-server' else 'mcp-tool-preview'
            return route(module.runtime,need,candidates,configuration(self.data,module,final=False),stage)

    class Runtime(base_runtime):
        def client(self,*args,**kwargs):
            client = super().client(*args,**kwargs)
            if inspected_tools.get() is not None:
                row = args[0] if args else kwargs['row']
                inspected_tools.get()['server'] = row['title']
            return InspectingClient(client) if inspected_tools.get() is not None else client

        def acquire(self, connection, need):
            state = {}
            context = inspected_tools.set(state)
            try:
                result = super().acquire(connection,need)
            finally:
                inspected_tools.reset(context)
            if result.get('status') != 'selected':
                return result
            released = False
            try:
                if 'validation' in state:
                    validation = state['validation']
                    if validation['tool'] != result['tool']:
                        return {'status':'uncertain','reason':'validated_tool_changed','execution':'not_performed'}
                    released = True
                    return {**result,'validation':validation['fit'],'routing_policy':POLICY,
                            'rejected_tools':validation['rejected_tools'],
                            'validation_binding':validation_binding(need,result)}
                # Older runtimes without captured tools retain the final-fit
                # guard; rejected persisted tickets still expire below.
                description = json.dumps({'server':result['server'],'tool':result['tool']},ensure_ascii=False)
                if len(description) > 24000:
                    return {'status':'unsupported','reason':'tool_schema_too_large','execution':'not_performed'}
                row = module.runtime.Skill('tool',description,Path('.'))
                config = configuration(self.data,module,final=True)
                fit = route(module.runtime,need,[row],config,'mcp-fit')
                fit = {k:v for k,v in fit.items() if k != 'skill'}
                fit['minimum_confidence'] = config['minimum_confidence']
                if fit['status'] != 'selected':
                    return {**fit,'phase':'actual_tool_validation','execution':'not_performed'}
                released = True
                return {**result,'validation':fit,'routing_policy':POLICY,
                        'validation_binding':validation_binding(need,result)}
            finally:
                # The base runtime writes a ticket before returning. Expire a
                # rejected/problematical selection while preserving its record.
                if not released:
                    path = self.data/'mcp-selections'/(result['selection']+'.json')
                    if path.exists():
                        ticket = module.public_access.owner_json(path)
                        module.runtime._atomic_json(path,{**ticket,'expires':0,
                            'validation_status':'not_released'})

    module.Router = Router
    return Runtime


def ensure_service(gateway, data, runtime_root):
    """Reuse a healthy service; start the staged runtime only when none is alive."""
    module = gateway.mcp_backpack
    data = module.public_access.safe(data)
    data.mkdir(parents=True,exist_ok=True,mode=0o700)
    with module.runtime.backpack_maintenance.target_lock(data,'mcp-service-launch'):
        info = None
        try:
            info = module.service_info(data)
            ping = module.service_call(data,'ping',timeout=2)
        except (OSError,ValueError,RuntimeError):
            if info is not None:
                try:
                    module.os.kill(info['pid'],0)
                except ProcessLookupError:
                    pass
                else:
                    raise module.MCPError('service_alive_but_unavailable')
        else:
            if ping.get('data_root') != str(data) or ping.get('pid') != info['pid']:
                raise module.MCPError('service_identity_mismatch')
            return
        child = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),
            '--runtime-root',str(runtime_root),'--data-root',str(data)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        threading.Thread(target=child.wait,daemon=True).start()
        until = time.monotonic()+5
        while time.monotonic() < until:
            try:
                info = module.service_info(data)
                if info['pid'] == child.pid and module.service_call(data,'ping',timeout=1).get('data_root') == str(data):
                    return
            except (OSError,ValueError,RuntimeError):
                pass
            if child.poll() is not None:
                break
            time.sleep(.05)
        raise module.MCPError('service_start_failed')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runtime-root',required=True);parser.add_argument('--data-root',required=True)
    args=parser.parse_args();root=Path(args.runtime_root).resolve(strict=True)
    entry=root/'scripts/backpack_mcp_runtime.py'
    spec=importlib.util.spec_from_file_location('backpack_base_service',entry)
    service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
    import mcp_backpack
    service.Runtime=install_selection(mcp_backpack)
    sys.argv=[str(entry),'--data-root',args.data_root]
    return service.main()


if __name__ == '__main__':
    raise SystemExit(main())
