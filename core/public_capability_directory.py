"""Validate and expand a public directory; capability selection belongs to Jev."""

from collections.abc import Mapping, Sequence


class PublicCapabilityDirectory:
    """A two-level directory over an ordered mapping of original descriptions.

    Node cards never include capability IDs or descriptions. Expansion preserves
    the choices' order and text, including the original position of ``none``.
    """

    def __init__(self, spec: Mapping, choices: Mapping[str, str]):
        if not isinstance(spec, Mapping) or set(spec) != {
            "version", "provenance", "roots", "leaves"
        }:
            raise ValueError("invalid directory schema")
        if type(spec["version"]) is not int or spec["version"] != 1:
            raise ValueError("unsupported directory version")
        if not isinstance(spec["provenance"], Mapping) or not spec["provenance"]:
            raise ValueError("directory provenance is required")
        if not isinstance(choices, Mapping) or "none" not in choices:
            raise ValueError("choices must include none")
        for key, description in choices.items():
            self._text(key, "capability ID")
            self._text(description, "capability description")
        self._choices = dict(choices)
        capability_ids = set(choices) - {"none"}
        if not capability_ids:
            raise ValueError("directory needs available capabilities")

        roots = self._nodes(spec["roots"], "children")
        leaves = self._nodes(spec["leaves"], "members")
        self.root_ids = list(roots)
        self.leaf_ids = list(leaves)
        if set(roots) & set(leaves) or {"none", "all"} & (set(roots) | set(leaves)):
            raise ValueError("node IDs must be unique and distinct from controls")
        shortcuts = self._ids(spec["provenance"].get("shortcut_roots", []), "shortcut roots")
        if not set(shortcuts) <= set(roots):
            raise ValueError("unknown shortcut root")
        self._shortcut_root_ids = tuple(shortcuts)
        self._nodes_by_id = {**roots, **leaves}
        self._children = {}
        parents = set()
        for root_id, root in roots.items():
            children = root["children"]
            if not set(children) <= set(leaves):
                raise ValueError("unknown leaf in root children")
            if parents & set(children):
                raise ValueError("each leaf must have exactly one parent")
            parents.update(children)
            self._children[root_id] = children
        if parents != set(leaves):
            raise ValueError("every leaf must have a parent")

        self._members = {}
        covered = set()
        for leaf_id, leaf in leaves.items():
            members = set(leaf["members"])
            if not members <= capability_ids:
                raise ValueError("unknown capability or none in leaf members")
            self._members[leaf_id] = members
            covered.update(members)
        if covered != capability_ids:
            raise ValueError("directory must cover every available capability")
        for root_id, children in self._children.items():
            self._members[root_id] = set().union(
                *(self._members[child] for child in children)
            )

    @property
    def shortcut_root_ids(self):
        """Explicit root shortcuts; callers receive an independent ID list."""
        return list(self._shortcut_root_ids)

    @staticmethod
    def _text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be nonempty text")

    @classmethod
    def _ids(cls, value, label, *, nonempty=False):
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"{label} must be an ID sequence")
        result = list(value)
        for item in result:
            cls._text(item, label)
        if len(set(result)) != len(result):
            raise ValueError(f"duplicate ID in {label}")
        if nonempty and not result:
            raise ValueError(f"{label} cannot be empty")
        return result

    @classmethod
    def _nodes(cls, value, relation):
        if not isinstance(value, list) or not value:
            raise ValueError("node lists cannot be empty")
        result = {}
        for node in value:
            if not isinstance(node, Mapping) or set(node) != {
                "id", "label", "description", relation
            }:
                raise ValueError("invalid node schema")
            for field in ("id", "label", "description"):
                cls._text(node[field], field)
            if node["id"] in result:
                raise ValueError("duplicate node ID")
            result[node["id"]] = {
                **node,
                relation: cls._ids(node[relation], relation, nonempty=True),
            }
        return result

    def _selected(self, ids):
        selected = self._ids(ids, "selected nodes")
        if not set(selected) <= set(self._nodes_by_id):
            raise ValueError("unknown directory node")
        return set(selected)

    def cards(self, ids):
        """Return only compact cards, in directory order."""
        selected = self._selected(ids)
        return [
            {
                "id": node_id,
                "label": node["label"],
                "description": node["description"],
                "available_count": len(self._members[node_id]),
            }
            for node_id, node in self._nodes_by_id.items()
            if node_id in selected
        ]

    def children(self, parent_id):
        """Return a root's leaf IDs in its declared order."""
        self._text(parent_id, "parent ID")
        if parent_id not in self._children:
            raise ValueError("unknown root")
        return list(self._children[parent_id])

    def members(self, ids):
        """Expand selected roots/leaves to a deduplicated ordered capability list."""
        selected = self._selected(ids)
        members = set().union(*(self._members[node] for node in selected))
        return [key for key in self._choices if key in members]

    def subset(self, ids):
        """Return expanded original choices and none, preserving text and order."""
        members = set(self.members(ids)) | {"none"}
        return {
            key: description
            for key, description in self._choices.items()
            if key in members
        }
