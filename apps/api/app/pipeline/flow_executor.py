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
  collect    — push per-step prompt, wait for user turn (NL-classified next)
  slot_fill  — gather required slots one at a time, advance when complete
  tool_call  — fire bound tool with mapped args; branch success/error
  kb_lookup  — inline KB search, inject hits as system note, advance
  condition  — LLM yes/no classifier on recent transcript, branch
  end        — close pipeline
  voicemail  — speak prompt, close pipeline
  api        — POST node.webhook with last context, inject response, advance
  transfer   — emit transfer tool call, close pipeline

Anything beyond the V1 surface (e.g. unknown kinds) falls through to the
next outbound edge with a warning, mirroring the validator's policy.

Per-node tools: a node can carry `data.tools` (list of tool names). When that
node is active, the Pipeline's LLM-visible tool set is replaced with the
node's subset (deduped against the global agent tools). On exit, the global
set is restored. This matches Retell's per-state tool binding pattern.

Edge transitions: edges may carry `data.condition` (natural-language). When
a non-condition node has > 1 outbound edge with conditions, the executor
runs an N-way classifier after the user turn and routes accordingly.
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

        # source_id → list[(target_id, label_lower, condition_text)]
        # `label` keeps backwards-compat with yes/no condition routing;
        # `condition` carries NL transition text (Retell-style) for N-way
        # routing on collect / slot_fill / tool_call outbound edges.
        self._edges: dict[str, list[tuple[str, str | None, str | None]]] = {}
        for e in edges_raw:
            if not isinstance(e, dict):
                continue
            src, tgt = e.get("source"), e.get("target")
            if not (isinstance(src, str) and isinstance(tgt, str)):
                continue
            label = e.get("label")
            label = label.lower() if isinstance(label, str) else None
            data = e.get("data") if isinstance(e.get("data"), dict) else {}
            condition = (data.get("condition") or "").strip() or None
            self._edges.setdefault(src, []).append((tgt, label, condition))

        # Stash the agent's full tool set so per-node `tools` overrides
        # can be unwound on exit. `cfg.tools` itself is mutated each node
        # entry so the next LLM turn sees the right subset.
        self._base_tools: list[dict] = list(cfg.tools or [])
        # tool_call nodes set this flag at enter-time when they want a
        # confirmation turn before firing. The next user turn's confirm
        # classifier reads + clears this.
        self._pending_confirm: dict[str, bool] = {}

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
            for tgt, lab, _cond in outs:
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
            await self._advance_with_nl(cur)
            return
        if nv.kind == "slot_fill":
            # Loop in-place until every required slot is in the var bag.
            missing = self._missing_slots(nv)
            if missing:
                self._inject_slot_prompt(nv, missing)
                return
            await self._enter_after(cur)
            return
        if nv.kind == "tool_call":
            # Confirm-before-fire path waits for a user "yes" turn.
            if self._pending_confirm.get(cur):
                approved = await self._classify_confirm()
                self._pending_confirm.pop(cur, None)
                if approved:
                    await self._do_tool_call(nv)
                else:
                    # User said no — go back upstream slot_fill if any,
                    # else stay in this node and reprompt.
                    self.pipe.set_step_prompt(
                        self._render(nv.data.get("retry_prompt"))
                        or "Which detail should we change?"
                    )

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
            self._apply_node_tools(nv)
            prompt = isinstance(nv.data.get("prompt"), str) and nv.data["prompt"].strip()
            self.pipe.set_step_prompt(self._render(prompt) or None)
            return  # wait for user turn → _on_turn_end advances
        if nv.kind == "slot_fill":
            self._apply_node_tools(nv, ensure=("extract_data",))
            missing = self._missing_slots(nv)
            if not missing:
                # Already satisfied (came in with vars populated upstream).
                await self._enter_after(nid)
                return
            self._inject_slot_prompt(nv, missing)
            return  # wait for next user turn
        if nv.kind == "tool_call":
            self._apply_node_tools(nv)
            if nv.data.get("confirm_before_fire"):
                self._pending_confirm[nid] = True
                await self._speak(self._confirm_text(nv))
                self.pipe.set_step_prompt(
                    "Wait for user confirmation. If they agree (yes / confirm / book it),"
                    " the next turn fires the tool. Otherwise ask which detail to change."
                )
                return
            await self._do_tool_call(nv)
            return
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

    # --- slot fill ----------------------------------------------------------

    def _slot_specs(self, nv: _NodeView) -> list[dict[str, Any]]:
        """Normalised list of slot specs from node data.

        Each spec is `{name, prompt, required, type, retry_prompt}`. Missing
        fields default to sensible values so authors can write `[{"name":"x"}]`.
        """
        raw = nv.data.get("slots")
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            name = (s.get("name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "prompt": (s.get("prompt") or "").strip(),
                    "required": bool(s.get("required", True)),
                    "type": (s.get("type") or "string").strip(),
                    "retry_prompt": (s.get("retry_prompt") or "").strip(),
                }
            )
        return out

    def _missing_slots(self, nv: _NodeView) -> list[dict[str, Any]]:
        return [s for s in self._slot_specs(nv) if s["required"] and not self._vars.get(s["name"])]

    def _inject_slot_prompt(self, nv: _NodeView, missing: list[dict[str, Any]]) -> None:
        # One-shot system note: tell the LLM what to ask + that it should call
        # extract_data with whatever it learns. The LLM stays in-node until
        # every required slot is on the var bag.
        slot_lines: list[str] = []
        for s in missing:
            hint = s["prompt"] or s["type"]
            extras: list[str] = []
            if s["type"] == "email":
                extras.append("spell-back letter by letter before extracting")
            elif s["type"] == "phone":
                extras.append("read back digit by digit before extracting")
            elif s["type"] == "iso_datetime":
                extras.append(
                    "convert relative dates like 'tomorrow 5pm' to ISO-8601 with the "
                    "user's timezone offset before extracting"
                )
            tail = f" — {'; '.join(extras)}" if extras else ""
            slot_lines.append(f"`{s['name']}` ({hint}){tail}")
        wanted = "\n  - ".join(slot_lines)
        intent = (self._render(nv.data.get("prompt")) or "").strip()
        # Show progress so the user perceives momentum even when looping.
        filled = [s["name"] for s in self._slot_specs(nv) if self._vars.get(s["name"])]
        progress = f"Filled so far: {', '.join(filled)}. " if filled else ""
        instructions = (
            (intent + "\n" if intent else "")
            + progress
            + "Still need:\n  - "
            + wanted
            + "\n\nAsk for ONE of these next. "
            "When the user supplies a value, IMMEDIATELY call the extract_data tool "
            "with a JSON object mapping the EXACT slot name to the value. Example: "
            '`{"data": {"attendee_email": "alice@example.com"}}`. '
            "If you hear it indistinctly, ask them to repeat — do NOT extract a guess. "
            "Never claim you've saved anything without calling the tool."
        )
        self.pipe.set_step_prompt(instructions)
        # Re-emit flow_node so the UI's rotating animation pulses on each
        # loop turn — gives the user visible feedback that the agent is
        # still on this step, not stuck.
        try:
            self.pipe.emit_event(
                "flow_node",
                data={
                    "node_id": nv.id,
                    "kind": nv.kind,
                    "progress": {"filled": filled, "missing": [s["name"] for s in missing]},
                },
            )
        except Exception:
            pass

    # --- tool dispatch ------------------------------------------------------

    def _confirm_text(self, nv: _NodeView) -> str:
        tmpl = (nv.data.get("confirm_message") or "").strip()
        if tmpl:
            return self._render(tmpl)
        # Auto-build "About to call X with Y=…, Z=…. Confirm?" read-back.
        args = self._tool_args_from_slots(nv)
        readback = ", ".join(f"{k}={v}" for k, v in args.items() if v is not None)
        tool_name = nv.data.get("tool") or "this action"
        return f"Just to confirm — I'll {tool_name} with {readback}. Sound right?"

    def _tool_args_from_slots(self, nv: _NodeView) -> dict[str, Any]:
        """Build the tool args dict from `arg_map` + var bag.

        `arg_map` is `{tool_param: slot_name}`. Missing entries fall back to
        a 1:1 match against `_vars`.
        """
        arg_map = nv.data.get("arg_map") if isinstance(nv.data.get("arg_map"), dict) else {}
        out: dict[str, Any] = {}
        for param, slot in arg_map.items():
            val = self._lookup_var(slot if isinstance(slot, str) else param)
            if val is not None:
                out[param] = val
        # If no explicit map, copy all matching keys from the var bag.
        if not out:
            for k, v in self._vars.items():
                if v is not None and isinstance(k, str):
                    out[k] = v
        return out

    async def _classify_confirm(self) -> bool:
        """Tiny LLM call: did the user just agree to fire the tool?"""
        recent = [
            {"role": m.get("role"), "content": m.get("content")}
            for m in self.pipe._messages[-4:]  # type: ignore[attr-defined]
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "Classify the user's last reply. Did they explicitly confirm / agree "
                    "to proceed with the proposed action? Reply with exactly one token: "
                    "yes or no."
                ),
            },
            *recent,
        ]
        text = ""
        try:
            async for ev in self.pipe._llm(  # type: ignore[attr-defined]
                messages=messages, tools=None
            ):
                if isinstance(ev, TextChunk):
                    text += ev.text
                elif isinstance(ev, TurnComplete):
                    break
        except Exception as exc:
            log.warning("flow.confirm.err", err=str(exc))
            return False
        return text.strip().lower().startswith("yes")

    async def _do_tool_call(self, nv: _NodeView) -> None:
        import asyncio as _asyncio

        tool_name = nv.data.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            log.warning("flow.tool.missing_ref", node=nv.id)
            await self._enter_after(nv.id)
            return

        args = self._tool_args_from_slots(nv)
        log.info("flow.tool.fire", node=nv.id, tool=tool_name, args=args)

        # Kick off the dispatch in parallel with the pre-message TTS so the
        # user hears "booking now…" while the HTTP request is already on
        # the wire. Big latency win — pre-message playback (~1.5s) overlaps
        # with the API round-trip instead of stacking.
        async def _fire() -> dict[str, Any]:
            if self.pipe._dispatch is None:  # type: ignore[attr-defined]
                return {"error": "no_tool_dispatch"}
            try:
                return await self.pipe._dispatch(  # type: ignore[attr-defined]
                    ToolCall(id=f"flow_{nv.id}", name=tool_name, arguments=args)
                )
            except Exception as exc:
                log.exception("flow.tool.err", node=nv.id, err=str(exc))
                return {"error": "tool_failed", "detail": str(exc)}

        dispatch_task = _asyncio.create_task(_fire())
        pre = self._render(nv.data.get("pre_message"))
        if pre:
            await self._speak(pre)
        result = await dispatch_task

        is_error = isinstance(result, dict) and "error" in result
        # Stash the result under the node id so downstream `{{node_id.key}}`
        # placeholders can quote it. Also under the tool name for ergonomics.
        self._vars[nv.id] = result
        self._vars[tool_name] = result
        self.pipe.emit_event(
            "tool_result",
            text=tool_name,
            data={"id": f"flow_{nv.id}", "result": result},
        )

        msg = self._render(nv.data.get("error_message" if is_error else "success_message"))
        if msg:
            await self._speak(msg)

        # Route via outbound label.
        nxt = self._next(nv.id, label="error" if is_error else "success")
        if nxt is None:
            # No labelled branch — fall through to first outbound, or terminate.
            nxt = self._next(nv.id)
        if nxt:
            await self._enter(nxt)
        else:
            await self._terminate()

    # --- per-node tools -----------------------------------------------------

    def _apply_node_tools(self, nv: _NodeView, *, ensure: tuple[str, ...] = ()) -> None:
        """Set Pipeline's visible tool list for this node's lifetime.

        Semantics:
          * If node declares `data.tools = [...]`, intersect the base agent
            tools by name + tack on anything in `ensure`.
          * If no override, start from the full base set, then still tack on
            `ensure` so callers (e.g. slot_fill) can guarantee a builtin is
            visible to the LLM regardless of agent-level config.
        """
        from app.tools.builtins import REGISTRY

        overrides = nv.data.get("tools")
        wanted: set[str] | None
        if isinstance(overrides, list):
            wanted = {t for t in overrides if isinstance(t, str)} | set(ensure)
        else:
            wanted = None  # accept all base tools, plus `ensure`

        kept: list[dict] = []
        seen: set[str] = set()
        for t in self._base_tools:
            fn = t.get("function") if isinstance(t, dict) else None
            name = fn.get("name") if isinstance(fn, dict) else None
            if not isinstance(name, str) or name in seen:
                continue
            if wanted is None or name in wanted:
                kept.append(t)
                seen.add(name)
        # Pull in any tool listed in `ensure` that isn't already on the agent
        # (e.g. extract_data on a slot_fill node when the agent didn't bind it).
        for name in ensure:
            if name in seen:
                continue
            entry = REGISTRY.get(name)
            if entry:
                kept.append(entry["definition"])
                seen.add(name)
        self.cfg.tools = kept

    # --- NL transition routing (Retell-style) ------------------------------

    async def _advance_with_nl(self, from_id: str) -> None:
        """Pick the outbound edge whose `condition` best matches the latest turn.

        Falls back to single-outbound behaviour when only one edge exists.
        """
        outs = self._edges.get(from_id) or []
        if not outs:
            return
        if len(outs) == 1:
            await self._enter(outs[0][0])
            return
        conditioned = [(tgt, cond) for tgt, _lab, cond in outs if cond]
        if not conditioned:
            # No conditions authored — first outbound wins for compat.
            await self._enter(outs[0][0])
            return
        chosen = await self._classify_nl(conditioned)
        await self._enter(chosen or outs[0][0])

    async def _classify_nl(self, branches: list[tuple[str, str]]) -> str | None:
        """N-way classifier: pick the branch whose condition matches the
        recent conversation. Returns target node id, or None on parse failure.
        """
        if not branches:
            return None
        lines = [f"{i + 1}. {cond}" for i, (_tgt, cond) in enumerate(branches)]
        recent = [
            {"role": m.get("role"), "content": m.get("content")}
            for m in self.pipe._messages[-6:]  # type: ignore[attr-defined]
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
        ]
        prompt = (
            "Classify the conversation into ONE of the following branches.\n"
            + "\n".join(lines)
            + "\nReply with the number only."
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
        except Exception as exc:
            log.warning("flow.classify_nl.err", err=str(exc))
            return None
        m = re.search(r"\d+", text)
        if not m:
            return None
        idx = int(m.group(0)) - 1
        if 0 <= idx < len(branches):
            return branches[idx][0]
        return None

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
