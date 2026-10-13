"""One-shot CLI transport for a caller-owned hierarchical selector.

The normal CLI owns provider credentials and configuration. This bridge reads
neither: it passes the configured executable/model and the caller's environment.
Task state and questions live only in protected, short-lived JSON files. Answers
are private routing data; exceptions contain fixed codes, never CLI output.
The selector remains responsible for validating typed answers and confidence.
"""

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def _positive_number(value):
    return (type(value) in (int, float) and value > 0
            and (type(value) is int or math.isfinite(value)))


def _cli_failure_code(stderr):
    """Return only fixed transport codes; never retain provider error bodies."""
    text = stderr.casefold() if isinstance(stderr, str) else ''
    if 'certificate_verify_failed' in text or 'certificate verify failed' in text:
        return 'provider_certificate_error'
    status = re.search(r'http\s+(\d{3})', text)
    if status:
        code = int(status.group(1))
        if code in {401, 403}:
            return 'authentication_failed'
        if code in {408, 429} or 500 <= code < 600:
            return 'provider_transient'
        return 'provider_failed'
    if any(marker in text for marker in ('网络错误', 'unexpected_eof_while_reading',
            'connection reset', 'remote end closed', 'broken pipe', 'timed out')):
        return 'provider_unavailable'
    return 'provider_failed'


