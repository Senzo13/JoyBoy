import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.backends.terminal_brain import ExecutionPlan, PlanStatus, PlanTask, TerminalBrain, ToolResult
from core.agent_runtime import CloudModelError, McpToolAdapter


class TerminalBrainSmokeTests(unittest.TestCase):
    def test_system_prompt_uses_english_operational_guardrails(self):
        brain = TerminalBrain()

        prompt = brain.build_system_prompt("C:/projects/demo", workspace_name="demo")

        self.assertIn("You are JoyBoy Terminal", prompt)
        self.assertIn("Always call read_file", prompt)
        self.assertIn("Do not pretend that files were created", prompt)
        self.assertIn("Workspace path visible to you: /workspace", prompt)
        self.assertIn("explicitly asks for agentic/parallel analysis", prompt)
        self.assertIn("use web_search first, then web_fetch", prompt)
        self.assertIn("verify directly with read_file/list_files", prompt)
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

    def test_cloud_error_metadata_is_read_from_provider_exception_shape(self):
        brain = TerminalBrain()
        error = CloudModelError("")
        error.status_code = 429
        error.body = {"error": {"code": "insufficient_quota"}}

        self.assertEqual(brain._extract_cloud_error_status_code(error), 429)
        self.assertEqual(brain._extract_cloud_error_code(error), "insufficient_quota")
        self.assertEqual(brain._classify_cloud_model_error(error), (False, "quota"))

    def test_cloud_status_can_be_read_from_response_object(self):
        brain = TerminalBrain()
        error = CloudModelError("provider failed")
        error.response = SimpleNamespace(status_code=502, headers={})

        self.assertEqual(brain._extract_cloud_error_status_code(error), 502)
        self.assertEqual(brain._classify_cloud_model_error(error), (True, "transient"))

    def test_cloud_retry_delay_respects_retry_after_headers(self):
        brain = TerminalBrain()
        retry_after_ms = CloudModelError("rate limited")
        retry_after_ms.response = SimpleNamespace(status_code=429, headers={"retry-after-ms": "2500"})
        retry_after_seconds = CloudModelError("service unavailable")
        retry_after_seconds.response = SimpleNamespace(status_code=503, headers={"Retry-After": "3"})

        self.assertEqual(brain._cloud_retry_delay_ms(1, retry_after_ms), 2500)
        self.assertEqual(brain._cloud_retry_delay_ms(1, retry_after_seconds), 3000)

    @patch("core.backends.terminal_brain.time.time", return_value=1_700_000_000)
    def test_cloud_retry_delay_accepts_http_date_retry_after(self, _time):
        brain = TerminalBrain()
        error = CloudModelError("provider busy")
        error.response = SimpleNamespace(
            status_code=503,
            headers={"Retry-After": "Tue, 14 Nov 2023 22:13:23 GMT"},
        )

        self.assertEqual(brain._cloud_retry_delay_ms(1, error), 3000)

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

    def test_cloud_circuit_half_open_allows_one_recovery_probe(self):
        brain = TerminalBrain()
        now = [1_000.0]

        with patch("core.backends.terminal_brain.time.time", side_effect=lambda: now[0]):
            for _ in range(3):
                brain._record_cloud_circuit_failure("openai:gpt-5.4")
            self.assertIn("retry in about", brain._cloud_circuit_block_reason("openai:gpt-5.4"))

            now[0] = 1_061.0
            self.assertIsNone(brain._cloud_circuit_block_reason("openai:gpt-5.4"))
            self.assertIn("recovery probe already running", brain._cloud_circuit_block_reason("openai:gpt-5.4"))

            brain._record_cloud_circuit_success("openai:gpt-5.4")
            self.assertIsNone(brain._cloud_circuit_block_reason("openai:gpt-5.4"))

    def test_cloud_circuit_failed_half_open_probe_reopens(self):
        brain = TerminalBrain()
        now = [2_000.0]

        with patch("core.backends.terminal_brain.time.time", side_effect=lambda: now[0]):
            for _ in range(3):
                brain._record_cloud_circuit_failure("openai:gpt-5.4")

            now[0] = 2_061.0
            self.assertIsNone(brain._cloud_circuit_block_reason("openai:gpt-5.4"))
            brain._record_cloud_circuit_failure("openai:gpt-5.4")

            reason = brain._cloud_circuit_block_reason("openai:gpt-5.4")
            self.assertIn("Cloud circuit breaker active for openai", reason)

    def test_tool_error_classification_covers_permission_and_validation(self):
        brain = TerminalBrain()

        permission = brain._classify_tool_error(
            ToolResult(success=False, tool_name="bash", error="Dangerous command blocked: rm -rf")
        )
        validation = brain._classify_tool_error(
            ToolResult(success=False, tool_name="write_file", error="BLOCKED: existing file was not read first.")
        )

        self.assertEqual(permission, "permission")
        self.assertEqual(validation, "validation")

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_repeated_tool_error_stops_loop(self, mock_chat):
        mock_chat.side_effect = [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "write_files",
                                "arguments": {
                                    "files": [
                                        {"path": "README.md", "content": "updated\n"}
                                    ]
                                },
                            },
                        }
                    ],
                },
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "write_files",
                                "arguments": {
                                    "files": [
                                        {"path": "README.md", "content": "updated\n"}
                                    ]
                                },
                            },
                        }
                    ],
                },
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
        ]
        brain = TerminalBrain()
        brain.current_intent = "write"

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("original\n", encoding="utf-8")
            events = list(brain.run_agentic_loop("explique le README", tmp, model="openai:gpt-5.4"))

        loop_warnings = [event for event in events if event.get("type") == "loop_warning"]
        done = [event for event in events if event.get("type") == "done"][-1]

        self.assertTrue(any(event.get("action") == "tool_error" for event in loop_warnings))
        self.assertIn("erreurs outils répétées", done.get("full_response", ""))
        self.assertEqual(mock_chat.call_count, 2)

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_repeated_tool_batch_warns_before_reexecuting_same_batch(self, mock_chat):
        repeated_tool_batch = [
            {
                "id": "call_list",
                "type": "function",
                "function": {"name": "list_files", "arguments": {"path": "."}},
            },
            {
                "id": "call_glob",
                "type": "function",
                "function": {"name": "glob", "arguments": {"pattern": "*.md"}},
            },
        ]
        mock_chat.side_effect = [
            {
                "message": {"role": "assistant", "content": "", "tool_calls": repeated_tool_batch},
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
            {
                "message": {"role": "assistant", "content": "", "tool_calls": repeated_tool_batch},
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
            {
                "message": {"role": "assistant", "content": "done without repeating tools"},
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
        ]
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("hello\n", encoding="utf-8")
            events = list(brain.run_agentic_loop("cherche README", tmp, model="openai:gpt-5.4"))

        loop_warnings = [event for event in events if event.get("type") == "loop_warning"]
        tool_results = [event for event in events if event.get("type") == "tool_result"]
        done = [event for event in events if event.get("type") == "done"][-1]

        self.assertTrue(any(event.get("action") == "tool_batch_loop" for event in loop_warnings))
        self.assertEqual(len(tool_results), 2)
        self.assertIn("done without repeating tools", done.get("full_response", ""))
        self.assertEqual(mock_chat.call_count, 3)

    def test_tool_call_batch_signature_is_order_independent(self):
        brain = TerminalBrain()
        first = [
            {"function": {"name": "list_files", "arguments": {"path": "."}}},
            {"function": {"name": "glob", "arguments": {"pattern": "*.md"}}},
        ]
        second = [
            {"function": {"name": "glob", "arguments": {"pattern": "*.md"}}},
            {"function": {"name": "list_files", "arguments": {"path": "."}}},
        ]

        self.assertEqual(
            brain._tool_call_batch_signature(first),
            brain._tool_call_batch_signature(second),
        )

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

    def test_missing_tool_call_ids_are_normalized_before_protocol_patch(self):
        brain = TerminalBrain()
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {"name": "list_files", "arguments": {"path": "."}},
                    }
                ],
            },
        ]

        patched = brain._patch_dangling_tool_messages(messages)
        assistant = next(item for item in patched if item.get("role") == "assistant")
        tool = next(item for item in patched if item.get("role") == "tool")
        call_id = assistant["tool_calls"][0]["id"]

        self.assertTrue(call_id)
        self.assertEqual(tool["tool_call_id"], call_id)

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_cloud_dict_tool_call_without_id_gets_matching_tool_output(self, mock_chat):
        mock_chat.side_effect = [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {"name": "list_files", "arguments": {"path": "."}},
                        }
                    ],
                },
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
            {
                "message": {"role": "assistant", "content": "done"},
                "prompt_eval_count": 10,
                "eval_count": 2,
            },
        ]
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("hello\n", encoding="utf-8")
            events = list(brain.run_agentic_loop("liste les fichiers", tmp, model="openai:gpt-5.4"))

        self.assertEqual([event for event in events if event.get("type") == "done"][-1].get("full_response"), "done")
        second_call_messages = mock_chat.call_args_list[1].kwargs["messages"]
        assistant = [item for item in second_call_messages if item.get("role") == "assistant" and item.get("tool_calls")][-1]
        tool = [item for item in second_call_messages if item.get("role") == "tool"][-1]

        self.assertTrue(assistant["tool_calls"][0]["id"])
        self.assertEqual(tool["tool_call_id"], assistant["tool_calls"][0]["id"])

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

    def test_provider_message_format_keeps_cloud_tool_arguments_as_json(self):
        brain = TerminalBrain()
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_list",
                        "type": "function",
                        "function": {"name": "list_files", "arguments": {"path": "."}},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_list", "tool_name": "list_files", "content": "ok"},
        ]

        formatted = brain._format_messages_for_provider(messages, "cloud")
        args = formatted[1]["tool_calls"][0]["function"]["arguments"]

        self.assertIsInstance(args, str)
        self.assertEqual(brain._parse_tool_arguments(args), {"path": "."})

    def test_provider_message_format_converts_ollama_tool_arguments_to_dict(self):
        brain = TerminalBrain()
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_list",
                        "type": "function",
                        "function": {"name": "list_files", "arguments": '{"path":"."}'},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_list", "tool_name": "list_files", "content": "ok"},
        ]

        formatted = brain._format_messages_for_provider(messages, "ollama")
        args = formatted[1]["tool_calls"][0]["function"]["arguments"]

        self.assertIsInstance(args, dict)
        self.assertEqual(args, {"path": "."})
        self.assertIsInstance(messages[1]["tool_calls"][0]["function"]["arguments"], str)

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

    def test_clear_workspace_preserves_git_metadata_in_full_access(self):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".git").mkdir()
            Path(tmp, "src").mkdir()
            Path(tmp, "src", "old.js").write_text("old", encoding="utf-8")
            Path(tmp, "README.md").write_text("old", encoding="utf-8")
            brain.current_intent = "write"

            blocked = brain.execute_tool("clear_workspace", {}, tmp)
            self.assertFalse(blocked.success)
            self.assertIn("full access", blocked.error)

            brain.permission_mode = "full_access"
            result = brain.execute_tool("clear_workspace", {}, tmp)

            self.assertTrue(result.success)
            self.assertTrue(Path(tmp, ".git").exists())
            self.assertFalse(Path(tmp, "src").exists())
            self.assertFalse(Path(tmp, "README.md").exists())
            self.assertIn(".git", result.data.get("kept", []))

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_clear_workspace_request_runs_directly_in_full_access(self, mock_chat):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".git").mkdir()
            Path(tmp, "public").mkdir()
            Path(tmp, "src").mkdir()
            Path(tmp, "public", "index.html").write_text("old", encoding="utf-8")
            Path(tmp, "README.md").write_text("old", encoding="utf-8")

            events = list(
                brain.run_agentic_loop(
                    "supprime ce qu'il y a dans le dossier",
                    tmp,
                    model="openai:gpt-5.4",
                    permission_mode="full_access",
                )
            )

            self.assertFalse(mock_chat.called)
            self.assertTrue(Path(tmp, ".git").exists())
            self.assertFalse(Path(tmp, "public").exists())
            self.assertFalse(Path(tmp, "src").exists())
            self.assertFalse(Path(tmp, "README.md").exists())
            tool_calls = [event for event in events if event.get("type") == "tool_call"]
            self.assertEqual([event.get("name") for event in tool_calls], ["clear_workspace"])
            done = [event for event in events if event.get("type") == "done"][-1]
            self.assertEqual(done.get("token_stats", {}).get("total"), 0)

    def test_clear_workspace_request_detects_folder_content_phrasing(self):
        self.assertTrue(
            TerminalBrain._is_clear_workspace_request("supprime ce qu'il y a dans le dossier")
        )
        self.assertTrue(
            TerminalBrain._is_clear_workspace_request("supprime le contenu du dossier")
        )
        self.assertFalse(TerminalBrain._is_clear_workspace_request("supprime README.md"))

    def test_full_access_workspace_clear_shell_command_uses_internal_tool(self):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".git").mkdir()
            Path(tmp, "src").mkdir()
            Path(tmp, "src", "old.js").write_text("old", encoding="utf-8")
            Path(tmp, "README.md").write_text("old", encoding="utf-8")
            brain.current_intent = "write"
            brain.permission_mode = "full_access"

            result = brain.execute_tool(
                "bash",
                {"command": "Get-ChildItem -Force | Where-Object { $_.Name -ne '.git' } | Remove-Item -Recurse -Force"},
                tmp,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.tool_name, "bash")
            self.assertEqual(result.data.get("converted_action"), "clear_workspace")
            self.assertTrue(Path(tmp, ".git").exists())
            self.assertFalse(Path(tmp, "src").exists())
            self.assertFalse(Path(tmp, "README.md").exists())

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_default_destructive_tool_pauses_for_approval_without_retry(self, mock_chat):
        mock_chat.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_clear",
                        "type": "function",
                        "function": {"name": "clear_workspace", "arguments": {"keep": []}},
                    }
                ],
            },
            "prompt_eval_count": 20,
            "eval_count": 5,
        }
        brain = TerminalBrain()

        workspace_tmp_root = Path(__file__).resolve().parents[1]
        tmp_path = workspace_tmp_root / "_terminal_approval_tmp"
        shutil.rmtree(tmp_path, ignore_errors=True)
        tmp_path.mkdir()
        try:
            target = tmp_path / "README.md"
            target.write_text("keep until approved\n", encoding="utf-8")
            events = list(brain.run_agentic_loop("delete tout", str(tmp_path), model="openai:gpt-5.4"))

            self.assertTrue(target.exists())
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

        approvals = [event for event in events if event.get("type") == "approval_required"]
        done = [event for event in events if event.get("type") == "done"][-1]

        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].get("tool_name"), "clear_workspace")
        self.assertTrue(approvals[0].get("permission", {}).get("requires_confirmation"))
        self.assertTrue(done.get("approval_required"))
        self.assertEqual(mock_chat.call_count, 0)

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

    def test_vague_followup_without_context_uses_clarification_fast_path(self):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            events = list(brain.run_agentic_loop("fais le", tmp, model="openai:gpt-5.4"))

        self.assertFalse(any(event.get("type") == "thinking" for event in events))
        self.assertFalse(any(event.get("type") == "tool_call" for event in events))
        done = [event for event in events if event.get("type") == "done"][-1]
        self.assertEqual(done.get("token_stats", {}).get("total"), 0)
        self.assertIn("trop vague", done.get("full_response", ""))

    def test_clarification_detector_uses_context_and_specific_targets(self):
        brain = TerminalBrain()

        self.assertTrue(brain._should_clarify_request("continue", history=[]))
        self.assertFalse(
            brain._should_clarify_request(
                "corrige le scroll dans web/static/js/settings.js",
                history=[],
            )
        )
        self.assertFalse(
            brain._should_clarify_request(
                "continue",
                history=[{"role": "user", "content": "Crée un template React propre dans le dossier caca"}],
            )
        )

        brain.current_plan = ExecutionPlan(
            title="Plan",
            goal="Finish terminal task",
            tasks=[PlanTask(id="1", title="Implement", status=PlanStatus.IN_PROGRESS)],
        )
        self.assertFalse(brain._should_clarify_request("continue", history=[]))

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

    def test_execution_journal_records_and_injects_useful_tool_state(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        read_result = ToolResult(
            success=True,
            tool_name="read_file",
            data={"path": "src/app/page.jsx", "lines": 42},
        )
        read_summary = brain._summarize_executed_tool(
            "read_file",
            {"path": "src/app/page.jsx"},
            read_result,
        )
        brain._record_execution_journal("read_file", {"path": "src/app/page.jsx"}, read_result, read_summary)

        write_result = ToolResult(
            success=True,
            tool_name="write_files",
            data={"files": [{"path": "src/app/page.jsx"}, {"path": "src/app/globals.css"}]},
        )
        write_summary = brain._summarize_executed_tool(
            "write_files",
            {"files": []},
            write_result,
        )
        brain._record_execution_journal("write_files", {"files": []}, write_result, write_summary)

        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "crée un template complet"},
        ]
        injected = brain._inject_execution_journal(messages)
        journal_messages = [
            msg for msg in injected
            if msg.get("content", "").startswith("[EXECUTION JOURNAL]")
        ]

        self.assertEqual(len(journal_messages), 1)
        self.assertIn("read src/app/page.jsx", journal_messages[0]["content"])
        self.assertIn("wrote batch: src/app/page.jsx, src/app/globals.css", journal_messages[0]["content"])

        reinjected = brain._inject_execution_journal(injected)
        self.assertEqual(
            sum(1 for msg in reinjected if msg.get("content", "").startswith("[EXECUTION JOURNAL]")),
            1,
        )

    def test_execution_journal_ignores_planning_noise_and_dedupes_targets(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        todo_result = ToolResult(
            success=True,
            tool_name="write_todos",
            data={"counts": {"in_progress": 1}},
        )
        brain._record_execution_journal(
            "write_todos",
            {},
            todo_result,
            brain._summarize_executed_tool("write_todos", {}, todo_result),
        )
        self.assertEqual(brain._active_execution_journal, [])

        first_read = ToolResult(
            success=True,
            tool_name="read_file",
            data={"path": "README.md", "lines": 10},
        )
        second_read = ToolResult(
            success=True,
            tool_name="read_file",
            data={"path": "README.md", "lines": 12},
        )
        brain._record_execution_journal(
            "read_file",
            {"path": "README.md"},
            first_read,
            brain._summarize_executed_tool("read_file", {"path": "README.md"}, first_read),
        )
        brain._record_execution_journal(
            "read_file",
            {"path": "README.md"},
            second_read,
            brain._summarize_executed_tool("read_file", {"path": "README.md"}, second_read),
        )

        self.assertEqual(len(brain._active_execution_journal), 1)
        self.assertIn("12 line", brain._active_execution_journal[0]["line"])

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

    def test_tool_schema_stats_report_active_schema_cost(self):
        brain = TerminalBrain()
        tools = brain.tool_registry.ollama_tools(["list_files", "read_file"])

        stats = brain._tool_schema_stats(tools)

        self.assertEqual(stats.get("tool_count"), 2)
        self.assertGreater(stats.get("tool_schema_tokens", 0), 0)

    def test_prepare_model_call_applies_premodel_middleware_chain(self):
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain._active_context_size = 4096
        result = ToolResult(success=True, tool_name="read_file", data={"path": "README.md", "lines": 12})
        summary = brain._summarize_executed_tool("read_file", {"path": "README.md"}, result)
        brain._record_execution_journal("read_file", {"path": "README.md"}, result, summary)

        messages, tools, prompt_estimate, stats = brain._prepare_model_call(
            messages=[
                {"role": "system", "content": "system"},
                {"role": "user", "content": "corrige le README"},
            ],
            initial_message="corrige le README",
            executed_tools=[summary],
            force_final=False,
            autonomous=False,
        )

        self.assertTrue(any(msg.get("content", "").startswith("[EXECUTION JOURNAL]") for msg in messages))
        self.assertGreater(len(tools), 0)
        self.assertGreater(prompt_estimate, 0)
        self.assertEqual(stats.get("tool_count"), len(tools))

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

    def test_replace_backend_architecture_is_scaffold_without_todo_loop(self):
        brain = TerminalBrain()
        message = "supprime tout et fait moi une architecture backend propre et solide en express"
        brain.current_intent = brain.detect_intent(message)
        brain._reset_deferred_tools()

        names = brain._select_tool_names_for_turn(message, [], autonomous=False)

        self.assertEqual(brain.current_intent, "write")
        self.assertTrue(brain._is_scaffold_write_request(message))
        self.assertIn("clear_workspace", names)
        self.assertLess(names.index("clear_workspace"), names.index("write_files"))
        self.assertNotIn("write_todos", names)
        self.assertNotIn("tool_search", names)

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_scaffold_write_files_finishes_without_extra_model_call(self, mock_chat):
        mock_chat.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "write_files",
                            "arguments": {
                                "files": [
                                    {"path": "package.json", "content": "{\"scripts\":{\"start\":\"node src/server.js\"}}\n"},
                                    {"path": "src/server.js", "content": "console.log('ok');\n"},
                                ]
                            },
                        },
                    }
                ],
            },
            "prompt_eval_count": 100,
            "eval_count": 25,
        }
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            events = list(brain.run_agentic_loop("crée un template backend express", tmp, model="openai:gpt-5.4"))

        done = [event for event in events if event.get("type") == "done"][-1]
        self.assertEqual(mock_chat.call_count, 1)
        self.assertIn("écritures ont été vérifiées", done.get("full_response", ""))
        self.assertTrue(any(event.get("type") == "tool_result" for event in events))

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_full_access_clear_then_scaffold_finishes_in_one_model_call(self, mock_chat):
        mock_chat.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_clear",
                        "type": "function",
                        "function": {"name": "clear_workspace", "arguments": {}},
                    },
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "write_files",
                            "arguments": {
                                "files": [
                                    {"path": "package.json", "content": "{\"scripts\":{\"start\":\"node src/server.js\"}}\n"},
                                    {"path": "src/server.js", "content": "console.log('api');\n"},
                                ]
                            },
                        },
                    },
                ],
            },
            "prompt_eval_count": 140,
            "eval_count": 30,
        }
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".git").mkdir()
            Path(tmp, "old.txt").write_text("old", encoding="utf-8")
            events = list(
                brain.run_agentic_loop(
                    "supprime tout et fait moi une architecture backend propre en express",
                    tmp,
                    model="openai:gpt-5.4",
                    permission_mode="full_access",
                )
            )
            self.assertTrue(Path(tmp, ".git").exists())
            self.assertFalse(Path(tmp, "old.txt").exists())
            self.assertTrue(Path(tmp, "package.json").exists())
            self.assertTrue(Path(tmp, "src", "server.js").exists())

        done = [event for event in events if event.get("type") == "done"][-1]
        self.assertEqual(mock_chat.call_count, 1)
        self.assertIn("clear_workspace", done.get("full_response", ""))
        self.assertIn("write_files", done.get("full_response", ""))

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

    def test_active_plan_focus_reorders_write_tools_after_passive_loop(self):
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain.execute_tool(
            "write_todos",
            {
                "todos": [
                    {"content": "Review current scaffold", "status": "completed"},
                    {"content": "Create React scaffold files", "status": "in_progress"},
                ]
            },
            os.getcwd(),
        )

        names = brain._select_tool_names_for_turn(
            "crée un template react propre",
            executed_tools=[
                {"tool": "list_files", "success": True, "summary": "0 item(s)"},
                {"tool": "read_file", "success": True, "summary": "package.json (40 lines)"},
                {"tool": "search", "success": True, "summary": "0 result(s)"},
            ],
            autonomous=False,
        )

        self.assertLess(names.index("write_files"), names.index("list_files"))
        self.assertLess(names.index("write_file"), names.index("list_files"))
        self.assertNotIn("tool_search", names)

    def test_active_verify_step_prioritizes_verification_tools(self):
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain._reset_deferred_tools()
        brain.execute_tool(
            "write_todos",
            {
                "todos": [
                    {"content": "Create runtime changes", "status": "completed"},
                    {"content": "Verify tests and build", "status": "in_progress"},
                ]
            },
            os.getcwd(),
        )

        names = brain._select_tool_names_for_turn(
            "corrige puis vérifie les tests",
            executed_tools=[
                {"tool": "list_files", "success": True, "summary": "4 item(s)"},
                {"tool": "read_file", "success": True, "summary": "terminal_brain.py (220 lines)"},
                {"tool": "search", "success": True, "summary": "2 result(s)"},
            ],
            autonomous=False,
        )

        self.assertLess(names.index("bash"), names.index("list_files"))
        self.assertNotIn("delegate_subagent", names)
        self.assertNotIn("tool_search", names)

    def test_step_focus_reminder_is_injected_after_passive_write_loop(self):
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain.execute_tool(
            "write_todos",
            {
                "todos": [
                    {"content": "Inspect files", "status": "completed"},
                    {"content": "Apply the real patch", "status": "in_progress"},
                ]
            },
            os.getcwd(),
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "continue"},
        ]

        injected = brain._inject_step_focus_reminder(
            messages,
            "corrige ce fichier",
            executed_tools=[
                {"tool": "list_files", "success": True, "summary": "5 item(s)"},
                {"tool": "read_file", "success": True, "summary": "app.py (120 lines)"},
                {"tool": "search", "success": True, "summary": "1 result(s)"},
            ],
        )

        self.assertEqual(injected[1]["role"], "user")
        self.assertIn("[ACTIVE EXECUTION STEP]", injected[1]["content"])
        self.assertIn("Apply the real patch", injected[1]["content"])
        self.assertIn("Use edit_file, write_files, write_file, or bash now", injected[1]["content"])

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

    def test_delegate_subagent_limit_drops_duplicates_and_empty_tasks(self):
        brain = TerminalBrain()
        calls = [
            {"type": "function", "function": {"name": "delegate_subagent", "arguments": {"task": "Explore MCP", "agent_type": "code_explorer"}}},
            {"type": "function", "function": {"name": "delegate_subagent", "arguments": {"task": "  Explore   MCP  ", "agent_type": "code_explorer"}}},
            {"type": "function", "function": {"name": "delegate_subagent", "arguments": {"task": "", "agent_type": "code_explorer"}}},
            {"type": "function", "function": {"name": "delegate_subagent", "arguments": {"task": "Run tests", "agent_type": "verifier", "command": "python -m unittest"}}},
            {"type": "function", "function": {"name": "read_file", "arguments": {"path": "README.md"}}},
        ]

        kept, dropped = brain._limit_delegate_subagent_calls(calls)

        self.assertEqual(dropped, 2)
        self.assertEqual(
            sum(1 for call in kept if call["function"]["name"] == "delegate_subagent"),
            2,
        )
        self.assertEqual(kept[-1]["function"]["name"], "read_file")

    def test_delegate_subagent_call_key_requires_real_task(self):
        brain = TerminalBrain()

        self.assertEqual(
            brain._delegate_subagent_call_key(
                {"function": {"name": "delegate_subagent", "arguments": {"task": "   "}}}
            ),
            "",
        )
        self.assertEqual(
            brain._delegate_subagent_call_key(
                {"function": {"name": "delegate_subagent", "arguments": {"task": "Explore MCP", "agent_type": "code_explorer"}}}
            ),
            "code_explorer:explore mcp:",
        )

    def test_tool_call_batch_type_limit_drops_excess_repeated_tools(self):
        brain = TerminalBrain()
        calls = [
            {"type": "function", "function": {"name": "read_file", "arguments": {"path": f"file_{index}.py"}}}
            for index in range(10)
        ]
        calls.append({"type": "function", "function": {"name": "search", "arguments": {"pattern": "JoyBoy"}}})

        kept, dropped = brain._limit_tool_calls_by_type(calls)

        self.assertEqual(dropped, {"read_file": 2})
        self.assertEqual(len(kept), 9)
        self.assertEqual(sum(1 for call in kept if call["function"]["name"] == "read_file"), 8)
        self.assertEqual(kept[-1]["function"]["name"], "search")

    @patch("core.backends.terminal_brain.chat_with_cloud_model")
    def test_run_loop_warns_and_executes_only_limited_tool_batch(self, mock_chat):
        tool_calls = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": "read_file", "arguments": {"path": f"file_{index}.txt"}},
            }
            for index in range(10)
        ]
        mock_chat.side_effect = [
            {
                "message": {"role": "assistant", "content": "", "tool_calls": tool_calls},
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
            {
                "message": {"role": "assistant", "content": "limited and done"},
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
        ]
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            for index in range(10):
                Path(tmp, f"file_{index}.txt").write_text(f"{index}\n", encoding="utf-8")
            events = list(brain.run_agentic_loop("lis ces fichiers", tmp, model="openai:gpt-5.4"))

        warnings = [event for event in events if event.get("type") == "loop_warning"]
        tool_results = [event for event in events if event.get("type") == "tool_result"]
        done = [event for event in events if event.get("type") == "done"][-1]

        self.assertTrue(any(event.get("action") == "tool_batch_frequency" for event in warnings))
        self.assertEqual(len(tool_results), 8)
        self.assertIn("limited and done", done.get("full_response", ""))

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
        self.assertIn("mcp:github", prompt)
        self.assertNotIn("Search repositories through GitHub MCP", prompt)

    @patch("core.backends.terminal_brain.get_cached_mcp_tools")
    def test_deferred_tool_search_matches_mcp_server_tags(self, mock_get_mcp_tools):
        mock_get_mcp_tools.return_value = [
            McpToolAdapter(
                name="search_repositories",
                description="Search repositories.",
                schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                invoke=lambda args: {"ok": True},
                server_name="github",
                tags=("mcp", "github"),
            )
        ]
        brain = TerminalBrain()
        brain._reset_deferred_tools()

        result = brain.execute_tool("tool_search", {"query": "github repos"}, os.getcwd())

        self.assertTrue(result.success)
        self.assertEqual(result.data.get("promoted"), ["search_repositories"])

    @patch("core.backends.terminal_brain.get_cached_mcp_tools")
    def test_autonomous_tool_selection_keeps_mcp_deferred(self, mock_get_mcp_tools):
        mock_get_mcp_tools.return_value = [
            McpToolAdapter(
                name="github__search_repositories",
                description="Search repositories through GitHub MCP.",
                schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                invoke=lambda args: {"ok": True},
                server_name="github",
                tags=("mcp", "github"),
            )
        ]
        brain = TerminalBrain()
        brain.current_intent = "write"
        brain._reset_deferred_tools()

        names = brain._select_tool_names_for_turn(
            "utilise le mcp github si besoin /auto",
            [],
            autonomous=True,
        )

        self.assertIn("write_file", names)
        self.assertIn("tool_search", names)
        self.assertNotIn("github__search_repositories", names)

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
