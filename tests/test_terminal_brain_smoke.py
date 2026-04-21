import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.backends.terminal_brain import TerminalBrain, ToolResult
from core.agent_runtime import CloudModelError, McpToolAdapter


class TerminalBrainSmokeTests(unittest.TestCase):
    def test_system_prompt_uses_english_operational_guardrails(self):
        brain = TerminalBrain()

        prompt = brain.build_system_prompt("C:/projects/demo", workspace_name="demo")

        self.assertIn("You are JoyBoy Terminal", prompt)
        self.assertIn("Always call read_file", prompt)
        self.assertIn("Do not pretend that files were created", prompt)
        self.assertIn("Workspace path visible to you: /workspace", prompt)
        self.assertIn("prefer delegate_subagent(code_explorer)", prompt)
        self.assertIn("use web_search first, then web_fetch", prompt)
        self.assertIn("delegate_subagent(verifier)", prompt)
        self.assertNotIn("C:/projects/demo", prompt)
        self.assertNotIn("TOUJOURS", prompt)
        self.assertNotIn("RÈGLES", prompt)

    def test_tool_result_messages_are_english_for_llm_loop(self):
        brain = TerminalBrain()
        result = ToolResult(
            success=True,
            tool_name="write_file",
            data={"path": "src/App.tsx", "created": True, "verified": True, "size": 42},
        )

        text = brain._format_result_for_llm(result)

        self.assertIn("[RESULT write_file]", text)
        self.assertIn("File created", text)
        self.assertIn("verified", text)
        self.assertNotIn("Fichier", text)

    def test_guard_reason_is_english_and_blocks_root_read(self):
        brain = TerminalBrain()

        reason = brain._tool_guard_reason("read_file", {"path": "."}, 1, [])

        self.assertEqual(reason, "read_file must target a file, not the workspace root")

    def test_vague_analysis_uses_bounded_repo_overview(self):
        brain = TerminalBrain()

        self.assertTrue(brain._is_repo_overview_request("Analyse le"))
        self.assertTrue(brain._is_repo_overview_request("analyse ça"))
        self.assertTrue(brain._is_repo_overview_request("analyse le projet"))
        self.assertFalse(brain._is_repo_overview_request("analyse core/backends/terminal_brain.py"))

    def test_budget_fallback_ends_without_another_model_call(self):
        brain = TerminalBrain()
        observed = [
            {
                "tool": "list_files",
                "args": {"path": "."},
                "success": True,
                "summary": "0 item(s)",
            }
        ]

        text = brain._budget_fallback_answer("analyse le", observed)

        self.assertIn("coupé avant de relancer", text)
        self.assertIn("list_files", text)

    def test_cloud_error_classification_separates_quota_auth_and_transient(self):
        brain = TerminalBrain()

        self.assertEqual(
            brain._classify_cloud_model_error(CloudModelError("OpenAI API error 429: insufficient_quota")),
            (False, "quota"),
        )
        self.assertEqual(
            brain._classify_cloud_model_error(CloudModelError("OpenAI API error 401: invalid api key")),
            (False, "auth"),
        )
        self.assertEqual(
            brain._classify_cloud_model_error(CloudModelError("OpenAI API error 503: service unavailable")),
            (True, "transient"),
        )

    @patch("core.backends.terminal_brain.time.sleep", return_value=None)
    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_cloud_terminal_retries_transient_failure_once(self, mock_chat, _sleep):
        mock_chat.side_effect = [
            CloudModelError("OpenAI API error 503: service unavailable"),
            {
                "message": {"role": "assistant", "content": "ok cloud"},
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        ]
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            events = list(brain.run_agentic_loop("dis bonjour", tmp, model="openai:gpt-5.4"))

        warnings = [event for event in events if event.get("type") == "warning"]
        done = [event for event in events if event.get("type") == "done"][-1]

        self.assertTrue(any("Cloud model retry 1/3" in event.get("message", "") for event in warnings))
        self.assertEqual(done.get("full_response"), "ok cloud")
        self.assertEqual(mock_chat.call_count, 2)

    def test_cloud_circuit_breaker_opens_after_repeated_transient_failures(self):
        brain = TerminalBrain()

        brain._record_cloud_circuit_failure("openai:gpt-5.4")
        brain._record_cloud_circuit_failure("openai:gpt-5.4")
        self.assertIsNone(brain._cloud_circuit_block_reason("openai:gpt-5.4"))

        brain._record_cloud_circuit_failure("openai:gpt-5.4")
        reason = brain._cloud_circuit_block_reason("openai:gpt-5.4")

        self.assertIn("Cloud circuit breaker active for openai", reason)
        brain._record_cloud_circuit_success("openai:gpt-5.4")
        self.assertIsNone(brain._cloud_circuit_block_reason("openai:gpt-5.4"))

    def test_dangling_tool_calls_are_patched_before_cloud_model_call(self):
        brain = TerminalBrain()
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_missing",
                        "type": "function",
                        "function": {"name": "glob", "arguments": '{"pattern":"**/*"}'},
                    },
                    {
                        "id": "call_done",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"pattern":"react"}'},
                    },
                ],
            },
            {"role": "tool", "tool_name": "search", "tool_call_id": "call_done", "content": "[RESULT search] 0"},
        ]

        patched = brain._patch_dangling_tool_messages(messages)
        patched_tool_ids = [
            item.get("tool_call_id")
            for item in patched
            if item.get("role") == "tool"
        ]

        self.assertIn("call_missing", patched_tool_ids)
        self.assertIn("call_done", patched_tool_ids)

    def test_orphan_tool_message_is_converted_before_cloud_model_call(self):
        brain = TerminalBrain()
        messages = [
            {"role": "system", "content": "system"},
            {"role": "tool", "tool_name": "glob", "tool_call_id": "call_stale", "content": "old"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_stale",
                        "type": "function",
                        "function": {"name": "glob", "arguments": '{"pattern":"**/*"}'},
                    },
                ],
            },
        ]

        patched = brain._patch_dangling_tool_messages(messages)
        patched_tool_ids = [
            item.get("tool_call_id")
            for item in patched
            if item.get("role") == "tool"
        ]
        compacted_tool_results = [
            item.get("content", "")
            for item in patched
            if item.get("role") == "user" and "[COMPACTED TOOL RESULT]" in item.get("content", "")
        ]

        self.assertEqual(patched_tool_ids.count("call_stale"), 1)
        self.assertEqual(len(compacted_tool_results), 1)

    def test_terminal_brain_full_access_allows_delete_file_tool(self):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "notes.txt"
            target.write_text("delete me\n", encoding="utf-8")
            brain.current_intent = "write"

            blocked = brain.execute_tool("delete_file", {"path": "notes.txt"}, tmp)
            self.assertFalse(blocked.success)
            self.assertIn("full access", blocked.error)

            brain.permission_mode = "full_access"
            deleted = brain.execute_tool("delete_file", {"path": "notes.txt"}, tmp)

            self.assertTrue(deleted.success)
            self.assertFalse(target.exists())

    def test_casual_greeting_fast_path_avoids_agentic_tool_loop(self):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            events = list(brain.run_agentic_loop("yo mec", tmp, model="qwen3.5:2b"))

        self.assertFalse(any(event.get("type") == "thinking" for event in events))
        self.assertFalse(any(event.get("type") == "tool_call" for event in events))
        done = [event for event in events if event.get("type") == "done"][-1]
        self.assertEqual(done.get("token_stats", {}).get("total"), 0)
        self.assertIn("Je suis là", done.get("full_response", ""))

    def test_casual_greeting_detection_does_not_capture_real_work(self):
        brain = TerminalBrain()

        self.assertTrue(brain._is_casual_greeting_request("yO MEC"))
        self.assertTrue(brain._is_casual_greeting_request("Yo j'ai dis"))
        self.assertFalse(brain._is_casual_greeting_request("yo analyse le projet"))
        self.assertFalse(brain._is_casual_greeting_request("salut corrige ce fichier"))

    def test_loop_message_compaction_omits_large_write_arguments(self):
        brain = TerminalBrain()
        huge_content = "A" * 5000
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": {"path": "package.json", "content": huge_content},
                        },
                    }
                ],
            },
            {"role": "tool", "tool_name": "write_file", "content": "[RESULT write_file] OK"},
        ]

        compacted = brain._compact_loop_messages(messages, context_size=4096)
        serialized = str(compacted)

        self.assertNotIn("A" * 1000, serialized)
        self.assertIn("omitted 5000 chars", serialized)

    def test_compaction_summary_collects_useful_tool_and_request_points(self):
        brain = TerminalBrain()
        messages = [
            {
                "role": "user",
                "content": (
                    "[COMPACTED LOOP SUMMARY]\n"
                    "Earlier context compacted: 2 message(s) folded into this summary.\n"
                    "Key preserved context:\n"
                    "- user asked: fix the terminal runtime\n"
                    "- tool read_file: terminal_brain.py (220 lines)\n"
                ),
            },
            {"role": "user", "content": "continue"},
            {"role": "tool", "tool_name": "write_file", "content": "[RESULT write_file]\nFile created: src/App.jsx"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"type": "function", "function": {"name": "read_file", "arguments": {"path": "README.md"}}},
                    {"type": "function", "function": {"name": "edit_file", "arguments": {"path": "README.md"}}},
                ],
            },
        ]

        lines = brain._collect_compaction_summary_lines(messages)

        self.assertIn("user asked: fix the terminal runtime", lines)
        self.assertIn("tool read_file: terminal_brain.py (220 lines)", lines)
        self.assertIn("tool write_file: File created: src/App.jsx", lines)
        self.assertIn("assistant used tools: read_file, edit_file", lines)
        self.assertFalse(any(line.endswith("continue") for line in lines))

    def test_loop_compaction_rolls_prior_summary_forward(self):
        brain = TerminalBrain()
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": (
                    "[COMPACTED LOOP SUMMARY]\n"
                    "Earlier context compacted: 3 message(s) folded into this summary.\n"
                    "Key preserved context:\n"
                    "- user asked: build a React scaffold\n"
                ),
            },
            {"role": "user", "content": "B" * 5000},
            {"role": "assistant", "content": "C" * 2500},
            {"role": "tool", "tool_name": "read_file", "content": "[RESULT read_file]\npackage.json (120 lines)\n" + ("D" * 5000)},
            {"role": "assistant", "content": "Z" * 2500},
        ]

        compacted = brain._compact_loop_messages(messages, context_size=2048)
        summary_messages = [
            msg for msg in compacted
            if msg.get("role") == "user" and msg.get("content", "").startswith("[COMPACTED LOOP SUMMARY]")
        ]

        self.assertEqual(len(summary_messages), 1)
        summary_content = summary_messages[0]["content"]
        self.assertIn("user asked: build a React scaffold", summary_content)
        self.assertIn("assistant noted:", summary_content)
        self.assertEqual(summary_content.count("[COMPACTED LOOP SUMMARY]"), 1)

    def test_history_compaction_preserves_summary_points(self):
        brain = TerminalBrain()
        history = [
            {"role": "user", "content": "Analyse DeerFlow et améliore JoyBoy pour les longues boucles."},
            {"role": "assistant", "content": "Je vais comparer les middlewares de summarization et loop detection."},
            {"role": "user", "content": "E" * 3200},
            {"role": "assistant", "content": "F" * 2200},
            {"role": "user", "content": "G" * 3200},
            {"role": "assistant", "content": "H" * 2200},
            {"role": "user", "content": "continue"},
            {"role": "assistant", "content": "ok"},
        ]

        compacted = brain._compact_history(history, context_size=2048)

        self.assertTrue(compacted[0]["content"].startswith("[COMPACTED HISTORY SUMMARY]"))
        self.assertIn("Analyse DeerFlow", compacted[0]["content"])
        self.assertIn("assistant noted:", compacted[0]["content"])

    def test_tool_selection_omits_network_tools_for_plain_write(self):
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain._reset_deferred_tools()

        names = brain._select_tool_names_for_turn("crée un composant", [], autonomous=False)

        self.assertIn("write_file", names)
        self.assertIn("bash", names)
        self.assertNotIn("tool_search", names)
        self.assertNotIn("web_search", names)
        self.assertNotIn("load_skill", names)

    def test_template_request_is_write_and_prioritizes_batch_write(self):
        brain = TerminalBrain()
        message = "je veux un TEMPLATE COMPLET"
        brain.current_intent = brain.detect_intent(message)
        brain._reset_deferred_tools()

        names = brain._select_tool_names_for_turn(message, [], autonomous=False)

        self.assertEqual(brain.current_intent, "write")
        self.assertIn("write_files", names)
        self.assertLess(names.index("write_files"), names.index("write_file"))
        self.assertNotIn("write_todos", names)
        self.assertNotIn("tool_search", names)

    def test_template_analysis_remains_read_only(self):
        brain = TerminalBrain()

        self.assertEqual(brain.detect_intent("analyse le template Next.js"), "read")

    def test_deferred_tool_search_promotes_matching_tools(self):
        brain = TerminalBrain()
        brain._reset_deferred_tools()

        result = brain.execute_tool("tool_search", {"query": "web"}, os.getcwd())

        self.assertTrue(result.success)
        self.assertIn("web_search", result.data.get("promoted", []))
        self.assertIn("web_fetch", result.data.get("promoted", []))
        self.assertIn("web_search", brain._active_promoted_tool_names)
        formatted = brain._format_result_for_llm(result)
        self.assertIn("[RESULT tool_search]", formatted)
        self.assertIn('"name": "web_search"', formatted)

    def test_tool_search_reports_core_tools_without_hiding_them(self):
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain._reset_deferred_tools()

        result = brain.execute_tool(
            "tool_search",
            {"query": "select:write_files,write_file,edit_file"},
            os.getcwd(),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.data.get("promoted"), [])
        self.assertEqual(result.data.get("already_available"), ["write_files", "write_file", "edit_file"])
        formatted = brain._format_result_for_llm(result)
        self.assertIn("Core tools already available", formatted)

    def test_write_files_counts_as_verified_mutation(self):
        brain = TerminalBrain()

        self.assertTrue(
            brain._has_successful_mutation([
                {"tool": "write_files", "success": True, "summary": "2 files"},
            ])
        )

    def test_write_task_keeps_tools_after_passive_guard(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        self.assertTrue(brain._should_continue_write_after_guard("glob", []))
        self.assertFalse(
            brain._should_continue_write_after_guard(
                "glob",
                [{"tool": "write_files", "success": False}],
            )
        )
        self.assertFalse(brain._should_continue_write_after_guard("edit_file", []))

    def test_explicit_web_request_auto_promotes_web_tools(self):
        brain = TerminalBrain()
        brain.current_intent = "question"
        brain._reset_deferred_tools()

        names = brain._select_tool_names_for_turn("cherche sur internet la doc", [], autonomous=False)

        self.assertIn("web_search", names)
        self.assertIn("web_fetch", names)
        self.assertIn("web_search", brain._active_promoted_tool_names)

    def test_memory_request_auto_promotes_memory_tools(self):
        brain = TerminalBrain()
        brain.current_intent = "question"
        brain._reset_deferred_tools()

        names = brain._select_tool_names_for_turn("souviens-toi de ma préférence", [], autonomous=False)

        self.assertIn("remember_fact", names)
        self.assertIn("list_memory", names)
        self.assertIn("remember_fact", brain._active_promoted_tool_names)

    def test_complex_task_auto_promotes_write_todos(self):
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain._reset_deferred_tools()

        names = brain._select_tool_names_for_turn(
            "analyse DeerFlow et améliore JoyBoy puis vérifie les tests",
            [],
            autonomous=False,
        )

        self.assertIn("write_todos", names)
        self.assertIn("write_todos", brain._active_promoted_tool_names)

    def test_write_todos_tracks_and_formats_plan(self):
        brain = TerminalBrain()

        result = brain.execute_tool(
            "write_todos",
            {
                "todos": [
                    {"id": "1", "content": "Audit DeerFlow", "status": "completed", "note": "middleware reviewed"},
                    {"id": "2", "content": "Port useful behavior", "status": "in_progress"},
                ]
            },
            os.getcwd(),
        )

        self.assertTrue(result.success)
        self.assertTrue(brain._has_incomplete_todos())
        self.assertIn("completed=1", brain._summarize_executed_tool("write_todos", {}, result)["summary"])
        formatted = brain._format_result_for_llm(result)
        self.assertIn("[completed] Audit DeerFlow", formatted)
        self.assertIn("[in_progress] Port useful behavior", formatted)

    def test_write_todos_rejects_unchanged_plan(self):
        brain = TerminalBrain()
        payload = {
            "todos": [
                {"id": "1", "content": "Audit DeerFlow", "status": "completed", "note": "done"},
                {"id": "2", "content": "Port useful behavior", "status": "in_progress", "note": "ongoing"},
            ]
        }

        first = brain.execute_tool("write_todos", payload, os.getcwd())
        second = brain.execute_tool("write_todos", payload, os.getcwd())

        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertIn("todo list unchanged", second.error)

    def test_todo_reminder_is_injected_after_context_compaction(self):
        brain = TerminalBrain()
        brain.execute_tool(
            "write_todos",
            {"todos": [{"content": "Finish runtime work", "status": "in_progress"}]},
            os.getcwd(),
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "continue"},
        ]

        injected = brain._inject_todo_reminder(messages)

        self.assertEqual(injected[1]["role"], "user")
        self.assertIn("[ACTIVE TODO LIST]", injected[1]["content"])
        self.assertIn("Finish runtime work", injected[1]["content"])

    def test_todo_reminder_includes_current_focus_and_recent_progress(self):
        brain = TerminalBrain()
        brain.execute_tool(
            "write_todos",
            {
                "todos": [
                    {"content": "Review DeerFlow middleware", "status": "completed", "note": "read"},
                    {"content": "Port active execution reminders", "status": "in_progress", "note": "editing terminal_brain"},
                ]
            },
            os.getcwd(),
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "continue"},
        ]

        injected = brain._inject_todo_reminder(
            messages,
            executed_tools=[
                {"tool": "read_file", "success": True, "summary": "terminal_brain.py (220 lines)"},
                {"tool": "edit_file", "success": True, "summary": "updated active reminder block"},
                {"tool": "write_todos", "success": True, "summary": "in_progress=1"},
            ],
        )

        reminder = injected[1]["content"]
        self.assertIn("Current execution step:", reminder)
        self.assertIn("Port active execution reminders", reminder)
        self.assertIn("Recent observed progress:", reminder)
        self.assertIn("read_file: terminal_brain.py (220 lines)", reminder)
        self.assertIn("edit_file: updated active reminder block", reminder)

    def test_delegate_subagent_calls_are_capped_per_response(self):
        brain = TerminalBrain()
        calls = [
            {"type": "function", "function": {"name": "delegate_subagent", "arguments": {"task": f"task {i}"}}}
            for i in range(5)
        ]
        calls.append({"type": "function", "function": {"name": "read_file", "arguments": {"path": "README.md"}}})

        kept, dropped = brain._limit_delegate_subagent_calls(calls)

        self.assertEqual(dropped, 2)
        self.assertEqual(
            sum(1 for call in kept if call["function"]["name"] == "delegate_subagent"),
            3,
        )
        self.assertEqual(kept[-1]["function"]["name"], "read_file")

    def test_terminal_memory_tools_save_and_retrieve_local_facts(self):
        old_home = os.environ.get("JOYBOY_HOME")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOYBOY_HOME"] = tmp
            try:
                brain = TerminalBrain()
                saved = brain.execute_tool(
                    "remember_fact",
                    {
                        "content": "User prefers DeerFlow-style agent planning.",
                        "category": "preference",
                        "confidence": 0.8,
                    },
                    os.getcwd(),
                )
                listed = brain.execute_tool(
                    "list_memory",
                    {"query": "deerflow planning", "limit": 5},
                    os.getcwd(),
                )
            finally:
                if old_home is None:
                    os.environ.pop("JOYBOY_HOME", None)
                else:
                    os.environ["JOYBOY_HOME"] = old_home

        self.assertTrue(saved.success)
        self.assertTrue(listed.success)
        self.assertEqual(listed.data.get("count"), 1)
        self.assertIn("DeerFlow-style", brain._format_result_for_llm(listed))

    def test_memory_context_prompt_injects_matching_facts(self):
        old_home = os.environ.get("JOYBOY_HOME")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOYBOY_HOME"] = tmp
            try:
                brain = TerminalBrain()
                brain.execute_tool(
                    "remember_fact",
                    {
                        "content": "JoyBoy terminal should prefer DeerFlow-style planning.",
                        "category": "preference",
                        "confidence": 0.9,
                    },
                    os.getcwd(),
                )
                prompt = brain._build_memory_context_prompt("deerflow planning")
            finally:
                if old_home is None:
                    os.environ.pop("JOYBOY_HOME", None)
                else:
                    os.environ["JOYBOY_HOME"] = old_home

        self.assertIn("LOCAL MEMORY CONTEXT", prompt)
        self.assertIn("DeerFlow-style planning", prompt)

    def test_large_local_context_scales_terminal_budget_safely(self):
        brain = TerminalBrain()

        self.assertEqual(brain._normalize_context_size(999999), 262144)
        self.assertLessEqual(brain._turn_token_budget(32768), brain.max_non_autonomous_tokens)
        self.assertEqual(brain._turn_token_budget(65536), 12000)
        self.assertEqual(brain._turn_token_budget(131072), 18000)
        self.assertEqual(brain._turn_token_budget(262144), 26000)

    def test_existing_write_requires_read_then_verifies(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "notes.txt"
            target.write_text("hello world\n", encoding="utf-8")

            blocked = brain.execute_tool(
                "write_file",
                {"path": "notes.txt", "content": "hello brave world\n"},
                tmp,
            )
            self.assertFalse(blocked.success)
            self.assertIn("read_file", blocked.error)

            read = brain.execute_tool("read_file", {"path": "notes.txt"}, tmp)
            self.assertTrue(read.success)

            written = brain.execute_tool(
                "write_file",
                {"path": "notes.txt", "content": "hello brave world\n"},
                tmp,
            )
            self.assertTrue(written.success)
            self.assertTrue(written.data.get("verified"))
            self.assertEqual(target.read_text(encoding="utf-8"), "hello brave world\n")

    def test_scaffold_verification_detects_vite_and_next_targets(self):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            vite_dir = Path(tmp) / "my-app"
            vite_dir.mkdir()
            (vite_dir / "package.json").write_text("{}", encoding="utf-8")

            vite = brain._verify_bash_side_effects(
                "npm create vite@latest my-app -- --template react",
                tmp,
            )
            self.assertTrue(vite.get("verified"))
            self.assertEqual(vite.get("kind"), "vite_scaffold")

            next_dir = Path(tmp) / "webapp"
            next_dir.mkdir()
            (next_dir / "package.json").write_text("{}", encoding="utf-8")

            next_app = brain._verify_bash_side_effects(
                "npx create-next-app@latest webapp --ts",
                tmp,
            )
            self.assertTrue(next_app.get("verified"))
            self.assertEqual(next_app.get("kind"), "next_app_scaffold")

            missing = brain._verify_bash_side_effects(
                "npx create-react-app missing-app",
                tmp,
            )
            self.assertFalse(missing.get("verified"))
            self.assertFalse(os.path.exists(Path(tmp) / "missing-app"))

    def test_web_fetch_rejects_non_url(self):
        brain = TerminalBrain()

        result = brain.execute_tool("web_fetch", {"url": "example.com"}, os.getcwd())

        self.assertFalse(result.success)
        self.assertIn("http", result.error)

    @patch("core.backends.terminal_brain.get_cached_mcp_tools")
    def test_deferred_prompt_lists_loaded_mcp_tools(self, mock_get_mcp_tools):
        mock_get_mcp_tools.return_value = [
            McpToolAdapter(
                name="github__search_repositories",
                description="Search repositories through GitHub MCP.",
                schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                invoke=lambda args: {"ok": True, "query": args.get("query", "")},
                server_name="github",
                tags=("mcp", "github"),
            )
        ]
        brain = TerminalBrain()
        brain._reset_deferred_tools()

        prompt = brain._build_deferred_tools_prompt()

        self.assertIn("github__search_repositories", prompt)
        self.assertIn("GitHub MCP", prompt)

    @patch("core.backends.terminal_brain.get_cached_mcp_tools")
    def test_mcp_tool_search_promotes_and_executes_loaded_tool(self, mock_get_mcp_tools):
        mock_get_mcp_tools.return_value = [
            McpToolAdapter(
                name="github__search_repositories",
                description="Search repositories through GitHub MCP.",
                schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                invoke=lambda args: {"items": [{"full_name": f"openai/{args.get('query', '')}"}]},
                server_name="github",
                tags=("mcp", "github"),
            )
        ]
        brain = TerminalBrain()
        brain._reset_deferred_tools()

        promoted = brain.execute_tool("tool_search", {"query": "github"}, os.getcwd())
        executed = brain.execute_tool(
            "github__search_repositories",
            {"query": "joyboy"},
            os.getcwd(),
        )

        self.assertTrue(promoted.success)
        self.assertIn("github__search_repositories", promoted.data.get("promoted", []))
        self.assertTrue(executed.success)
        self.assertEqual(executed.data.get("server_name"), "github")
        self.assertIn("openai/joyboy", brain._format_result_for_llm(executed))


if __name__ == "__main__":
    unittest.main()