class JevHierarchyProvider:
    """Run each supplied stage once, with no retry or provider fallback.

    ``deadline`` is absolute on ``clock``. ``environment`` is a complete child
    environment when supplied; otherwise the current environment is inherited.
    Debug payload output is disabled in the child without mutating the parent.
    The caller must prevent its configured executable from recursively invoking
    the routing entry point. This class does not inspect installed executables.
    """

    def __init__(self, config, *, deadline=None, environment=None,
                 process=subprocess.run, clock=time.monotonic):
        if not isinstance(config, Mapping):
            raise ValueError('invalid_provider_configuration')
        if config.get('provider', 'jev-cli') != 'jev-cli':
            raise ValueError('unsupported_hierarchy_provider')
        if config.get('jev_provider', 'typesafe') != 'typesafe':
            raise ValueError('unsupported_jev_provider')
        executable = config.get('executable') or 'jev'
        if not isinstance(executable, str) or not executable.strip() or '\0' in executable:
            raise ValueError('invalid_provider_executable')
        model = config.get('model')
        if model is not None and (not isinstance(model, str) or not model.strip() or '\0' in model):
            raise ValueError('invalid_provider_model')
        timeout = config.get('timeout_seconds', 30)
        if not _positive_number(timeout):
            raise ValueError('invalid_provider_timeout')
        if (deadline is not None and (type(deadline) not in (int, float)
                or (type(deadline) is float and not math.isfinite(deadline)))):
            raise ValueError('invalid_provider_deadline')
        if not callable(process) or not callable(clock):
            raise ValueError('invalid_provider_dependency')
        try:
            self.environment = dict(os.environ if environment is None else environment)
        except Exception:
            raise ValueError('invalid_provider_environment') from None
        if any(not isinstance(key, str) or not isinstance(value, str)
               or '\0' in key or '=' in key or '\0' in value
               for key, value in self.environment.items()):
            raise ValueError('invalid_provider_environment')
        self.environment.pop('JEV_DEBUG', None)
        self.executable, self.model = executable, model
        self.timeout = min(timeout, 30)
        self.deadline, self.process, self.clock = deadline, process, clock
        # In-memory transport receipts only; absent usage stays unavailable.
        self.calls = []

    def _remaining(self):
        remaining = self.timeout
        if self.deadline is not None:
            remaining = min(remaining, self.deadline - self.clock())
        if remaining <= 0:
            raise TimeoutError('deadline_exceeded')
        return remaining

    @staticmethod
    def _write(path, value):
        try:
            content = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except Exception:
            raise ValueError('invalid_provider_input') from None
        # Set the mode at creation, rather than exposing bytes before chmod.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(content)

    def _run(self, spec, state):
        self._remaining()
        if not isinstance(spec, Mapping) or not isinstance(state, Mapping):
            raise ValueError('invalid_provider_input')
        try:
            with tempfile.TemporaryDirectory(prefix='jev-hierarchy-') as temporary:
                folder = Path(temporary)
                state_path, spec_path = folder / 'STATE.json', folder / 'SPEC.json'
                self._write(state_path, dict(state))
                self._write(spec_path, dict(spec))
                remaining = self._remaining()
                command = [self.executable, 'run', '--json', '--state', '@' + str(state_path),
                           '--provider', 'typesafe', '--timeout', str(remaining), '--retries', '0']
                if self.model is not None:
                    command.extend(['--model', self.model])
                command.append(str(spec_path))
                return self._invoke(command, remaining)
        except (TimeoutError, ValueError):
            raise
        except Exception:
            raise ValueError('provider_input_failed') from None

    def _invoke(self, command, remaining):
        started = self.clock()
        receipt = {'completed': False, 'outcome': 'provider_process_failed', 'seconds': None}
        self.calls.append(receipt)
        try:
            try:
                result = self.process(command, capture_output=True, text=True,
                                      env=dict(self.environment), timeout=remaining)
            except (subprocess.TimeoutExpired, TimeoutError):
                # The evaluation may already have run. Never replay it.
                receipt['outcome'] = 'unknown_no_replay'
                receipt['failure_code'] = 'provider_timeout'
                raise TimeoutError('unknown_no_replay') from None
            except Exception:
                receipt['failure_code'] = 'provider_process_failed'
                raise ValueError('provider_process_failed') from None
            receipt['completed'] = True
            if self.deadline is not None and self.clock() >= self.deadline:
                receipt['outcome'] = 'unknown_no_replay'
                receipt['failure_code'] = 'provider_timeout'
                raise TimeoutError('unknown_no_replay')
            if result.returncode != 0:
                receipt['failure_code'] = _cli_failure_code(getattr(result, 'stderr', None))
                raise ValueError('provider_process_failed')
            try:
                raw = json.loads(result.stdout)
            except (ValueError, TypeError):
                receipt['outcome'] = 'malformed_cli_result'
                receipt['failure_code'] = 'malformed_cli_result'
                raise ValueError('malformed_cli_result') from None
            if not isinstance(raw, dict) or not isinstance(raw.get('answers'), dict):
                receipt['outcome'] = 'malformed_cli_result'
                receipt['failure_code'] = 'malformed_cli_result'
                raise ValueError('malformed_cli_result')
            usage = raw.get('usage')
            if isinstance(usage, dict):
                for field in ('input_tokens', 'output_tokens'):
                    if type(usage.get(field)) is int and usage[field] >= 0:
                        receipt[field] = usage[field]
            receipt['outcome'] = 'completed'
            # Drop unsolicited CLI metadata, which can include echoed input.
            return {'answers': raw['answers']}
        finally:
            elapsed = self.clock() - started
            if type(elapsed) in (int, float) and 0 <= elapsed < float('inf'):
                receipt['seconds'] = elapsed

    def noul(self, spec, state):
        """Return the answer map; the selector checks every Noul answer."""
        return self._run(spec, state)

    def choose(self, question, state, choices):
        """Preserve exact final question, option order, IDs and descriptions."""
        if not isinstance(question, str) or not isinstance(choices, Mapping):
            raise ValueError('invalid_provider_input')
        spec = {'questions': {'answer': {'type': 'choice', 'instructions': question,
                                         'criteria': dict(choices)}}}
        raw = self._run(spec, state)
        answer = raw['answers'].get('answer')
        if not isinstance(answer, dict):
            self.calls[-1]['outcome'] = 'malformed_cli_result'
            self.calls[-1]['failure_code'] = 'malformed_cli_result'
            raise ValueError('malformed_cli_result')
        return answer
