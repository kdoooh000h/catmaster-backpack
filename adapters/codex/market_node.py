"""Launch the verified real npm bin, without npx symlink or runtime downloads."""
import json
import os
from pathlib import Path
import re
import shutil
import sys

PACKAGE = re.compile(r'((?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*)@(\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?)')
BIN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}')


def target(config, *, exact=True):
    args = config.get('command', [])
    if (len(args) >= 9 and args[1:3] == ['-I', '-B']
            and (args[3] == str(Path(__file__).resolve()) if exact else Path(args[3]).name == 'market_node.py')
            and args[4] == 'run' and PACKAGE.fullmatch(args[5]) and BIN.fullmatch(args[6])):
        return args[5], args[6], Path(args[7])
    return None


def configuration(config, directory):
    args = config['command']
    if len(args) < 5 or args[1:3] != ['--yes', '--ignore-scripts'] or not args[3].startswith('--package='):
        raise ValueError('unsupported_npm_launch')
    package, binary = args[3].removeprefix('--package='), args[4]
    if not PACKAGE.fullmatch(package) or not BIN.fullmatch(binary):
        raise ValueError('invalid_npm_launch')
    node = shutil.which('node')
    if not node:
        raise ValueError('market_runtime_missing')
    return {**config, 'command': [sys.executable, '-I', '-B', str(Path(__file__).resolve()),
        'run', package, binary, str(directory), str(Path(node).resolve()), *args[5:]]}


def entrypoint(directory, package, binary):
    match = PACKAGE.fullmatch(package)
    if not match or not BIN.fullmatch(binary):
        raise ValueError('invalid_npm_launch')
    name, version = match.groups()
    root = directory / 'node_modules' / name
    manifest = json.loads((root / 'package.json').read_text())
    lock = json.loads((directory / 'package-lock.json').read_text())
    installed = lock.get('packages', {}).get('node_modules/' + name, {})
    if (manifest.get('name') != name or manifest.get('version') != version
            or installed.get('version') != version or not installed.get('integrity')):
        raise ValueError('market_dependency_state_changed')
    bins = manifest.get('bin')
    if not isinstance(bins, dict) or set(bins) != {binary} or not isinstance(bins[binary], str):
        raise ValueError('npm_entrypoint_changed')
    relative = Path(bins[binary])
    if relative.is_absolute() or '..' in relative.parts or '\\' in bins[binary]:
        raise ValueError('unsafe_npm_entrypoint')
    script = (root / relative).resolve()
    if not script.is_relative_to(root.resolve()) or not script.is_file():
        raise ValueError('unsafe_npm_entrypoint')
    # A shell/native executable is not silently interpreted as JavaScript.
    with script.open('rb') as stream:
        first = stream.readline(256)
    if script.suffix not in {'.js', '.mjs', '.cjs'} and b'node' not in first:
        raise ValueError('unsupported_npm_entrypoint')
    return script


if __name__ == '__main__':
    if len(sys.argv) < 6 or sys.argv[1] != 'run':
        raise SystemExit('invalid_npm_launch')
    script = entrypoint(Path(sys.argv[4]), sys.argv[2], sys.argv[3])
    os.execv(sys.argv[5], [sys.argv[5], str(script), *sys.argv[6:]])
