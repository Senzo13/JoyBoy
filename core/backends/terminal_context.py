"""Context compaction and tool-call protocol middleware for terminal agent."""

from __future__ import annotations

from collections import defaultdict
import json
import re
import unicodedata
from typing import Any, Dict, List

from core.agent_runtime import tool_signature, truncate_middle


MAX_DELEGATE_SUBAGENT_CALLS_PER_RESPONSE = 3
DEFAULT_TOOL_CALL_BATCH_TYPE_LIMIT = 10
TOOL_CALL_BATCH_TYPE_LIMITS = {
    "list_files": 2,
    "glob": 4,
    "search": 4,
    "read_file": 8,
    "bash": 3,
    "tool_search": 2,
    "write_todos": 2,
    "think": 2,
    "web_search": 2,
    "web_fetch": 3,
    "load_skill": 2,
    "remember_fact": 2,
    "list_memory": 2,
    "open_workspace": 1,
    "write_files": 2,
    "write_file": 8,
    "edit_file": 8,
    "delete_file": 8,
}
COMPACTED_HISTORY_HEADER = "[COMPACTED HISTORY SUMMARY]"
COMPACTED_LOOP_HEADER = "[COMPACTED LOOP SUMMARY]"
MAX_COMPACTION_SUMMARY_POINTS = 8


