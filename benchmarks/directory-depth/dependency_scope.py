"""Clarify package-audit operations without changing members or routing rules."""
from copy import deepcopy

NODE = 'domain:engineering:topic7'
PARENT = 'domain:engineering'
ORIGINAL = ('Audit dependencies and unsafe code patterns; manage environment secrets '
            'and vault infrastructure; verify release readiness.')
REPLACEMENT = (
    'Audit third-party software packages for known vulnerabilities, license conflicts '
    'and transitive dependency risks; plan safe upgrade paths. Also detect unsafe code '
    'patterns, manage environment secrets and vault infrastructure, and verify release readiness.')


def build(original):
    node, parent = original.get(NODE), original.get(PARENT)
    if not node or not parent or NODE not in parent['children'] or 'dependency-auditor' not in node['members']:
        raise ValueError('missing_dependency_scope')
    if node['description'] != ORIGINAL or parent['description'].count(ORIGINAL) != 1:
        raise ValueError('unexpected_dependency_scope')
    nodes = deepcopy(original)
    nodes[NODE]['description'] = REPLACEMENT
    # The level-two card is the compiler's complete child-scope list. Keep its
    # embedded copy consistent, rather than hiding different promises by depth.
    nodes[PARENT]['description'] = parent['description'].replace(ORIGINAL, REPLACEMENT)
    return nodes
