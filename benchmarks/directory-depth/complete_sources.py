"""Checkpointed public reads and isolated reuse of installed ranking adapters."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.parse

from source_preflight import save


def read(p): return json.loads(Path(p).read_text())


def registry(old, output, seconds=1200, max_pages=500):
    """Resume exact saved cursor; HTTP reads only, at most one transient retry."""
    old, out = Path(old), Path(output)
    out.mkdir(mode=0o700, exist_ok=False)
    saved = sorted(old.glob('registry-page-*.json'), key=lambda p: int(p.stem.rsplit('-', 1)[1]))
    if not saved: raise ValueError('resume_requires_saved_pages')
    for index, path in enumerate(saved):
        if path.name != f'registry-page-{index}.json': raise ValueError('noncontiguous_saved_pages')
        shutil.copy2(path, out / path.name)
    cursor = read(saved[-1])['metadata']['nextCursor'] if saved else None
    seen = {read(path)['metadata'].get('nextCursor') for path in saved}
    began, requests = time.monotonic(), 0
    complete, error = not cursor, None
    for page in range(len(saved), max_pages):
        if complete: break
        if time.monotonic()-began >= seconds: error = 'read_budget_exhausted'; break
        url = 'https://registry.modelcontextprotocol.io/v0.1/servers?' + urllib.parse.urlencode(
            {'version': 'latest', 'limit': 100, 'cursor': cursor})
        success = False
        for attempt in range(2):
            remaining = min(45, seconds-(time.monotonic()-began))
            if remaining <= 0: error = 'read_budget_exhausted'; break
            requests += 1
            started = time.monotonic()
            try:
                process = subprocess.run(['/usr/bin/curl', '-q', '--silent', '--show-error', '--max-time', str(remaining),
                    '--max-filesize', '8388608', '--proto', '=https', '--write-out', '\n%{http_code}', '--url', url],
                    capture_output=True, timeout=remaining+2)
            except subprocess.TimeoutExpired:
                save(out / f'page-{page}-attempt-{attempt}.json', {'outcome': 'read_timeout', 'seconds': time.monotonic()-started})
                error = 'read_timeout'; continue
            body, _, code = process.stdout.rpartition(b'\n')
            receipt = {'outcome': 'http_read', 'curl_exit': process.returncode, 'status': code.decode(),
                       'seconds': time.monotonic()-started, 'request_cursor': cursor}
            save(out / f'page-{page}-attempt-{attempt}.json', receipt)
            if process.returncode or code != b'200':
                error = 'network_error' if process.returncode else 'http_'+code.decode()
                if process.returncode in {6, 7, 28, 35, 52, 56} or code in {b'429', b'502', b'503', b'504'}: continue
                break
            value = json.loads(body)
            if not isinstance(value.get('servers'), list) or len(value['servers']) > 100:
                raise ValueError('invalid_registry_page')
            new = value.get('metadata', {}).get('nextCursor')
            if new and (not isinstance(new, str) or new in seen): raise ValueError('repeated_registry_cursor')
            save(out / f'registry-page-{page}.json', value)
            cursor = new; seen.add(new); complete = not cursor
            success, error = True, None
            break
        if not success: break
        if page % 10 == 0 or complete:
            print(json.dumps({'page': page, 'complete': complete, 'seconds': time.monotonic()-began}), flush=True)
    else: error = 'page_budget_exhausted'
    pages = sorted(out.glob('registry-page-*.json'), key=lambda p: int(p.stem.rsplit('-', 1)[1]))
    unique, conflicts, versions = {}, [], {}
    for path in pages:
        for envelope in read(path)['servers']:
            server = envelope['server']; identity = (server['name'], server['version'])
            if identity in unique and unique[identity]['server'] != server: conflicts.append(identity)
            unique[identity] = envelope
            versions.setdefault(server['name'], set()).add(server['version'])
    changed_names = [name for name, values in versions.items() if len(values) > 1]
    result = {'complete': complete and not conflicts and not changed_names, 'pagination_complete': complete,
        'pages': len(pages), 'rows': sum(len(read(p)['servers']) for p in pages), 'unique': len(unique),
        'conflicts': conflicts, 'changed_names': changed_names, 'error': error, 'next_cursor': cursor,
        'requests': requests, 'reused_pages': len(saved), 'seconds': time.monotonic()-began,
        'limitation': 'Cursor census across observation times, not a transactional snapshot; historical pages reused unchanged.'}
    save(out / 'summary.json', result)
    save(out / 'servers.json', list(unique.values()))
    print(json.dumps(result), flush=True)


def rankings(app, history, output):
    app, history, out = Path(app), Path(history), Path(output)
    out.mkdir(mode=0o700, exist_ok=False)
    copied = out / 'history'; copied.mkdir(mode=0o700)
    for path in history.glob('*.json'):
        if path.is_symlink() or path.stat().st_size > 8*1024*1024: raise ValueError('unsafe_ranking_cache')
        shutil.copy2(path, copied / path.name)
    sys.path.insert(0, str(app / 'adapters/standalone'))
    import sources
    import community_rankings as C
    import claude_rankings as A
    import directory_rankings as D
    library = sources.Library(copied)
    community = C.Library(library)
    directory = D.Library(library)
    claude = A.Library(library)
    # One public fetch per community publisher; its parser exposes all kinds.
    def publisher(name):
        began = time.monotonic()
        try:
            page = C.parse(name, C.fetch_page(C.PROVIDERS[name][0]))
            return {'provider': name, 'status': 'fresh', 'at': time.time(), 'rows': page, 'seconds': time.monotonic()-began}
        except Exception as error:
            return {'provider': name, 'status': 'unavailable', 'error': str(error), 'seconds': time.monotonic()-began}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(publisher, ['claudius', 'skill-codex', 'skill-opencode', 'codex-community', 'codex-community-skills', 'opendock']):
            save(out / (result['provider']+'.json'), result)
            if result['status']=='fresh': community.pages[result['provider']] = (result['at'], result['rows'])
    original_load=community.load
    community.load=lambda view: None if C.VIEWS[view][0] in community.pages else original_load(view)
    feeds = []
    for view, (provider, kind, metric, _) in C.VIEWS.items():
        try:
            result = community.leaderboard(kind, view, refresh=False)
            board = community.boards[view]
            feeds.append({'kind': kind, 'feed': view, 'metric': metric, 'at': board['fetched_at'],
                          'rows': board['rows'], 'stale': result['stale'], 'coverage': result['coverage']})
        except Exception as error:
            feeds.append({'feed': view, 'kind': kind, 'error': str(error), 'rows': []})
    for view in ('all-time', 'trending'):
        try:
            result = library.leaderboard(view, refresh=True); board = library.boards[view]
            feeds.append({'kind': 'skill', 'feed': view, 'metric': 'installs', 'at': board['fetched_at'],
                          'rows': board['rows'], 'stale': result['stale'], 'coverage': result['coverage']})
        except Exception as error: feeds.append({'kind': 'skill', 'feed': view, 'error': str(error), 'rows': []})
    try:
        result=claude.leaderboard(refresh=True);board=claude.board
        feeds.append({'kind':'plugin','feed':'claude-installs','metric':'installs','at':board['fetched_at'],
                      'rows':board['rows'],'stale':result['stale'],'coverage':result.get('coverage')})
    except Exception as error: feeds.append({'kind':'plugin','feed':'claude-installs','error':str(error),'rows':[]})
    for kind in ('plugin','mcp'):
        try:
            result=directory.leaderboard(kind,refresh=True);board=directory.boards[kind]
            feeds.append({'kind':kind,'feed':'github-topics','metric':'stars','at':board['fetched_at'],
                          'rows':board['rows'],'stale':result['stale'],'coverage':result.get('coverage')})
        except Exception as error: feeds.append({'kind':kind,'feed':'github-topics','error':str(error),'rows':[]})
    save(out / 'feeds.json', feeds)
    print(json.dumps([{'feed':f['feed'],'kind':f['kind'],'rows':len(f['rows']),'stale':f.get('stale'),'error':f.get('error')} for f in feeds]), flush=True)


def resolve_rank_pages(app, output):
    """Reparse already captured fresh pages; never repeat the network reads."""
    out=Path(output);sys.path.insert(0,str(Path(app)/'adapters/standalone'))
    import community_rankings as C
    feeds=read(out/'feeds.json')
    for feed in feeds:
        if feed['feed'] not in C.VIEWS:continue
        provider,kind,metric,_=C.VIEWS[feed['feed']]
        page=read(out/(provider+'.json'))
        if page['status']!='fresh':continue
        rows=page['rows'][metric]
        if provider=='claudius':rows=[r for r in rows if r['kind']==kind]
        if not (provider=='claudius' and feed['feed'].endswith('-composite')):
            rows=sorted(rows,key=lambda r:(-r[metric],r['id']))
        rows=[{**r,'rank':i} for i,r in enumerate(rows,1)]
        for row in rows:C.validate(row,feed['feed'])
        feed.update(rows=rows,at=page['at'],stale=False,reparsed_captured_page=True)
        feed.pop('error',None)
    save(out/'feeds-resolved.json',feeds)
    print(json.dumps({'feeds':len(feeds),'fresh':sum(f.get('stale') is False for f in feeds),'network_calls':0}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('registry')
    for name in ('old','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--seconds',type=float,default=1200);p.add_argument('--max-pages',type=int,default=500)
    p=sub.add_parser('rankings')
    for name in ('app','history','output'):p.add_argument('--'+name,required=True)
    p=sub.add_parser('resolve-rank-pages')
    for name in ('app','output'):p.add_argument('--'+name,required=True)
    a=parser.parse_args();values=vars(a).copy();values.pop('command')
    {'registry':registry,'rankings':rankings,'resolve-rank-pages':resolve_rank_pages}[a.command](**values)
