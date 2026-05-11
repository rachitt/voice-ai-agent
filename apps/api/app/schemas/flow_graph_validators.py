"""Server-side flow-graph validator.

Mirrors apps/web/src/pages/builder/connection-rules.ts. Keep in sync.

Used at publish-time to reject malformed agent flow graphs. Drafts via PATCH
are NOT validated here — only when /publish runs.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

StepKind = Literal[
    "greeting",
    "collect",
    "api",
    "condition",
    "transfer",
    "voicemail",
    "kb_lookup",
    "end",
]


@dataclass
class KindRule:
    in_allowed: bool
    out_max: int
    out_needs_label: bool = False
    allowed_labels: tuple[str, ...] = ()
    terminal: bool = False
    root: bool = False


RULES: dict[str, KindRule] = {
    "greeting": KindRule(in_allowed=False, out_max=1, root=True),
    "collect": KindRule(in_allowed=True, out_max=1),
    "api": KindRule(in_allowed=True, out_max=1),
    "condition": KindRule(
        in_allowed=True, out_max=2, out_needs_label=True, allowed_labels=("yes", "no")
    ),
    "transfer": KindRule(in_allowed=True, out_max=1),
    "voicemail": KindRule(in_allowed=True, out_max=0, terminal=True),
    "kb_lookup": KindRule(in_allowed=True, out_max=1),
    "end": KindRule(in_allowed=True, out_max=0, terminal=True),
}


@dataclass
class FlowValidation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _extract_kind(node: dict[str, Any]) -> str | None:
    # Frontend stores kind under data.kind.
    data = node.get("data") if isinstance(node, dict) else None
    if isinstance(data, dict) and isinstance(data.get("kind"), str):
        return data["kind"]
    if isinstance(node.get("kind"), str):
        return node["kind"]
    return None


def validate_flow_graph(graph: dict[str, Any] | None) -> FlowValidation:
    """Validate a serialized React Flow graph: {"nodes": [...], "edges": [...]}.

    Returns FlowValidation; .errors block publish, .warnings inform the user.
    """
    res = FlowValidation()
    if not graph:
        res.errors.append("flow_graph is empty")
        return res

    nodes_raw = graph.get("nodes") or []
    edges_raw = graph.get("edges") or []
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        res.errors.append("flow_graph.nodes and .edges must be arrays")
        return res

    nodes_by_id: dict[str, dict[str, Any]] = {}
    for n in nodes_raw:
        if not isinstance(n, dict):
            res.errors.append("node entries must be objects")
            continue
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            res.errors.append("node missing id")
            continue
        kind = _extract_kind(n)
        if kind not in RULES:
            res.errors.append(f"{nid}: unknown kind {kind!r}")
            continue
        nodes_by_id[nid] = {"kind": kind, "raw": n}

    # Exactly one greeting
    roots = [nid for nid, info in nodes_by_id.items() if RULES[info["kind"]].root]
    if not roots:
        res.errors.append("graph must contain a greeting node")
    elif len(roots) > 1:
        res.errors.append(f"graph must have exactly one greeting (found {len(roots)})")

    # Edges
    out_by_src: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in edges_raw:
        if not isinstance(e, dict):
            res.errors.append("edge entries must be objects")
            continue
        eid = e.get("id") or f"{e.get('source')}->{e.get('target')}"
        src = e.get("source")
        tgt = e.get("target")
        if not (isinstance(src, str) and isinstance(tgt, str)):
            res.errors.append(f"edge {eid} missing source/target")
            continue
        if src == tgt:
            res.errors.append(f"edge {eid}: self-loop not allowed")
            continue
        if src not in nodes_by_id or tgt not in nodes_by_id:
            res.errors.append(f"edge {eid}: references unknown node")
            continue
        src_kind = nodes_by_id[src]["kind"]
        tgt_kind = nodes_by_id[tgt]["kind"]
        src_rule = RULES[src_kind]
        tgt_rule = RULES[tgt_kind]
        if src_rule.terminal or src_rule.out_max == 0:
            res.errors.append(f"edge {eid}: {src_kind} cannot have outbound edges")
            continue
        if not tgt_rule.in_allowed:
            res.errors.append(f"edge {eid}: {tgt_kind} cannot receive inbound edges")
            continue
        out_by_src[src].append(e)

    # Outbound limits + labels
    for src, outs in out_by_src.items():
        kind = nodes_by_id[src]["kind"]
        rule = RULES[kind]
        if len(outs) > rule.out_max:
            res.errors.append(
                f"{src} ({kind}) has {len(outs)} outbound edges (max {rule.out_max})"
            )
        if rule.out_needs_label:
            labels: list[str] = []
            for o in outs:
                lab = o.get("label")
                if not isinstance(lab, str) or not lab:
                    res.errors.append(f"{src} ({kind}): outbound edge missing label")
                    continue
                labels.append(lab.lower())
            if rule.allowed_labels:
                for lab in labels:
                    if lab not in rule.allowed_labels:
                        res.errors.append(
                            f"{src} ({kind}): label {lab!r} not in {list(rule.allowed_labels)}"
                        )
            if len(labels) != len(set(labels)):
                res.errors.append(f"{src} ({kind}): duplicate branch labels")

    # Cycle detection (DFS from each root)
    if not res.errors and roots:
        adj: dict[str, list[str]] = defaultdict(list)
        for outs in out_by_src.values():
            for e in outs:
                adj[e["source"]].append(e["target"])

        WHITE, GREY, BLACK = 0, 1, 2
        color = dict.fromkeys(nodes_by_id, WHITE)

        def dfs(start: str) -> bool:
            stack: list[tuple[str, int]] = [(start, 0)]
            color[start] = GREY
            while stack:
                node, idx = stack[-1]
                kids = adj.get(node, [])
                if idx >= len(kids):
                    color[node] = BLACK
                    stack.pop()
                    continue
                stack[-1] = (node, idx + 1)
                nxt = kids[idx]
                c = color.get(nxt, WHITE)
                if c == GREY:
                    return True
                if c == WHITE:
                    color[nxt] = GREY
                    stack.append((nxt, 0))
            return False

        for r in roots:
            if color[r] == WHITE and dfs(r):
                res.errors.append("graph contains a cycle")
                break

    # Reachability + dead-end warnings
    if len(roots) == 1:
        adj2: dict[str, list[str]] = defaultdict(list)
        for outs in out_by_src.values():
            for e in outs:
                adj2[e["source"]].append(e["target"])
        seen: set[str] = set()
        stack = [roots[0]]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj2.get(cur, []))
        for nid in nodes_by_id:
            if nid not in seen:
                res.warnings.append(f"{nid} unreachable from greeting")

    # Non-terminal nodes without outbound
    for nid, info in nodes_by_id.items():
        rule = RULES[info["kind"]]
        if rule.terminal:
            continue
        if not out_by_src.get(nid):
            res.warnings.append(f"{nid} ({info['kind']}) has no outbound edge")

    return res
