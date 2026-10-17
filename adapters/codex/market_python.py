"""Pinned PyPI MCPs in Backpack-owned environments; no host Python installation."""
import configparser
import ast
import csv
import concurrent.futures
import email.parser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}')
VERSION = re.compile(r'\d+(?:\.\d+){1,3}(?:(?:a|b|rc)\d+|\.post\d+|\.dev\d+)?')
ENV = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,79}')


def package_launch(package):
    """Recognize a declared uvx --from SAME_PACKAGE[extras] entrypoint only.

    This is normalized into a pinned wheel install plus a verified distribution
    console script, never passed as publisher-controlled installer flags.
    """
    arguments = package.get('packageArguments') or []
    if not arguments:
        return '', ''
    if len(arguments) != 2 or package.get('runtimeHint') != 'uvx':
        raise ValueError('unsupported_python_package_arguments')
    source, entry = arguments
    if (not isinstance(source, dict) or not isinstance(entry, dict)
            or source.get('type') != 'named' or source.get('name') != '--from'
            or entry.get('type') != 'positional' or not NAME.fullmatch(str(entry.get('value', '')))):
        raise ValueError('unsupported_python_package_arguments')
    match = re.fullmatch(re.escape(package['identifier']) + r'\[([a-zA-Z0-9_,.-]{1,100})\]', str(source.get('value', '')))
    if not match:
        raise ValueError('unsupported_python_package_arguments')
    extras = sorted(set(match[1].split(',')))
    if len(extras) > 8 or any(not NAME.fullmatch(value) for value in extras):
        raise ValueError('unsupported_python_package_arguments')
    return ','.join(extras), entry['value']


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def metadata_summaries(library, rows):
    """Small complete pools can reuse versioned publisher summaries and tags.

    Reads are anonymous and optional: failures never remove a Registry candidate.
    Package descriptions are evidence, never instructions or permission.
    """
    tasks = {}
    for row in rows:
        for option in row.get('available', []):
            if option['id'].startswith('pypi:'):
                package = library.items[row['receipt']]['server']['packages'][int(option['id'].split(':')[1])]
                name, version = package['identifier'], package['version']
                if NAME.fullmatch(name) and VERSION.fullmatch(version):
                    tasks.setdefault((name, version), []).append(row['receipt'])
    if not tasks or len(rows) > 12 or len(tasks) > 12:
        return {}
    deadline = time.monotonic() + 12
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('pypi_metadata_redirect')
    def fetch(key):
        name, version = key
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return key, None
        url = 'https://pypi.org/pypi/' + urllib.parse.quote(name, safe='') + '/' + urllib.parse.quote(version, safe='') + '/json'
        try:
            request = urllib.request.Request(url, headers={'User-Agent':'CatMaster-Backpack','Accept':'application/json'})
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=remaining) as response:
                content = response.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024:
                return key, None
            info = json.loads(content)['info']
            if normalized(info['name']) != normalized(name) or info['version'] != version:
                return key, None
            values = {field: info[field] for field in ('summary','keywords','requires_python')
                      if isinstance(info.get(field),str) and len(info[field]) <= 2000}
            return key, values
        except (OSError,ValueError,KeyError,TypeError):
            return key, None
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for key, value in pool.map(fetch, tasks):
            if value:
                for receipt in tasks[key]:
                    result.setdefault(receipt, []).append({'package':key[0], 'version':key[1], **value})
    return result


def options(library, receipt):
    result = library.options(receipt)
    if not shutil.which('uv'):
        return result
    server = library.items[receipt]['server']
    for index, package in enumerate(server.get('packages') or []):
        if (not isinstance(package, dict) or package.get('registryType') != 'pypi'
                or package.get('registryBaseUrl', 'https://pypi.org') not in {'https://pypi.org', 'https://pypi.org/simple'}
                or package.get('transport', {}).get('type') != 'stdio'
                or not NAME.fullmatch(str(package.get('identifier', '')))
                or not VERSION.fullmatch(str(package.get('version', '')))
                or package.get('runtimeArguments')):
            continue
        try:
            extras, entry = package_launch(package)
        except ValueError:
            continue
        fields = []
        for env in package.get('environmentVariables', []):
            if not isinstance(env, dict) or not ENV.fullmatch(str(env.get('name', ''))):
                break
            default = env.get('default', '')
            if not isinstance(default, str) or len(default) > 1000 or any(c in default for c in '\r\n\0'):
                break
            fields.append({'key': 'env:' + env['name'], 'label': env['name'],
                           'required': env.get('isRequired') is True, 'secret': env.get('isSecret') is True,
                           'default': '' if env.get('isSecret') else default})
        else:
            if len(fields) <= 32:
                result['options'].append({'id': 'pypi:' + str(index),
                    'label': 'Local PyPI (isolated environment, wheels only) ' + package['identifier'] + '==' + package['version'],
                    'fields': fields, 'extras': extras, 'entrypoint': entry})
    return result


