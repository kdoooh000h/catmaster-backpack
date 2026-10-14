"""Resolve public GitHub plugin sources to a commit before reading package bytes."""
import json
import time
import urllib.parse


def resolve(location, snapshot, sources, plugin_sources):
    if isinstance(location, str):
        if not location.startswith('./'):
            raise ValueError('invalid_plugin_source_path')
        return snapshot['repo'], snapshot['commit'], sources.safe_path(location[2:])
    if not isinstance(location, dict):
        raise ValueError('unsupported_plugin_source')
    kind = location.get('source')
    allowed = {'source', 'ref', 'sha', 'path', 'repo' if kind == 'github' else 'url'}
    if kind not in {'github', 'url', 'git-subdir'} or set(location) - allowed:
        raise ValueError('unsupported_plugin_source')
    repo = plugin_sources.repository(location.get('repo' if kind == 'github' else 'url'))
    prefix = location.get('path', '')
    if not isinstance(prefix, str) or kind == 'git-subdir' and not prefix:
        raise ValueError('invalid_plugin_source_path')
    prefix = sources.safe_path(prefix.removeprefix('./'), allow_empty=True)
    sha, ref = location.get('sha'), location.get('ref')
    if sha is not None and (not isinstance(sha, str) or not sources.SHA.fullmatch(sha)):
        raise ValueError('invalid_plugin_source_commit')
    if ref is not None and (not isinstance(ref, str) or not 1 <= len(ref) <= 200
                            or any(ord(c) < 32 for c in ref)):
        raise ValueError('invalid_plugin_source_ref')
    deadline = time.monotonic() + 35
    base = 'https://api.github.com/repos/' + repo
    def get(url):
        value = json.loads(sources.fetch(url, 2 * 1024 * 1024, deadline))
        if not isinstance(value, dict):
            raise ValueError('invalid_plugin_source_response')
        return value
    meta = get(base)
    if (meta.get('full_name', '').lower() != repo or meta.get('private') is not False
            or meta.get('archived') or meta.get('disabled')):
        raise ValueError('plugin_source_unavailable')
    target = sha or ref or meta.get('default_branch')
    if not isinstance(target, str) or not target:
        raise ValueError('invalid_plugin_source_ref')
    commit = get(base + '/commits/' + urllib.parse.quote(target, safe='')).get('sha')
    if (not isinstance(commit, str) or not sources.SHA.fullmatch(commit)
            or sha is not None and commit != sha):
        raise ValueError('plugin_source_commit_changed')
    return repo, commit, prefix
