"""System prompt and LLM-facing tool result formatting."""

from __future__ import annotations

from collections import defaultdict
import json
import os
import platform
from typing import Dict, List, Optional

from core.agent_runtime import mask_workspace_paths, truncate_middle
from core.backends.terminal_tool_schemas import DEFERRED_PROMPT_MAX_MCP_NAMES


class TerminalPromptingMixin:
    """Prompt construction and result projection for model calls."""

    def build_system_prompt(
        self,
        workspace_path: str,
        workspace_name: Optional[str] = None,
        force_response_language: Optional[str] = None,
    ) -> str:
        """Build the terminal agent prompt in English.

        Local coding models are usually more reliable when the operational
        contract is written in English, even when the final answer is in the
        user's language. Keep UI translations elsewhere; this prompt is for the
        tool-using model.
        """
        project_name = workspace_name or os.path.basename(os.path.abspath(workspace_path or "")) or "workspace"
        language_rule = (
            f"Final answer language: {force_response_language}.\n"
            if force_response_language
            else "Final answer language: match the user's language.\n"
        )
        skill_index = self._build_skill_index_prompt()
        deferred_tools = self._build_deferred_tools_prompt()
        host_os = platform.system() or os.name
        return f"""You are JoyBoy Terminal, an expert coding agent working inside a local project folder.

Workspace name: {project_name}
Workspace path visible to you: /workspace
Host workspace path: hidden by JoyBoy runtime; do not mention local absolute paths unless the user asks.
Host OS: {host_os}. The bash tool runs through the host default shell in the workspace; on Windows, use PowerShell/cmd-compatible commands unless a POSIX tool is confirmed available.
{language_rule}
Core contract:
1. Use tools for real work. Do not pretend that files were created, edited, installed, or tested.
2. Always call read_file before editing or replacing an existing file.
3. Prefer edit_file for targeted changes. Use write_files for scaffolds or multi-file creation. Use write_file only for a single new file or intentional full rewrite.
4. Never call read_file on "." or on a directory. read_file is only for specific files.
5. Do one meaningful step at a time, then verify the result before claiming success.
6. Do not loop on list_files, glob, ls, dir, or pwd. One root exploration is enough; then read specific files.
7. If a shell scaffold command succeeds, verify the expected folder and package.json before saying it exists.
8. If a command or edit fails, inspect the error, adjust once or twice, then explain the blocker.
9. Keep context lean: read focused file chunks, summarize large outputs, and avoid dumping entire files.
10. For final code snippets, use fenced Markdown blocks with a language tag. If the snippet itself contains fenced blocks, wrap the outer block with a longer fence such as ````markdown so nested ```bash blocks stay literal.
11. For broad codebase tasks, prefer one focused code_explorer delegation only when the user explicitly asks for agentic/parallel analysis; otherwise read/search directly.
12. For web research, use web_search first, then web_fetch exact public URLs returned by search or provided by the user.
13. After modifications, verify directly with read_file/list_files or one focused bash test/build command. Do not delegate verification unless the user explicitly asks for subagents or long parallel analysis.
14. Some rare tools are deferred to save tokens. If a needed deferred tool is listed by name only, call tool_search once to fetch its schema, then call that tool. Do not use tool_search for core tools like write_files, write_file, edit_file, read_file, list_files, bash, search, or glob.
15. For complex multi-step tasks, call write_todos early with 2-6 concrete items, keep exactly one item in_progress, and update it as you work. Provide both content (imperative) and activeForm (present continuous) when useful. Do not use write_todos for simple scaffolds or small direct edits.
16. Use remember_fact only for explicit durable user/project preferences. Never store secrets, API keys, tokens, private URLs, or one-off transient details.
17. Use list_memory when the user asks about remembered context or when memory is clearly relevant.
18. Never expose raw tool protocol traces such as to=read_file, JSON payloads, internal call logs, or ledger lines like "write_files: 9 file(s)" in the final answer. Summarize the work in natural language instead.
19. Final answers should not replay tool names as proof. Say "fichiers créés/modifiés", "commande lancée", or "fichier lu" with concrete paths/results.
20. Prefer high-signal answers over reports. Unless the user asks for exhaustive detail, keep final answers compact: lead with the verdict, include only concrete observed evidence, and stop after the next useful step.
21. For codebase analysis, do not produce generic boilerplate. Read related files together (for example JSX plus CSS, API route plus tests, config plus docs), then mention only issues grounded in those files.
22. If required information is missing, a requirement has multiple valid meanings, or the next step is risky, call ask_clarification with one specific question instead of guessing. Keep options to 2-3 choices and put the recommended option first.
23. On Windows/PowerShell, do not enumerate paths in one shell and pipe them into cmd.exe, powershell.exe, or another shell for deletion, moving, or copying. Use one shell end-to-end with explicit paths, and prefer JoyBoy file tools for file mutations.
24. Never write shell output or generated files directly into .git, HEAD, objects, or refs paths. Use git commands for git metadata and normal file tools for workspace files.

Fast repo reading:
1. Use git ls-files or rg --files through bash when available for broad repo maps; fall back to list_files/glob when shell tools are unavailable.
2. Use search/glob before reading when you need symbols, routes, CSS classes, tests, or references. Then call read_file with start_line near the match instead of rereading from line 1.
3. Read manifests/instructions first only when they affect the task, then read the smallest set of files that proves or disproves the likely issue.
4. Cross-check paired surfaces before judging quality: component and stylesheet, route and client call, implementation and test.

Safe workflow for analysis:
1. list_files once if needed.
2. read 2 to 6 relevant files, including paired files when the task is about UI or behavior.
3. answer with concrete findings from observed files.
4. For a quick repo audit, use three short sections at most: what it is, concrete issues, next step.

Safe workflow for modifications:
1. read_file the target file.
2. edit_file or write_file.
3. verify with read_file, list_files, or command output.
4. only then summarize what changed.

Safe workflow for project scaffolding:
1. Prefer write_files for small templates and starter projects so the whole scaffold is one tool step.
2. If the user asks to delete/replace the whole workspace and full access is enabled, call clear_workspace once before write_files.
3. If the user asked to replace everything, do not spend turns auditing old files unless they asked to preserve or migrate them.
4. Use a scaffold command only when the user asks for a framework generator or the project is too large for a small batch.
5. write_files verifies every file server-side; for simple scaffolds, finish after that unless the user explicitly asked to run tests/build.
{skill_index}
{deferred_tools}

You have access to filesystem, search, shell, and workspace tools. Use them to complete the user's task."""

    def _get_default_system_prompt(self, workspace_path: str) -> str:
        """Default Claude-Code-style terminal system prompt."""
        return self.build_system_prompt(workspace_path)

    def _build_skill_index_prompt(self) -> str:
        try:
            from core.infra.packs import get_pack_skills

            skills = get_pack_skills()
        except Exception:
            skills = []

        if not skills:
            return ""

        lines = [
            "",
            "Local pack skills:",
            "- Use load_skill only when a listed skill clearly matches the task.",
            "- Do not load every skill preemptively; keep context lean.",
        ]
        for skill in skills[:20]:
            summary = f" - {skill.get('summary', '')}" if skill.get("summary") else ""
            lines.append(f"- {skill.get('id')}: {skill.get('name', 'Skill')}{summary}")
        if len(skills) > 20:
            lines.append(f"- ... {len(skills) - 20} more skill(s) hidden from the base prompt.")
        return "\n".join(lines)

    def _build_deferred_tools_prompt(self) -> str:
        remaining = [
            name
            for name in self._ordered_deferred_tool_names
            if name in self._active_deferred_tool_names
            and name not in self._active_promoted_tool_names
            and self.tool_registry.get(name)
        ]
        if not remaining:
            return ""

        core_deferred: List[str] = []
        mcp_by_server: Dict[str, List[str]] = defaultdict(list)
        for name in remaining:
            tool = self.tool_registry.get(name)
            tags = set(tool.tags or []) if tool else set()
            if "mcp" in tags:
                server_name = next((tag for tag in (tool.tags or []) if tag != "mcp"), "external")
                mcp_by_server[str(server_name or "external")].append(name)
            else:
                core_deferred.append(name)

        lines = [
            "",
            "Available deferred tools:",
            "- Their full schemas are hidden from the base prompt to reduce token use.",
            "- Call tool_search with select:<tool_name> or keywords only when one is actually needed.",
            "- Core file tools are already active when the task needs them; never fetch write_files/write_file/edit_file/bash through tool_search.",
        ]
        for name in core_deferred:
            tool = self.tool_registry.get(name)
            lines.append(f"- {name}: {tool.description if tool else ''}")
        if mcp_by_server:
            lines.append("- MCP tools are grouped by server below. Search them by server, name, tag, or intent; schemas are only returned by tool_search.")
            shown_mcp = 0
            total_mcp = sum(len(names) for names in mcp_by_server.values())
            for server_name in sorted(mcp_by_server):
                names = mcp_by_server[server_name]
                available_slots = max(0, DEFERRED_PROMPT_MAX_MCP_NAMES - shown_mcp)
                if available_slots <= 0:
                    break
                visible_names = names[:available_slots]
                shown_mcp += len(visible_names)
                hidden = len(names) - len(visible_names)
                suffix = f" (+{hidden} more)" if hidden > 0 else ""
                lines.append(f"- mcp:{server_name}: {', '.join(visible_names)}{suffix}")
            if shown_mcp < total_mcp:
                lines.append(
                    f"- {total_mcp - shown_mcp} additional MCP tool(s) hidden from the prompt; use tool_search with keywords to discover them."
                )
        return "\n".join(lines)

    def _format_result_for_llm(self, result: ToolResult) -> str:
        """Formate le résultat d'un tool pour le LLM"""
        if not result.success:
            if result.tool_name == 'delegate_subagent' and result.data:
                return self._format_delegate_subagent_for_llm(result.data)
            if result.tool_name == 'bash' and result.data:
                data = result.data
                output = data.get('output', '')
                verification = data.get('verification')
                if verification:
                    output += (
                        f"\n[VERIFICATION]\n"
                        f"{verification.get('kind', 'artifact')}: FAILED - "
                        f"{verification.get('path', '')}"
                    )
                    if verification.get('package_json') is not None:
                        output += f" (package.json: {'yes' if verification.get('package_json') else 'no'})"
                output = truncate_middle(output, max(3000, min(8000, int(self._active_context_size * 1.35))))
                output = mask_workspace_paths(output, self._active_workspace_path)
                return f"[ERROR bash] {result.error or 'Command failed'}\n```\n{output}\n```"
            return f"[ERROR {result.tool_name}] {result.error}"

        data = result.data

        if result.tool_name == 'list_files':
            items = data.get('items', [])
            listing = '\n'.join([
                f"{'[DIR]' if i.get('type') == 'dir' else '[FILE]'} {i.get('name')}"
                for i in items[:50]
            ])
            return f"[RESULT list_files]\n{listing}"

        elif result.tool_name == 'read_file':
            content = data.get('content', '')
            lines = data.get('lines', 0)
            start_line = data.get('start_line', 1)
            end_line = data.get('end_line', 0)
            range_text = f", lines {start_line}-{end_line}" if end_line else ""
            if data.get("already_read"):
                return f"[RESULT read_file] Already read unchanged content ({lines} total lines{range_text}): {data.get('path', '')}"
            # Tronquer si trop long
            max_chars = max(2500, min(6500, int(self._active_context_size * 1.2)))
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... (truncated to preserve context)"
            return f"[RESULT read_file] ({lines} total lines{range_text})\n```\n{content}\n```"

        elif result.tool_name == 'write_file':
            verified = " verified" if data.get('verified') else ""
            size = f", {data.get('size')} bytes" if data.get('size') is not None else ""
            return f"[RESULT write_file] OK{verified} - File {'created' if data.get('created') else 'modified'}: {data.get('path', '')}{size}"

        elif result.tool_name == 'edit_file':
            verified = " verified" if data.get('verified') else ""
            size = f", {data.get('size')} bytes" if data.get('size') is not None else ""
            line_range = data.get("line_range") if isinstance(data.get("line_range"), dict) else {}
            line_text = ""
            if line_range.get("start_line") and line_range.get("end_line"):
                line_text = f" lines {line_range.get('start_line')}-{line_range.get('end_line')}"
            changed = ""
            if data.get("lines_added") is not None or data.get("lines_removed") is not None:
                changed = f", +{int(data.get('lines_added') or 0)}/-{int(data.get('lines_removed') or 0)}"
            return (
                f"[RESULT edit_file] OK{verified} - {data.get('replacements', 0)} "
                f"replacement(s): {data.get('path', '')}{line_text}{changed}{size}"
            )

        elif result.tool_name == 'delete_file':
            verified = " verified" if data.get('verified') else ""
            return f"[RESULT delete_file] OK{verified} - Deleted: {data.get('path', '')}"

        elif result.tool_name == 'clear_workspace':
            deleted = data.get("deleted", []) if isinstance(data, dict) else []
            kept = data.get("kept", []) if isinstance(data, dict) else []
            deleted_preview = ", ".join(deleted[:12])
            if len(deleted) > 12:
                deleted_preview += f", +{len(deleted) - 12} more"
            kept_preview = ", ".join(kept) if kept else "nothing"
            return (
                f"[RESULT clear_workspace] OK - Deleted {len(deleted)} top-level item(s)"
                f"{f': {deleted_preview}' if deleted_preview else ''}. Kept: {kept_preview}"
            )

        elif result.tool_name == 'search':
            results = data.get('results', [])
            matches = '\n'.join([
                f"{r.get('file')}:{r.get('line')}: {r.get('content', '')[:80]}"
                for r in results[:20]
            ])
            return f"[RESULT search]\n{matches or 'No results'}"

        elif result.tool_name == 'glob':
            files = data.get('files', [])
            return f"[RESULT glob]\n" + '\n'.join(files[:30])

        elif result.tool_name == 'bash':
            output = data.get('output', '')
            code = data.get('return_code', -1)
            status = 'OK' if code == 0 else 'ERROR'
            verification = data.get('verification')
            if verification:
                verified_label = "OK" if verification.get('verified') else "FAILED"
                output += (
                    f"\n[VERIFICATION]\n"
                    f"{verification.get('kind', 'artifact')}: {verified_label} - "
                    f"{verification.get('path', '')}"
                )
                if verification.get('package_json') is not None:
                    output += f" (package.json: {'yes' if verification.get('package_json') else 'no'})"
            output = truncate_middle(output, max(3000, min(8000, int(self._active_context_size * 1.35))))
            output = mask_workspace_paths(output, self._active_workspace_path)
            return f"[RESULT bash] {status} (code: {code})\n```\n{output}\n```"

        elif result.tool_name == 'write_todos':
            todos = data.get("todos", []) if isinstance(data, dict) else []
            if not todos:
                return "[RESULT write_todos] Todo list cleared"
            lines = [
                f"- [{item.get('status', 'pending')}] {item.get('content', '')}"
                + (f" (active: {item.get('activeForm')})" if item.get("activeForm") else "")
                + (f" - {item.get('note')}" if item.get("note") else "")
                for item in todos
            ]
            return "[RESULT write_todos]\n" + "\n".join(lines)

        elif result.tool_name == 'ask_clarification':
            question = data.get("question", "") if isinstance(data, dict) else ""
            return f"[RESULT ask_clarification] Waiting for user clarification: {question}"

        elif result.tool_name == 'write_files':
            files = data.get("files", []) if isinstance(data, dict) else []
            if not files:
                conflicts = data.get("conflicts", []) if isinstance(data, dict) else []
                if conflicts:
                    return "[RESULT write_files] Existing files blocked:\n" + "\n".join(f"- {path}" for path in conflicts)
                return f"[RESULT write_files] {'OK' if result.success else 'failed'}"
            lines = [
                f"- {item.get('action', 'written')}: {item.get('path', '')} ({item.get('bytes', 0)} bytes)"
                for item in files
            ]
            return "[RESULT write_files]\n" + "\n".join(lines)

        elif result.tool_name == 'tool_search':
            promoted = data.get("promoted", []) if isinstance(data, dict) else []
            already_available = data.get("already_available", []) if isinstance(data, dict) else []
            blocked_by_intent = data.get("blocked_by_intent", []) if isinstance(data, dict) else []
            tools = data.get("tools", []) if isinstance(data, dict) else []
            if not promoted and not already_available and not blocked_by_intent:
                return f"[RESULT tool_search] No deferred tools matched: {data.get('query', '') if isinstance(data, dict) else ''}"
            lines: List[str] = []
            if promoted:
                schemas = json.dumps(tools, ensure_ascii=False, indent=2)
                lines.append(f"Promoted deferred tools: {', '.join(promoted)}")
                lines.append("These tool schemas are now available for the next call:")
                lines.append(f"```json\n{schemas}\n```")
            if already_available:
                lines.append(
                    "Core tools already available in this turn; call them directly, do not fetch them through tool_search: "
                    + ", ".join(already_available)
                )
            if blocked_by_intent:
                lines.append(
                    "Core write tools were requested but this turn is read-only. The user must ask for a modification before using: "
                    + ", ".join(blocked_by_intent)
                )
            return "[RESULT tool_search]\n" + "\n".join(lines)

        elif result.tool_name == 'web_search':
            items = data.get('results', [])
            if not items:
                return "[RESULT web_search] No results"
            results_text = '\n'.join([
                f"{i+1}. {item.get('title', 'Untitled')}\n   {item.get('url', '')}\n   {item.get('snippet', '')[:150]}"
                for i, item in enumerate(items[:5])
            ])
            return f"[RESULT web_search]\n{results_text}"

        elif result.tool_name == 'web_fetch':
            title = data.get("title", "Untitled")
            url = data.get("url", "")
            content = truncate_middle(data.get("content", ""), max(3000, min(9000, int(self._active_context_size * 1.5))))
            return f"[RESULT web_fetch] {title}\nURL: {url}\n````markdown\n{content}\n````"

        elif result.tool_name == 'delegate_subagent':
            return self._format_delegate_subagent_for_llm(data)

        elif result.tool_name == 'load_skill':
            skill = data.get("skill", {}) if isinstance(data, dict) else {}
            content = data.get("content", "") if isinstance(data, dict) else ""
            content = truncate_middle(content, max(3500, min(9000, int(self._active_context_size * 1.5))))
            suffix = "\n... (skill truncated)" if data.get("truncated") else ""
            return f"[RESULT load_skill] {skill.get('id', '')} - {skill.get('name', 'Skill')}\n````markdown\n{content}{suffix}\n````"

        elif result.tool_name == 'remember_fact':
            fact = data.get("fact", {}) if isinstance(data, dict) else {}
            return (
                "[RESULT remember_fact] Saved local memory fact "
                f"{fact.get('id', '')}: {fact.get('content', '')}"
            )

        elif result.tool_name == 'list_memory':
            facts = data.get("facts", []) if isinstance(data, dict) else []
            if not facts:
                return "[RESULT list_memory] No local memory facts matched"
            lines = [
                f"- {fact.get('id', '')} [{fact.get('category', 'context')}, confidence={fact.get('confidence', '?')}]: {fact.get('content', '')}"
                for fact in facts[:10]
            ]
            return "[RESULT list_memory]\n" + "\n".join(lines)

        elif result.tool_name == 'think':
            return f"[THOUGHT] {data.get('thought', '')} - Continue with the appropriate concrete action."

        elif result.tool_name == 'open_workspace':
            return f"[RESULT open_workspace] Folder opened: {data.get('path', '')}"

        elif result.tool_name in self._mcp_tools_by_name:
            server_name = data.get("server_name", "")
            raw_payload = data.get("result")
            if isinstance(raw_payload, str):
                content = raw_payload
                fence = ""
            else:
                try:
                    content = json.dumps(raw_payload, ensure_ascii=False, indent=2, default=str)
                except Exception:
                    content = str(raw_payload)
                fence = "json"
            content = truncate_middle(mask_workspace_paths(content, self._active_workspace_path), max(3000, min(9000, int(self._active_context_size * 1.5))))
            server_suffix = f" via {server_name}" if server_name else ""
            if fence:
                return f"[RESULT {result.tool_name}]{server_suffix}\n```{fence}\n{content}\n```"
            return f"[RESULT {result.tool_name}]{server_suffix}\n```\n{content}\n```"

        return f"[RESULT {result.tool_name}] OK"

    def _format_delegate_subagent_for_llm(self, data: Dict) -> str:
        observations = data.get("observations", []) if isinstance(data, dict) else []
        files = data.get("files", []) if isinstance(data, dict) else []
        commands = data.get("commands", []) if isinstance(data, dict) else []
        warnings = data.get("warnings", []) if isinstance(data, dict) else []
        lines = [
            f"[RESULT delegate_subagent] {data.get('agent_type', 'subagent')} {data.get('status', '')}",
            f"Task id: {data.get('task_id', '')}",
            f"Summary: {data.get('summary', '')}",
        ]
        if observations:
            lines.append("Observations:")
            lines.extend(f"- {item}" for item in observations[:8])
        if commands:
            lines.append("Commands:")
            for item in commands[:4]:
                lines.append(f"- {item.get('command', '')} (code: {item.get('return_code', 'n/a')})")
                output = item.get("output", "")
                if output:
                    lines.append("```")
                    lines.append(truncate_middle(output, 5000))
                    lines.append("```")
                if item.get("error"):
                    lines.append(f"  error: {item.get('error')}")
        if warnings:
            lines.append("Warnings:")
            lines.extend(f"- {item}" for item in warnings[:5])
        if files:
            lines.append("Relevant files:")
            for item in files[:8]:
                excerpt = item.get("excerpt", "")
                if excerpt:
                    excerpt = truncate_middle(excerpt, 1800)
                    lines.append(f"\n--- {item.get('path', '')} ({item.get('lines', '?')} lines) ---\n{excerpt}")
                else:
                    lines.append(f"- {item.get('path', '')}: {item.get('error', 'unreadable')}")
        return "\n".join(lines)

