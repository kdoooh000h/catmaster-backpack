"""One source-grounded root description repair; no request-specific metadata."""
from copy import deepcopy

ROOT_ID = 'root:leadership-and-business'
SOURCE_ID = 'culture-architect'
ORIGINAL = ('Leadership, Business Operations & Finance: Make executive decisions '
            'across company functions; organize business operations and financial analysis.')
ADDITION = (' Also build company culture: translate mission, vision and values into '
            'observable behaviors; create culture codes and rituals; assess culture '
            'health and address culture clashes.')


def build(original):
    root = original.get(ROOT_ID)
    if not root or SOURCE_ID not in root['members'] or root['depth'] != 1:
        raise ValueError('missing_culture_root')
    if root['description'] not in {ORIGINAL, ORIGINAL + ADDITION}:
        raise ValueError('unexpected_root_description')
    nodes = deepcopy(original)
    nodes[ROOT_ID]['description'] = ORIGINAL + ADDITION
    return nodes