class TerminalContextMixin:
    """Prompt compaction, tool-call parsing, and tool protocol repair."""

    @staticmethod
    def _is_compaction_summary_content(content: str) -> bool:
        text = str(content or "").strip()
        return text.startswith(COMPACTED_HISTORY_HEADER) or text.startswith(COMPACTED_LOOP_HEADER)

    def _is_compaction_summary_message(self, message: Any) -> bool:
        if not isinstance(message, dict):
            return False
        return self._is_compaction_summary_content(str(message.get("content", "") or ""))

    @staticmethod
    def _compact_summary_snippet(text: str, limit: int = 160) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return ""
        return truncate_middle(normalized, limit)

    def _extract_compaction_summary_lines(self, content: str) -> List[str]:
        lines: List[str] = []
        for raw_line in str(content or "").splitlines():
            line = raw_line.strip()
            if not line.startswith("- "):
                continue
            snippet = self._compact_summary_snippet(line[2:])
            if snippet:
                lines.append(snippet)
        return lines

    def _extract_tool_result_summary(self, tool_name: str, content: str) -> str:
        text = str(content or "")
        if not text.strip():
            return ""
        preferred_prefixes = ("summary:", "error:", "stderr:", "stdout:", "status:")
        fallback = ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("[RESULT"):
                continue
            lower = line.lower()
            if lower.startswith("command:") or lower.startswith("output:"):
                continue
            if lower.startswith(preferred_prefixes):
                return self._compact_summary_snippet(line)
            if not fallback:
                fallback = line
        if fallback:
            return self._compact_summary_snippet(fallback)
        return self._compact_summary_snippet(text)

    def _is_low_signal_user_message(self, content: str) -> bool:
        text = unicodedata.normalize("NFKD", str(content or "")).encode("ascii", "ignore").decode("ascii").lower()
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return True
        if text.startswith("[active todo list]"):
            return True
        low_signal = {
            "continue",
            "continue encore",
            "continue si tu n'avais pas fini",
            "continue si tu n'avais pas tout fini",
            "ok",
            "ok bref",
            "vas y",
            "go",
            "yo",
            "yo mec",
            "salut",
            "merci",
            "fait le",
        }
        if text in low_signal:
            return True
        if len(text) <= 6 and re.fullmatch(r"[a-z0-9!?.,' -]+", text):
            return True
        return False

    def _summarize_message_for_compaction(self, message: Dict[str, Any]) -> List[str]:
        if not isinstance(message, dict):
            return []

        role = str(message.get("role") or "")
        content = str(message.get("content", "") or "")
        lines: List[str] = []

        if self._is_compaction_summary_content(content):
            return self._extract_compaction_summary_lines(content)

        if role == "tool":
            tool_name = str(message.get("tool_name") or message.get("name") or "tool").strip() or "tool"
            summary = self._extract_tool_result_summary(tool_name, content)
            if summary:
                lines.append(f"tool {tool_name}: {summary}")
            return lines

        if role == "assistant" and message.get("tool_calls"):
            tool_names: List[str] = []
            for call in message.get("tool_calls") or []:
                name = self._tool_call_name(call)
                if name and name not in tool_names:
                    tool_names.append(name)
            if tool_names:
                joined = ", ".join(tool_names[:4])
                extra = f" (+{len(tool_names) - 4} more)" if len(tool_names) > 4 else ""
                lines.append(f"assistant used tools: {joined}{extra}")
            return lines

        snippet = self._compact_summary_snippet(content)
        if not snippet:
            return []

        if role == "user":
            if self._is_low_signal_user_message(content):
                return []
            lines.append(f"user asked: {snippet}")
            return lines

        if role == "assistant":
            lines.append(f"assistant noted: {snippet}")
            return lines

        return []

    def _collect_compaction_summary_lines(
        self,
        messages: List[Dict[str, Any]],
        max_points: int = MAX_COMPACTION_SUMMARY_POINTS,
    ) -> List[str]:
        summary_lines: List[str] = []
        seen: set[str] = set()

        for message in messages:
            for line in self._summarize_message_for_compaction(message):
                normalized = unicodedata.normalize("NFKD", line).encode("ascii", "ignore").decode("ascii").lower()
                normalized = re.sub(r"\s+", " ", normalized).strip()
                if not normalized or normalized in seen:
                    continue
                summary_lines.append(line)
                seen.add(normalized)
                if len(summary_lines) >= max_points:
                    return summary_lines
        return summary_lines

    def _build_compaction_summary_message(
        self,
        header: str,
        omitted_count: int,
        summary_lines: List[str],
        guidance: str,
    ) -> Dict[str, str]:
        bullet_lines = summary_lines[:MAX_COMPACTION_SUMMARY_POINTS]
        if not bullet_lines:
            bullet_lines = ["Earlier context was compacted; use the preserved files and latest tool outputs as source of truth."]

        remaining = max(0, len(summary_lines) - len(bullet_lines))
        content_lines = [
            header,
            f"Earlier context compacted: {omitted_count} message(s) folded into this summary.",
            "Key preserved context:",
            *[f"- {line}" for line in bullet_lines],
        ]
        if remaining:
            content_lines.append(f"- {remaining} additional point(s) already compacted.")
        content_lines.extend(["", guidance])
        return {
            "role": "user",
            "content": "\n".join(content_lines),
        }

    def _compact_history(self, history: List[Dict], context_size: int = 4096) -> List[Dict]:
        """Keep recent terminal context inside a rough character budget."""
        max_chars = max(3000, min(12000, int(context_size) * 1))
        visible_history = [
            msg for msg in history
            if str(msg.get("content", "") or "").strip()
        ]
        compact: List[Dict] = []
        total = 0
        for msg in reversed(visible_history[-12:]):
            content = str(msg.get("content", "")).strip()
            role = msg.get("role", "user")
            if not content:
                continue
            if len(content) > 1200:
                content = content[:1200] + "\n... (conversation tronquee)"
            if total + len(content) > max_chars and compact:
                break
            compact.append({"role": role, "content": content})
            total += len(content)
        compact.reverse()
        omitted_messages = visible_history[:-len(compact)] if compact else visible_history
        omitted = len(omitted_messages)
        if omitted:
            summary_lines = self._collect_compaction_summary_lines(omitted_messages)
            compact.insert(0, self._build_compaction_summary_message(
                COMPACTED_HISTORY_HEADER,
                omitted,
                summary_lines,
                "Use the current workspace files and recent messages as source of truth.",
            ))
        return compact

    def _compact_loop_messages(self, messages: List[Dict], context_size: int = 4096) -> List[Dict]:
        """Bound the live agent loop context before each model call."""
        if not messages:
            return messages

        max_chars = max(6000, min(22000, int(context_size) * 3))
        system = messages[0]
        tail = messages[1:]
        prior_summary_messages = [msg for msg in tail if self._is_compaction_summary_message(msg)]
        tail = [msg for msg in tail if not self._is_compaction_summary_message(msg)]
        kept: List[Dict] = []
        total = len(str(system.get("content", "")))

        for msg in reversed(tail):
            compact_msg = dict(msg)
            role = compact_msg.get("role", "user")
            content = str(compact_msg.get("content", "") or "")
            if role == "assistant" and compact_msg.get("tool_calls"):
                compact_msg["tool_calls"] = self._compact_assistant_tool_calls(compact_msg.get("tool_calls"))

            if role == "tool" and len(content) > 3500:
                content = content[:3500] + "\n... (tool result truncated for context)"
            elif role == "assistant" and len(content) > 1600:
                content = content[:1600] + "\n... (assistant text truncated for context)"
            elif role == "user" and len(content) > 3500:
                suffix = "older user text truncated for context" if kept else "user text truncated for context"
                content = content[:3500] + f"\n... ({suffix})"

            compact_msg["content"] = content
            tool_call_len = len(json.dumps(compact_msg.get("tool_calls", []), ensure_ascii=False)) if compact_msg.get("tool_calls") else 0
            msg_len = len(content) + tool_call_len
            if kept and total + msg_len > max_chars:
                break
            kept.append(compact_msg)
            total += msg_len

        kept.reverse()
        omitted_messages = tail[:-len(kept)] if kept else tail
        if omitted_messages or prior_summary_messages:
            summary_lines = self._collect_compaction_summary_lines(prior_summary_messages + omitted_messages)
            summary = self._build_compaction_summary_message(
                COMPACTED_LOOP_HEADER,
                len(omitted_messages) + len(prior_summary_messages),
                summary_lines,
                "Do not restart broad exploration. Rely on preserved tool results or read specific files again.",
            )
            return [system, summary] + kept
        return [system] + kept

    def _compact_assistant_tool_calls(self, tool_calls: Any) -> List[Dict]:
        compact_calls: List[Dict] = []
        for call in tool_calls or []:
            call_dict = dict(call) if isinstance(call, dict) else {}
            function = dict(call_dict.get("function", {})) if isinstance(call_dict.get("function"), dict) else {}
            name = str(function.get("name") or call_dict.get("name") or "")
            raw_args = function.get("arguments", {})
            args = self._parse_tool_arguments(raw_args)

            if args:
                for key in ("content", "new_text", "old_text"):
                    value = args.get(key)
                    if isinstance(value, str) and len(value) > 260:
                        args[key] = f"<omitted {len(value)} chars from terminal history after {name}>"

                for key, value in list(args.items()):
                    if isinstance(value, str) and len(value) > 1200:
                        args[key] = truncate_middle(value, 1200)

                if isinstance(raw_args, dict):
                    function["arguments"] = args
                else:
                    function["arguments"] = json.dumps(args, ensure_ascii=False)

            call_dict["function"] = function
            compact_calls.append(call_dict)
        return compact_calls

    def _normalise_tool_calls_for_history(self, tool_calls: Any, prefix: str = "call") -> List[Dict[str, Any]]:
        """Return provider-neutral tool calls with stable IDs and JSON arguments."""
        normalised: List[Dict[str, Any]] = []
        for index, call in enumerate(tool_calls or []):
            name = self._tool_call_name(call).strip()
            if not name:
                continue

            args = self._tool_call_args(call)
            call_id = self._tool_call_id(call).strip()
            if not call_id:
                safe_name = re.sub(r"[^a-zA-Z0-9_:-]+", "_", name).strip("_") or "tool"
                call_id = f"{prefix}_{index}_{safe_name}"

            normalised.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            })
        return normalised

    def _patch_dangling_tool_messages(self, messages: List[Dict]) -> List[Dict]:
        """Normalize assistant/tool pairs before the next model call."""
        if not messages:
            return messages

        has_tool_protocol = any(
            isinstance(message, dict)
            and (
                (message.get("role") == "assistant" and message.get("tool_calls"))
                or message.get("role") == "tool"
            )
            for message in messages
        )
        if not has_tool_protocol:
            return messages

        patched: List[Dict] = []
        patch_count = 0
        orphan_count = 0
        pending_tool_ids: set[str] = set()

        def append_missing_outputs(before_role: str | None = None) -> None:
            nonlocal patch_count
            if not pending_tool_ids:
                return
            for call_id in list(pending_tool_ids):
                patched.append({
                    "role": "tool",
                    "tool_name": "tool",
                    "tool_call_id": call_id,
                    "content": (
                        "[TERMINAL GUARDRAIL] Tool call did not return an output "
                        f"before {before_role or 'the next model call'}. Treat it as failed and continue "
                        "from the available context."
                    ),
                })
                patch_count += 1
            pending_tool_ids.clear()

        for message in messages:
            if not isinstance(message, dict):
                append_missing_outputs("a non-message item")
                patched.append(message)
                continue

            role = message.get("role")
            if role == "tool":
                call_id = str(message.get("tool_call_id") or "").strip()
                if call_id and call_id in pending_tool_ids:
                    patched.append(message)
                    pending_tool_ids.remove(call_id)
                else:
                    orphan_count += 1
                    tool_name = str(message.get("tool_name") or message.get("name") or "tool").strip()
                    patched.append({
                        "role": "user",
                        "content": (
                            "[COMPACTED TOOL RESULT]\n"
                            f"Tool result ({tool_name}) was kept after its assistant tool call left the context:\n"
                            f"{message.get('content', '')}"
                        ),
                    })
                continue

            if role in {"assistant", "user", "system"}:
                append_missing_outputs(role)

            if role == "assistant":
                if message.get("tool_calls"):
                    message = dict(message)
                    message["tool_calls"] = self._normalise_tool_calls_for_history(message.get("tool_calls"))
                patched.append(message)
                for call in message.get("tool_calls") or []:
                    call_id = self._tool_call_id(call)
                    if call_id:
                        pending_tool_ids.add(call_id)
                continue

            patched.append(message)

        append_missing_outputs("the next model call")

        if patch_count or orphan_count:
            print(
                f"[BRAIN] Patched tool protocol: "
                f"{patch_count} dangling output(s), {orphan_count} orphan tool result(s)"
            )
        return patched

    def _limit_delegate_subagent_calls(self, tool_calls: Any) -> tuple[List[Any], int]:
        kept: List[Any] = []
        delegate_count = 0
        dropped = 0
        seen_delegate_keys: set[str] = set()
        for call in tool_calls or []:
            name = self._tool_call_name(call)
            if name == "delegate_subagent":
                key = self._delegate_subagent_call_key(call)
                if not key:
                    dropped += 1
                    continue
                if key in seen_delegate_keys:
                    dropped += 1
                    continue
                seen_delegate_keys.add(key)
                delegate_count += 1
                if delegate_count > MAX_DELEGATE_SUBAGENT_CALLS_PER_RESPONSE:
                    dropped += 1
                    continue
            kept.append(call)
        return kept, dropped

    def _limit_tool_calls_by_type(self, tool_calls: Any) -> tuple[List[Any], Dict[str, int]]:
        kept: List[Any] = []
        counts: Dict[str, int] = defaultdict(int)
        dropped: Dict[str, int] = defaultdict(int)
        for call in tool_calls or []:
            name = self._tool_call_name(call)
            if not name or name == "delegate_subagent":
                kept.append(call)
                continue
            counts[name] += 1
            limit = TOOL_CALL_BATCH_TYPE_LIMITS.get(name, DEFAULT_TOOL_CALL_BATCH_TYPE_LIMIT)
            if counts[name] > limit:
                dropped[name] += 1
                continue
            kept.append(call)
        return kept, dict(dropped)

    def _delegate_subagent_call_key(self, call: Any) -> str:
        args = self._tool_call_args(call)
        task = re.sub(r"\s+", " ", str(args.get("task", "") or "")).strip().lower()
        if not task:
            return ""
        agent_type = str(args.get("agent_type", "code_explorer") or "code_explorer").strip().lower()
        command = re.sub(r"\s+", " ", str(args.get("command", "") or "")).strip().lower()
        return f"{agent_type}:{task}:{command}"

    @staticmethod
    def _tool_call_name(call: Any) -> str:
        if hasattr(call, "function") and hasattr(call.function, "name"):
            return str(call.function.name or "")
        if isinstance(call, dict):
            function = call.get("function", {})
            if isinstance(function, dict):
                return str(function.get("name") or "")
            return str(call.get("name") or "")
        return ""

    @staticmethod
    def _tool_call_id(call: Any) -> str:
        if hasattr(call, "id"):
            return str(getattr(call, "id", "") or "")
        if isinstance(call, dict):
            return str(call.get("id") or call.get("call_id") or "")
        return ""

    def _tool_call_args(self, call: Any) -> Dict:
        raw_args: Any = {}
        if hasattr(call, "function"):
            raw_args = getattr(call.function, "arguments", {})
        elif isinstance(call, dict):
            function = call.get("function", {})
            raw_args = function.get("arguments", {}) if isinstance(function, dict) else call.get("args", {})
        return self._parse_tool_arguments(raw_args)

    @staticmethod
    def _parse_tool_arguments(raw_args: Any) -> Dict:
        if isinstance(raw_args, dict):
            return dict(raw_args)
        if isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed = json.loads(raw_args)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _estimate_prompt_tokens(self, messages: List[Dict], tools: List[Dict]) -> int:
        """Rough local estimate used only to avoid one more doomed call."""
        try:
            char_count = len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(tools or [], ensure_ascii=False))
        except Exception:
            char_count = sum(len(str(msg.get("content", ""))) for msg in messages) + len(str(tools or []))
        return max(1, int(char_count / 4))

    def _prepare_model_call(
        self,
        messages: List[Dict],
        initial_message: str,
        executed_tools: List[Dict],
        force_final: bool = False,
        autonomous: bool = False,
    ) -> tuple[List[Dict], List[Dict], int, Dict[str, int]]:
        """Apply JoyBoy's pre-model middleware chain in one readable place."""
        tool_names_for_turn = self._select_tool_names_for_turn(
            initial_message,
            executed_tools=executed_tools,
            autonomous=autonomous,
        )
        tools_for_model = [] if force_final else self.tool_registry.ollama_tools(tool_names_for_turn)
        prepared = self._compact_loop_messages(messages, context_size=self._active_context_size)
        prepared = self._inject_execution_journal(prepared)
        prepared = self._inject_todo_reminder(prepared, executed_tools=executed_tools)
        prepared = self._inject_step_focus_reminder(prepared, initial_message, executed_tools)
        prepared = self._patch_dangling_tool_messages(prepared)
        prompt_estimate = self._estimate_prompt_tokens(prepared, tools_for_model)
        return prepared, tools_for_model, prompt_estimate, self._tool_schema_stats(tools_for_model)

    def _tool_schema_stats(self, tools: List[Dict]) -> Dict[str, int]:
        """Small TokenUsageMiddleware-style telemetry for active tool schemas."""
        try:
            schema_chars = len(json.dumps(tools or [], ensure_ascii=False))
        except Exception:
            schema_chars = len(str(tools or []))
        return {
            "tool_count": len(tools or []),
            "tool_schema_tokens": max(0, int(schema_chars / 4)),
        }

    def _tool_call_batch_signature(self, tool_calls: Any) -> str:
        """Order-independent signature for a model response's tool-call batch."""
        signatures: List[str] = []
        for call in tool_calls or []:
            name = self._tool_call_name(call)
            if not name:
                continue
            args = self._tool_call_args(call)
            signatures.append(tool_signature(name, args))
        if not signatures:
            return ""
        return "|".join(sorted(signatures))
