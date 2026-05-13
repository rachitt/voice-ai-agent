"""Runtime executor for AgentVersion.flow_graph.

The graph is the same shape the React Flow builder emits:

    {"nodes": [{"id": ..., "data": {"kind": ..., "prompt": ..., ...}}, ...],
     "edges": [{"id": ..., "source": ..., "target": ..., "label": ...}, ...]}

Validation lives in `app.schemas.flow_graph_validators` and is enforced at
publish time, so by the time we run we can assume:
  • exactly one `greeting` root
  • DAG (no cycles)
  • condition nodes have unique yes/no labelled outbound edges

The executor sits on top of `Pipeline`: Pipeline still owns STT/LLM/TTS,
the executor decides what system prompt + side effects apply at each step
and advances the graph after every conversational turn.

V1 node-kind coverage:
  greeting   — speak prompt, advance
  collect    — push per-step prompt, wait for user turn
  kb_lookup  — inline KB search, inject hits as system note, advance
  condition  — LLM yes/no classifier on recent transcript, branch
  end        — close pipeline
  voicemail  — speak prompt, close pipeline
  api        — POST node.webhook with last context, inject response, advance
  transfer   — emit transfer tool call, close pipeline

Anything beyond the V1 surface (e.g. unknown kinds) falls through to the
next outbound edge with a warning, mirroring the validator's policy.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.logging import log
from app.pipeline.orchestrator import (
    AgentConfig,
    Pipeline,
    TextChunk,
    ToolCall,
    TurnComplete,
)

# Callback signature: kb_id, query, top_k → dict result.
KbDispatchFn = Callable[..., Awaitable[dict[str, Any]]]
# Callback signature: e164_to, summary → None. Used to bridge transfer nodes
# back to the live Telnyx connection.
TransferFn = Callable[..., Awaitable[None]]


@dataclass
class _NodeView:
    id: str
    kind: str
    data: dict[str, Any]


class FlowExecutor:
    def __init__(
        self,
        *,
        graph: dict[str, Any],
        cfg: AgentConfig,
        pipe: Pipeline,
        kb_dispatch: KbDispatchFn | None = None,
        transfer: TransferFn | None = None,
        variables: dict[str, Any] | None = None,
    ) -> None:
        self.cfg = cfg
        self.pipe = pipe
        self._kb = kb_dispatch
        self._transfer = transfer
        self._closed = False
        self.current_id: str | None = None
        # Mutable variable bag used for {{var}} interpolation. The caller can
        # pass the same dict they want updated as `api` nodes return data —
        # we mutate in place so the live Call.dynamic_variables stays in sync.
        self._vars: dict[str, Any] = variables if variables is not None else {}

        nodes_raw = graph.get("nodes") or []
        edges_raw = graph.get("edges") or []
        self._nodes: dict[str, _NodeView] = {}
        for n in nodes_raw:
            if not isinstance(n, dict):
                continue
            nid = n.get("id")
            data = n.get("data") if isinstance(n.get("data"), dict) else {}
            kind = data.get("kind") or n.get("kind")
            if isinstance(nid, str) and isinstance(kind, str):
                self._nodes[nid] = _NodeView(id=nid, kind=kind, data=data)

        # source_id → list[(target_id, label_lower)]
        self._edges: dict[str, list[tuple[str, str | None]]] = {}
        for e in edges_raw:
            if not isinstance(e, dict):
                continue
            src, tgt = e.get("source"), e.get("target")
            if not (isinstance(src, str) and isinstance(tgt, str)):
                continue
            label = e.get("label")
            label = label.lower() if isinstance(label, str) else None
            self._edges.setdefault(src, []).append((tgt, label))

    # --- variable interpolation --------------------------------------------

    _VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")

    def _render(self, text: str | None) -> str:
        """Substitute {{var}} placeholders using `self._vars`. Missing keys
        render as empty string and emit a debug log so authors notice."""
        if not text:
            return ""

        def _sub(m: re.Match[str]) -> str:
            key = m.group(1)
            val = self._lookup_var(key)
            if val is None:
                log.info("flow.var.miss", key=key)
                return ""
            if isinstance(val, str):
                return val
            try:
                return json.dumps(val) if isinstance(val, (dict, list)) else str(val)
            except Exception:
                return str(val)

        return self._VAR_RE.sub(_sub, text)

    def _lookup_var(self, key: str) -> Any:
        """Resolve dotted keys like `customer.email` against the vars bag."""
        if "." not in key:
            return self._vars.get(key)
        head, *rest = key.split(".")
        cur: Any = self._vars.get(head)
        for part in rest:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    # --- public API ---------------------------------------------------------

    async def start(self) -> None:
        """Wire the turn_end hook + take the first step."""
        self.pipe.on_turn_end = self._on_turn_end
        root = self._root()
        if root is None:
            log.warning("flow.no_root", node_ids=list(self._nodes))
            return
        # Greeting prompt becomes the spoken first_message.
        greeting_text = self._spoken_text(root)
        self.cfg.first_message = greeting_text
        await self.pipe.start()
        # Greeting is conversational only for its spoken message — walk forward.
        await self._enter_after(root.id)

    # --- internals ----------------------------------------------------------

    def _root(self) -> _NodeView | None:
        for nv in self._nodes.values():
            if nv.kind == "greeting":
                return nv
        return None

    def _spoken_text(self, nv: _NodeView) -> str:
        raw = (
            (isinstance(nv.data.get("prompt"), str) and nv.data["prompt"].strip())
            or (isinstance(nv.data.get("title"), str) and nv.data["title"].strip())
            or "Hello."
        )
        return self._render(raw) or "Hello."

    def _next(self, nid: str, *, label: str | None = None) -> str | None:
        outs = self._edges.get(nid) or []
        if label is not None:
            for tgt, lab in outs:
                if lab == label.lower():
                    return tgt
            # No exact label match — fall through to first outbound.
        return outs[0][0] if outs else None

    async def _on_turn_end(self) -> None:
        if self._closed:
            return
        cur = self.current_id
        if cur is None:
            return
        nv = self._nodes.get(cur)
        if nv is None:
            return
        if nv.kind == "collect":
            await self._enter_after(cur)

    async def _enter_after(self, from_id: str) -> None:
        nxt = self._next(from_id)
        if nxt is None:
            return
        await self._enter(nxt)

    async def _enter(self, nid: str) -> None:
        """Apply node's effect; chain forward through deterministic nodes."""
        nv = self._nodes.get(nid)
        if nv is None:
            log.warning("flow.unknown_node", node_id=nid)
            return
        self.current_id = nid
        log.info("flow.enter", node=nid, kind=nv.kind)
        # Surface the visited node to the WS so the builder canvas can
        # highlight whichever step the agent is at right now. Best-effort —
        # if the pipe is mid-shutdown the queue may reject, which is fine
        # since the call is ending anyway.
        try:
            self.pipe.emit_event("flow_node", data={"node_id": nid, "kind": nv.kind})
        except Exception:
            pass

        if nv.kind == "end":
            await self._terminate()
            return
        if nv.kind == "voicemail":
            raw = (
                isinstance(nv.data.get("prompt"), str) and nv.data["prompt"].strip()
            ) or "Please leave a message after the tone."
            await self._speak(self._render(raw))
            await self._terminate()
            return
        if nv.kind == "transfer":
            await self._do_transfer(nv)
            await self._terminate()
            return
        if nv.kind == "kb_lookup":
            await self._do_kb(nv)
            await self._enter_after(nid)
            return
        if nv.kind == "api":
            await self._do_api(nv)
            await self._enter_after(nid)
            return
        if nv.kind == "collect":
            prompt = isinstance(nv.data.get("prompt"), str) and nv.data["prompt"].strip()
            self.pipe.set_step_prompt(self._render(prompt) or None)
            return  # wait for user turn → _on_turn_end advances
        if nv.kind == "condition":
            # Condition classifies the just-completed turn synchronously, then
            # routes by yes/no label. We don't wait for another user turn —
            # the conversation history already contains the signal.
            label = await self._classify(nv)
            log.info("flow.condition.decision", node=nv.id, label=label)
            nxt = self._next(nid, label=label)
            if nxt:
                await self._enter(nxt)
            return
        # Unknown / unimplemented: fall through.
        log.warning("flow.unhandled_kind", node=nid, kind=nv.kind)
        await self._enter_after(nid)

    async def _terminate(self) -> None:
        """Close the pipeline. `Pipeline.close` is now self-cancel-safe so this
        works whether called from the turn task or outside it."""
        if self._closed:
            return
        self._closed = True
        log.info("flow.terminate")
        await self.pipe.close()

    async def _speak(self, text: str) -> None:
        # Reuses Pipeline._speak through the public start() path is not available
        # mid-flow; pipe.append_system_note + a follow-up turn would be too slow.
        # Best to drive TTS directly via the same code Pipeline.start() uses.
        await self.pipe._speak(text, also_as_event=True)  # type: ignore[attr-defined]

    # --- node effects -------------------------------------------------------

    async def _do_kb(self, nv: _NodeView) -> None:
        if self._kb is None:
            log.info("flow.kb.skip_no_dispatch")
            return
        kb_id = nv.data.get("kb_id") or (
            self.cfg.knowledge_base_ids[0] if self.cfg.knowledge_base_ids else None
        )
        query = self._render((nv.data.get("query_template") or "").strip())
        top_k = int(nv.data.get("top_k") or 5)
        top_k = max(1, min(top_k, 20))
        if not kb_id or not query:
            log.info("flow.kb.skip_unset", kb_id=kb_id, has_query=bool(query))
            return
        try:
            res = await self._kb(kb_id=kb_id, query=query, top_k=top_k)
        except Exception as exc:
            log.warning("flow.kb.err", err=str(exc))
            return
        snippet = _format_kb_for_prompt(res)
        if snippet:
            self.pipe.append_system_note(snippet)

    async def _do_api(self, nv: _NodeView) -> None:
        url = self._render((nv.data.get("webhook") or "").strip())
        if not url:
            return
        body = {
            "node_id": nv.id,
            "title": nv.data.get("title"),
            "dynamic_variables": dict(self._vars),
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(url, json=body)
            text = r.text[:1000] if r.text else ""
            # If the response is JSON, merge top-level keys into the var bag
            # so downstream nodes can reference them via {{key}}.
            try:
                parsed = r.json()
                if isinstance(parsed, dict):
                    self._vars.update(parsed)
            except Exception:
                pass
            note = (
                f"Result from step '{nv.data.get('title') or nv.id}' "
                f"(status {r.status_code}): {text}"
            )
            self.pipe.append_system_note(note)
        except Exception as exc:
            log.warning("flow.api.err", url=url, err=str(exc))

    async def _do_transfer(self, nv: _NodeView) -> None:
        if self._transfer is None:
            log.info("flow.transfer.skip_no_dispatch", node=nv.id)
            return
        to = self._render((nv.data.get("webhook") or "").strip())
        summary = self._render((nv.data.get("prompt") or "").strip())
        if not to:
            log.info("flow.transfer.skip_no_target", node=nv.id)
            return
        try:
            await self._transfer(to=to, summary=summary)
        except Exception as exc:
            log.warning("flow.transfer.err", to=to, err=str(exc))

    # --- condition classifier ----------------------------------------------

    async def _classify(self, nv: _NodeView) -> str:
        """Run a tiny single-shot LLM call to decide yes/no for a condition node.

        Returns the lowercase label string, defaulting to 'no' when uncertain
        so callers fall back to a safer branch.
        """
        criterion = self._render(
            (nv.data.get("prompt") or "").strip() or (nv.data.get("title") or "")
        )
        recent: list[dict] = []
        # Re-use the pipeline's recent transcript view (last ~4 messages).
        for m in self.pipe._messages[-6:]:  # type: ignore[attr-defined]
            role = m.get("role")
            content = m.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content:
                recent.append({"role": role, "content": content})

        prompt = (
            "You are a strict classifier for an agent flow. "
            f"Criterion: {criterion or '(none — say no)'}. "
            "Reply with exactly one token: yes or no."
        )
        messages = [{"role": "system", "content": prompt}, *recent]

        text = ""
        try:
            async for ev in self.pipe._llm(  # type: ignore[attr-defined]
                messages=messages, tools=None
            ):
                if isinstance(ev, TextChunk):
                    text += ev.text
                elif isinstance(ev, TurnComplete):
                    break
                elif isinstance(ev, ToolCall):
                    # Classifier should not call tools; ignore.
                    continue
        except Exception as exc:
            log.warning("flow.classify.err", err=str(exc))
            return "no"

        t = text.strip().lower()
        if t.startswith("yes"):
            return "yes"
        if t.startswith("no"):
            return "no"
        return "no"


def _format_kb_for_prompt(res: Any) -> str:
    """Render a kb_lookup result into a single system-note string."""
    if not isinstance(res, dict):
        return ""
    hits = res.get("hits") or []
    if not isinstance(hits, list) or not hits:
        return ""
    parts: list[str] = ["Knowledge base context (use these snippets if relevant):"]
    for i, h in enumerate(hits[:5], start=1):
        if not isinstance(h, dict):
            continue
        body = (h.get("text") or "").strip()
        if not body:
            continue
        parts.append(f"[{i}] {body[:600]}")
    return "\n".join(parts) if len(parts) > 1 else ""


def has_executable_graph(graph: Any) -> bool:
    """True iff `graph` has at least one greeting node and one edge."""
    if not isinstance(graph, dict):
        return False
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return False
    has_greeting = False
    for n in nodes:
        if not isinstance(n, dict):
            continue
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        if (data.get("kind") or n.get("kind")) == "greeting":
            has_greeting = True
            break
    return has_greeting and bool(edges)


def _safe_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj)
    except Exception:
        return repr(obj)