def configuration(library, receipt, option, data, descriptor):
    if not option['id'].startswith('pypi:'):
        return library.configuration({'source_receipt': receipt, 'option': option['id']})
    # Revalidate the exact option and its still-current metadata receipt.
    current = options(library, receipt)
    if option not in current['options'] or any(f['required'] and not f['default'] for f in option['fields']):
        raise ValueError('python_mcp_configuration_required')
    package = library.items[receipt]['server']['packages'][int(option['id'].split(':')[1])]
    name, version = normalized(package['identifier']), package['version']
    identity = hashlib.sha256(json.dumps([descriptor, name, version]).encode()).hexdigest()[:32]
    directory = Path(data) / 'market-python' / identity
    command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), 'run', name, version, str(directory),
               option['extras'], option['entrypoint']]
    return {'title': str(current['title'])[:200], 'description': str(current['description'])[:1200],
            'configuration': {'transport': 'stdio', 'command': command,
                              'env': {f['label']: f['default'] for f in option['fields'] if f['default']}},
            'source': {'kind': 'registry', 'name': current['name'], 'version': current['version'],
                       'package': name, 'package_version': version}}


def target(config, *, exact=True):
    command = config.get('command', [])
    if (len(command) in {8, 10} and command[1:3] == ['-I', '-B']
            and (command[3] == str(Path(__file__).resolve()) if exact else Path(command[3]).name == 'market_python.py')
            and command[4] == 'run'
            and NAME.fullmatch(command[5]) and VERSION.fullmatch(command[6])):
        return command[5], command[6], Path(command[7])
    return None


def tree_digest(root):
    digest = hashlib.sha256()
    count = size = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            content = os.readlink(path).encode()
        elif path.is_file():
            size += path.stat().st_size
            if size > 128 * 1024 * 1024:
                raise ValueError('python_mcp_environment_too_large')
            content = path.read_bytes()
        else:
            continue
        count += 1
        if count > 10000:
            raise ValueError('python_mcp_environment_too_large')
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + hashlib.sha256(content).digest())
    return digest.hexdigest()


def entrypoint(directory, name, version, requested=''):
    sites = list((directory / 'venv/lib').glob('python*/site-packages'))
    if len(sites) != 1:
        raise ValueError('python_mcp_environment_invalid')
    matches = []
    for path in sites[0].glob('*.dist-info'):
        meta = email.parser.Parser().parsestr((path / 'METADATA').read_text())
        if normalized(meta.get('Name', '')) == name and meta.get('Version') == version:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError('python_mcp_package_identity_changed')
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(matches[0] / 'entry_points.txt')
    scripts = dict(parser.items('console_scripts')) if parser.has_section('console_scripts') else {}
    if requested:
        scripts = {requested: scripts[requested]} if requested in scripts else {}
    if len(scripts) != 1 or not NAME.fullmatch(next(iter(scripts), '')):
        raise ValueError('python_mcp_unique_entrypoint_required')
    script = directory / 'venv/bin' / next(iter(scripts))
    if not script.is_file() or script.is_symlink():
        raise ValueError('python_mcp_entrypoint_invalid')
    return script


