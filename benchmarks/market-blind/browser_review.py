"""Optional host-browser review bridge for the native HTML benchmark.

The evaluator uses the supported Computer Use browser surface. This bridge does
not simulate a browser or infer success from source. The native Agent waits for
an explicit, artifact-bound observation and then reports its own Skill use.
It is benchmark infrastructure, not a production Backpack browser capability.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid


TOOL = {'name':'verify_local_webpage',
    'description':'Ask the host browser verifier to check the finished local HTML using real browser controls. Returns actual slider, formula, reset and clipboard observations, or an unavailable/failed result. The verifier does not edit the artifact or report Skill use. Call once after writing the requested page; do not generate a simulated browser harness or search for another browser. Wait time is included in this task budget. Await this operation with a 60-second initial yield when supported. If the host wrapper yields a running cell, wait 30–60 seconds per poll, not 1 second. Do not duplicate the verification call.',
    'inputSchema':{'type':'object','properties':{'path':{'type':'string','description':'HTML file inside the task workspace, e.g. index.html. Both workspace-relative and in-workspace absolute paths are accepted.'}},'required':['path'],'additionalProperties':False},
    'annotations':{'readOnlyHint':False,'destructiveHint':False,'openWorldHint':False}}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(connection, folder, arguments, timeout=120):
    if not isinstance(arguments,dict) or set(arguments)!={'path'} or not isinstance(arguments['path'],str):
        raise ValueError('invalid_browser_review_arguments')
    work=Path(connection['project_root']).resolve(strict=True)
    supplied=Path(arguments['path'])
    if '..' in supplied.parts or supplied.suffix.lower()!='.html':
        raise ValueError('browser_review_path_outside_workspace')
    path=supplied if supplied.is_absolute() else work/supplied
    if not path.is_file() or path.resolve()!=path or not path.is_relative_to(work):
        raise ValueError('browser_review_path_outside_workspace')
    if path.stat().st_size>512*1024:raise ValueError('browser_review_artifact_too_large')
    folder=Path(folder)
    if folder.is_symlink() or folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:
        raise ValueError('browser_review_folder_not_private')
    request={'id':uuid.uuid4().hex,'artifact':str(path),'sha256':digest(path),'created_at':time.time(),
             'required_checks':['formula','sliders','reset','clipboard']}
    # One review per case. Unknown/expired review outcomes are inspected, not replayed.
    with (folder/'request.json').open('x') as stream:json.dump(request,stream)
    (folder/'request.json').chmod(0o600)
    deadline=time.monotonic()+timeout
    response=folder/'response.json'
    while time.monotonic()<deadline:
        if response.is_file():
            value=json.loads(response.read_text())
            if value.get('id')!=request['id'] or value.get('sha256')!=request['sha256'] or digest(path)!=request['sha256']:
                raise ValueError('browser_review_artifact_changed')
            if value.get('status') not in {'passed','failed','unavailable'} or value.get('executor')!='root_cua':
                raise ValueError('invalid_browser_review_response')
            checks=value.get('checks',{})
            if value['status']=='passed' and not all(checks.get(k) is True for k in request['required_checks']):
                raise ValueError('incomplete_browser_review_evidence')
            return {k:value[k] for k in ('status','executor','checks','observations','limitations','elapsed_seconds') if k in value}
        threading.Event().wait(min(.2,max(0,deadline-time.monotonic())))
    return {'status':'unavailable','reason':'browser_review_deadline','instruction':'No completed browser receipt. Do not report browser success or replay this review automatically.'}


def install(protocol, connection, folder):
    original_catalog,original_dispatch=protocol.tool_catalog,protocol.dispatch
    protocol.tool_catalog=lambda gateway:[*original_catalog(gateway),TOOL]
    def dispatch(gateway, current, reader, market, name, arguments):
        if name!='verify_local_webpage':return original_dispatch(gateway,current,reader,market,name,arguments)
        if current!=connection or not gateway.load_connection(current['_descriptor'])['enabled']:
            raise ValueError('browser_review_connection_changed')
        result=review(current,folder,arguments)
        if not gateway.load_connection(current['_descriptor'])['enabled']:
            raise ValueError('connection_disabled')
        return result
    protocol.dispatch=dispatch