def legacy_mcp_constraint(directory, name, version):
    """Constrain only a selected wheel that imports v1 APIs against installed v2.

    Inspect that distribution's own RECORD and Python AST without importing it.
    The resolver still enforces all publisher requirements; an incompatible
    declared floor fails rather than being overridden. Mixed v1/v2 code is not
    automatically downgraded.
    """
    sites = list((directory / 'venv/lib').glob('python*/site-packages'))
    if len(sites) != 1:
        raise ValueError('python_mcp_environment_invalid')
    site = sites[0]
    selected = None
    sdk = ''
    for dist in site.glob('*.dist-info'):
        meta = email.parser.Parser().parsestr((dist / 'METADATA').read_text())
        if normalized(meta.get('Name', '')) == name and meta.get('Version') == version:
            selected = dist
        if normalized(meta.get('Name', '')) == 'mcp':
            sdk = meta.get('Version', '')
    if selected is None or not sdk or not sdk.split('.')[0].isdigit() or int(sdk.split('.')[0]) < 2:
        return None
    record = selected / 'RECORD'
    if not record.is_file() or record.stat().st_size > 1024 * 1024:
        return None
    legacy = modern = False
    total = count = 0
    with record.open(newline='') as stream:
        for row in csv.reader(stream):
            count += 1
            if count > 10000:
                raise ValueError('python_mcp_package_too_large')
            if not row or not row[0].endswith('.py'):
                continue
            path = site / row[0]
            if path.is_symlink() or not path.resolve().is_relative_to(site.resolve()) or not path.is_file():
                raise ValueError('python_mcp_package_path_invalid')
            total += path.stat().st_size
            if total > 2 * 1024 * 1024:
                raise ValueError('python_mcp_package_too_large')
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeError):
                continue
            for node in ast.walk(tree):
                modules = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                           [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                legacy |= any(m == 'mcp.server.fastmcp' or m.startswith('mcp.server.fastmcp.') for m in modules)
                modern |= any(m == 'mcp.server.mcpserver' or m.startswith('mcp.server.mcpserver.') for m in modules)
    return 'mcp<2' if legacy and not modern else None


def verify(directory, name, version, extras='', requested=''):
    record = json.loads((directory / 'ready.json').read_text())
    script = entrypoint(directory, name, version, requested)
    if (record.get('name') != name or record.get('version') != version
            or record.get('entrypoint') != script.name
            or record.get('extras', '') != extras
            or record.get('digest') != tree_digest(directory / 'venv')):
        raise ValueError('python_mcp_environment_changed')
    return script


def install(market, row, plan):
    value = target(row['configuration'])
    if value is None:
        return False
    name, version, directory = value
    command = row['configuration']['command']
    extras, requested = command[8:] if len(command) == 10 else ('', '')
    if (extras and (len(extras.split(',')) > 8 or any(not NAME.fullmatch(e) for e in extras.split(',')))
            or requested and not NAME.fullmatch(requested)):
        raise ValueError('invalid_python_mcp_entrypoint')
    market.gateway.public_access.safe(directory)
    expected = hashlib.sha256(json.dumps([market.descriptor, name, version]).encode()).hexdigest()[:32]
    if directory != market.data / 'market-python' / expected:
        raise ValueError('python_mcp_environment_scope_mismatch')
    if directory.exists():
        if not (directory / 'ready.json').is_file():
            raise ValueError('python_mcp_setup_interrupted')
        verify(directory, name, version, extras, requested)
        return True
    uv = shutil.which('uv')
    if not uv:
        raise ValueError('market_runtime_missing')
    directory.mkdir(mode=0o700, parents=True)
    home = directory / 'home'; home.mkdir(mode=0o700)
    environment = {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(home), 'TMPDIR': str(directory),
                   'UV_CACHE_DIR': str(directory / 'cache'), 'UV_PYTHON_DOWNLOADS': 'never', 'LANG': 'en_US.UTF-8'}
    commands = [
        [uv, 'venv', '--no-config', '--no-python-downloads', '--python', sys.executable, str(directory / 'venv')],
        [uv, 'pip', 'install', '--no-config', '--no-python-downloads', '--only-binary', ':all:',
         '--python', str(directory / 'venv/bin/python'), '--index-url', 'https://pypi.org/simple',
         name + ('[' + extras + ']' if extras else '') + '==' + version],
    ]
    deadline = time.monotonic() + 150
    log = market.folder / (plan['id'] + '-pypi.log')
    with log.open('wb') as output:
        log.chmod(0o600)
        compatibility = None
        for index, command in enumerate(commands):
            process = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=output, start_new_session=True)
            try:
                code = process.wait(timeout=max(.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
                raise ValueError('python_mcp_setup_interrupted') from None
            if code:
                raise ValueError('python_mcp_dependency_setup_failed')
            if index == 1:
                compatibility = legacy_mcp_constraint(directory, name, version)
                if compatibility:
                    constraint = directory / 'compatibility-constraints.txt'
                    constraint.write_text(compatibility + '\n')
                    constraint.chmod(0o600)
                    commands.append([*command, '--constraint', str(constraint)])
    script = entrypoint(directory, name, version, requested)
    market.runtime._atomic_json(directory / 'ready.json', {'name': name, 'version': version,
        'entrypoint': script.name, 'extras': extras, 'compatibility_constraint': compatibility,
        'digest': tree_digest(directory / 'venv')})
    market.current()
    return True


if __name__ == '__main__':
    if len(sys.argv) not in {5, 7} or sys.argv[1] != 'run' or not NAME.fullmatch(sys.argv[2]) or not VERSION.fullmatch(sys.argv[3]):
        raise SystemExit('invalid_python_mcp_invocation')
    folder = Path(sys.argv[4])
    script = verify(folder, sys.argv[2], sys.argv[3], *(sys.argv[5:] if len(sys.argv) == 7 else []))
    executable = str(folder / 'venv/bin/python')
    os.execv(executable, [executable, '-I', '-B', str(script)])
