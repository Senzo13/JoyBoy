"""
Blueprint pour les routes terminal et workspace (terminal/detect, terminal/select-workspace,
terminal/chat, workspace/list, workspace/read, workspace/search, workspace/glob,
workspace/summary, workspace/validate, workspace/check-model).
"""
from flask import Blueprint, request, jsonify
import base64
import os
import platform
import subprocess
import uuid

terminal_bp = Blueprint('terminal', __name__)

TERMINAL_BUSY_MESSAGE = (
    "Cette conversation terminal traite déjà une demande. "
    "Attends la fin ou appuie sur stop avant de relancer."
)


def _terminal_run_key(chat_id, workspace_path):
    chat_key = str(chat_id or "").strip()
    if chat_key:
        return f"terminal:chat:{chat_key}"
    normalized_workspace = os.path.normcase(os.path.abspath(str(workspace_path or "")))
    return f"terminal:workspace:{normalized_workspace}"


# ===== TERMINAL MODE (joyboy run) =====

@terminal_bp.route('/terminal/detect', methods=['POST'])
def terminal_detect():
    """Détecte si le message active le mode terminal ou parle de workspace"""
    from core import utility_ai

    data = request.json
    message = data.get('message', '')

    is_terminal_trigger = utility_ai.detect_terminal_intent(message)
    is_workspace_intent = utility_ai.detect_workspace_intent(message)

    return jsonify({
        'terminal_trigger': is_terminal_trigger,
        'workspace_intent': is_workspace_intent
    })


@terminal_bp.route('/terminal/tools', methods=['GET'])
def terminal_tools():
    """Return terminal tool metadata for UI cards and future plugin surfaces."""
    from core.terminal_brain import get_brain

    brain = get_brain()
    return jsonify({
        'success': True,
        'tools': brain.tool_registry.public_tools()
    })


@terminal_bp.route('/terminal/select-workspace', methods=['POST'])
def terminal_select_workspace():
    """Utilise l'IA pour sélectionner le bon workspace"""
    from core import utility_ai

    data = request.json
    message = data.get('message', '')
    workspaces = data.get('workspaces', [])

    if not workspaces:
        return jsonify({'workspace': None, 'error': 'Aucun workspace configuré'})

    selected = utility_ai.select_workspace_ai(message, workspaces)

    if selected:
        return jsonify({'workspace': selected})
    else:
        return jsonify({'workspace': None, 'needs_selection': True})


@terminal_bp.route('/terminal/chat', methods=['POST'])
def terminal_chat():
    """Chat en mode terminal - comportement Claude Code"""
    from flask import Response, stream_with_context
    import json

    data = request.json
    message = data.get('message', '')
    image_b64 = data.get('image')  # Image base64 pour les modèles vision
    history = data.get('history', [])
    workspace = data.get('workspace')  # {name, path}
    chat_model = data.get('chatModel', 'qwen3.5:2b')
    context_size = data.get('contextSize', 8192)  # Plus grand pour le code
    reasoning_effort = data.get('reasoningEffort')
    permission_mode = data.get('permissionMode') or data.get('permission_mode') or 'default'
    chat_id = data.get('chatId') or data.get('conversation_id')

    if not message:
        return jsonify({'error': 'Message requis'}), 400

    if not workspace or not workspace.get('path'):
        return jsonify({
            'error': 'Workspace requis en mode terminal',
            'code': 'workspace_required',
            'message': 'Choisis ou ajoute un dossier projet pour que JoyBoy puisse utiliser les outils terminal.'
        }), 400

    # Vérifier si une image est envoyée avec un modèle vision
    has_image = bool(image_b64)
    if has_image:
        print(f"[TERMINAL] Image reçue ({len(image_b64) // 1024}KB) - modèle: {chat_model}")

    from core.agent_runtime import is_cloud_model_name
    from core.terminal_brain import get_brain, is_tool_capable

    workspace_path = workspace['path']
    workspace_name = workspace.get('name', os.path.basename(workspace_path))
    brain = get_brain()
    from core.runtime import get_active_run_registry

    terminal_run_key = _terminal_run_key(chat_id, workspace_path)
    terminal_run_owner = str(uuid.uuid4())
    active_run_registry = get_active_run_registry()
    if not active_run_registry.acquire(
        terminal_run_key,
        terminal_run_owner,
        metadata={
            "kind": "terminal",
            "chat_id": chat_id,
            "workspace": workspace_path,
            "workspace_name": workspace_name,
            "model": chat_model,
            "message": message[:160],
        },
    ):
        active_run = active_run_registry.get(terminal_run_key) or {}
        return jsonify({
            'error': 'Terminal occupé',
            'code': 'terminal_busy',
            'message': TERMINAL_BUSY_MESSAGE,
            'active_run': {
                'started_at': active_run.get('started_at'),
                'workspace_name': (active_run.get('metadata') or {}).get('workspace_name'),
            }
        }), 409

    job_manager = None
    terminal_job_id = None
    try:
        from core.runtime import get_conversation_store, get_job_manager

        job_manager = get_job_manager()
        if chat_id:
            # Terminal jobs must attach to the existing conversation when the
            # user resumes a thread. Calling create() here would overwrite the
            # stored transcript for an existing chat_id.
            conversation_store = get_conversation_store()
            if not conversation_store.get(chat_id):
                conversation_store.create(
                    conversation_id=chat_id,
                    title=message[:44] or "Terminal",
                    metadata={"workspace": workspace_path, "source": "terminal"},
                )
        terminal_job = job_manager.create(
            "terminal",
            job_id=terminal_run_owner,
            conversation_id=chat_id,
            prompt=message,
            model=chat_model,
            metadata={"workspace": workspace_path, "workspace_name": workspace_name},
        )
        terminal_job_id = terminal_job.get("id")
    except Exception as exc:
        print(f"[TERMINAL] Runtime job disabled: {exc}")

    # Keep operational guardrails in English for stronger tool-following.
    # The prompt still asks the agent to answer in the user's language.
    try:
        system_content = brain.build_system_prompt(
            workspace_path=workspace_path,
            workspace_name=workspace_name,
            force_response_language="French" if has_image else None,
        )
    except Exception:
        if job_manager and terminal_job_id:
            job_manager.fail(terminal_job_id, "Terminal prompt build failed")
        active_run_registry.release(terminal_run_key, terminal_run_owner)
        raise

    chat_messages = [{"role": "system", "content": system_content}]
    recent_history = history[-15:] if len(history) > 15 else history

    # Si on a une image, l'ajouter au dernier message (ou créer un nouveau message user)
    # TODO: brancher l'image dans un vrai tool vision. Pour l'instant on évite
    # d'injecter des payloads base64 massifs dans l'historique terminal.
    if has_image:
        print("[TERMINAL] Image reçue mais non injectée dans le contexte tool-calling")

    print(f"\n{'='*60}")
    print(f"[TERMINAL] Mode: {workspace_name} | Model: {chat_model}")
    print(f"[TERMINAL] Permissions: {permission_mode}")
    print(f"[TERMINAL] Message: {message[:100]}..." + (" [+IMAGE]" if has_image else ""))
    print(f"{'='*60}\n")

    is_capable = is_cloud_model_name(chat_model) or is_tool_capable(chat_model)

    if not is_capable:
        print(f"[TERMINAL] ⚠️ Modèle {chat_model} non optimal pour le tool calling")

    def tool_display_target(tool_name, args):
        args = args if isinstance(args, dict) else {}
        if tool_name == 'write_files':
            files = args.get('files', [])
            if isinstance(files, list):
                paths = [
                    str(item.get('path', '')).strip()
                    for item in files[:3]
                    if isinstance(item, dict) and item.get('path')
                ]
                suffix = f", +{len(files) - len(paths)}" if len(files) > len(paths) else ""
                return f"{', '.join(paths)}{suffix}" if paths else f"{len(files)} files"
            return "files"
        if tool_name == 'write_todos':
            todos = args.get('todos', [])
            return f"{len(todos)} steps" if isinstance(todos, list) else "steps"
        if tool_name == 'clear_workspace':
            keep = args.get('keep', [])
            return f"keep: {', '.join(keep)}" if isinstance(keep, list) and keep else "workspace"
        for key in ('path', 'pattern', 'command', 'query', 'url', 'skill_id', 'task'):
            value = args.get(key)
            if value:
                return value
        return ''

    def _generate_terminal_events():
        """
        Boucle agentique avec Native Tool Calling (comme Cursor/Claude Code).
        Utilise brain.run_agentic_loop qui gère tout via ollama.chat() avec tools.
        """
        # Construire le system prompt
        system_prompt = chat_messages[0]["content"] if chat_messages else ""

        # Construire l'historique pour le brain. Ne pas dupliquer `history`:
        # le TerminalBrain compacte déjà les derniers tours selon le contexte.
        brain_history = [
            {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            for msg in recent_history
        ]

        # Message avec image si présente
        user_message = message
        if has_image:
            user_message = f"(Reply in French for this turn.) {message}"
            # Note: les images sont gérées différemment avec native tools
            # Pour l'instant on les ignore, à améliorer plus tard

        # Utiliser la nouvelle boucle agentique avec native tool calling
        if job_manager and terminal_job_id:
            job_manager.update(
                terminal_job_id,
                status="running",
                phase="thinking",
                progress=3,
                message="Terminal agent running",
            )

        for event in brain.run_agentic_loop(
            initial_message=user_message,
            workspace_path=workspace_path,
            model=chat_model,
            system_prompt=system_prompt,
            history=brain_history,
            context_size=context_size,
            reasoning_effort=reasoning_effort,
            permission_mode=permission_mode,
            job_id=terminal_job_id,
        ):
            if job_manager and terminal_job_id and job_manager.is_cancel_requested(terminal_job_id):
                job_manager.cancel(terminal_job_id, "Terminal request cancelled")
                yield f"data: {json.dumps({'error': 'Interrompu', 'done': True})}\n\n"
                return

            event_type = event.get('type', '')

            # Mapper les events vers le format attendu par le frontend
            if event_type == 'intent':
                yield f"data: {json.dumps({'intent': event['intent'], 'read_only': event['read_only'], 'autonomous': event.get('autonomous', False), 'permission_mode': event.get('permission_mode')})}\n\n"

            elif event_type == 'warning':
                print(f"[TERMINAL] Warning: {event.get('message', '')}")

            elif event_type == 'loop_warning':
                reason = event.get('reason', 'Boucle terminal évitée')
                print(f"[TERMINAL] Loop guard: {event.get('action', '')} - {reason}")
                if job_manager and terminal_job_id:
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="guardrail",
                        progress=None,
                        message=reason[:160],
                    )
                yield f"data: {json.dumps({'loop_warning': True, 'action': event.get('action', ''), 'reason': reason})}\n\n"

            elif event_type == 'thinking':
                if job_manager and terminal_job_id:
                    max_iterations = max(1, int(event.get('max_iterations', 24) or 24))
                    progress = min(88, 8 + (int(event.get('iteration', 1) or 1) / max_iterations) * 70)
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="thinking",
                        progress=progress,
                        message=f"Iteration {event.get('iteration', 1)}/{max_iterations}",
                    )
                yield f"data: {json.dumps({'thinking': True, 'iteration': event['iteration'], 'max_iterations': event.get('max_iterations', 24)})}\n\n"
                print(f"[TERMINAL] Iteration {event['iteration']}")

            elif event_type == 'model_call':
                tools_count = int(event.get('tools_count') or 0)
                label = "Appel du modèle"
                if tools_count:
                    label = f"Appel du modèle ({tools_count} outil(s) disponibles)"
                if job_manager and terminal_job_id:
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="model_call",
                        progress=None,
                        message=label,
                    )
                yield f"data: {json.dumps({'model_call': {'model': event.get('model', ''), 'provider': event.get('provider', ''), 'iteration': event.get('iteration', 1), 'tools_count': tools_count, 'estimated_prompt_tokens': event.get('estimated_prompt_tokens', 0)}})}\n\n"

            elif event_type == 'content':
                if job_manager and terminal_job_id:
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="responding",
                        progress=92,
                        message="Writing response",
                    )
                yield f"data: {json.dumps({'content': event['text']})}\n\n"

            elif event_type == 'tool_call':
                tool_name = event.get('name', '')
                args = event.get('args', {})
                # Extraire path des args pour compatibilité frontend
                path = workspace_path if tool_name == 'open_workspace' else tool_display_target(tool_name, args)
                if job_manager and terminal_job_id:
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="tool_call",
                        progress=None,
                        message=f"{tool_name}: {path}"[:160],
                    )
                print(f"[TERMINAL] Tool call: {tool_name}({path})")
                yield f"data: {json.dumps({'tool_call': {'action': tool_name, 'path': path, 'args': args}})}\n\n"

            elif event_type == 'tool_progress':
                tool_name = event.get('name', '')
                args = event.get('args', {}) or {}
                elapsed_seconds = int(event.get('elapsed_seconds') or 0)
                path = tool_display_target(tool_name, args)
                label = f"{tool_name} running for {elapsed_seconds}s"
                if job_manager and terminal_job_id:
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="tool_progress",
                        progress=None,
                        message=label[:160],
                    )
                yield f"data: {json.dumps({'tool_progress': {'action': tool_name, 'path': path, 'args': args, 'elapsed_seconds': elapsed_seconds}})}\n\n"

            elif event_type == 'tool_result':
                result = event.get('result', {})
                data = result.get('data', {})
                permission_info = data.get('permission') if isinstance(data, dict) else None
                if job_manager and terminal_job_id:
                    status_text = "Tool completed" if result.get('success') else "Tool error"
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="tool_result",
                        progress=None,
                        message=status_text,
                    )
                result_data = {
                    'tool_result': {
                        'success': result.get('success', False),
                        'action': result.get('tool_name', ''),
                        'path': '',
                        'error': result.get('error'),
                        'write_blocked': result.get('write_blocked', False)
                    }
                }
                # Inclure les données selon le type
                tool_name = result.get('tool_name', '')
                if permission_info:
                    result_data['tool_result']['permission'] = permission_info

                if result.get('success'):
                    if tool_name == 'list_files':
                        result_data['tool_result']['items'] = data.get('items', [])[:30]
                        result_data['tool_result']['path'] = data.get('path', '')
                        result_data['tool_result']['summary'] = f"{data.get('total', len(data.get('items', [])))} élément(s)"
                    elif tool_name == 'read_file':
                        result_data['tool_result']['content'] = data.get('content', '')[:3000]
                        result_data['tool_result']['lines'] = data.get('lines', 0)
                        result_data['tool_result']['path'] = data.get('path', '')
                        result_data['tool_result']['already_read'] = data.get('already_read', False)
                        read_summary = f"{data.get('path', '')} · {data.get('lines', 0)} lines".strip(" ·")
                        if data.get('already_read'):
                            read_summary = f"{data.get('path', '')} déjà lu".strip()
                        result_data['tool_result']['summary'] = read_summary
                    elif tool_name in ['write_file', 'edit_file']:
                        result_data['tool_result']['bytes_written'] = data.get('bytes_written', 0)
                        result_data['tool_result']['path'] = data.get('path', '')
                        result_data['tool_result']['verified'] = data.get('verified', False)
                        result_data['tool_result']['size'] = data.get('size')
                        result_data['tool_result']['created'] = data.get('created')
                        result_data['tool_result']['replacements'] = data.get('replacements')
                        result_data['tool_result']['lines_added'] = data.get('lines_added')
                        result_data['tool_result']['lines_removed'] = data.get('lines_removed')
                        result_data['tool_result']['line_range'] = data.get('line_range')
                        result_data['tool_result']['diff_preview'] = data.get('diff_preview', '')[:6000]
                        if tool_name == 'edit_file':
                            added = int(data.get('lines_added') or 0)
                            removed = int(data.get('lines_removed') or 0)
                            result_data['tool_result']['summary'] = (
                                f"{data.get('path', '')} · {data.get('replacements', 0)} remplacement(s)"
                                f" · +{added}/-{removed}"
                            ).strip()
                        else:
                            state = "créé" if data.get('created') else "modifié"
                            verified = " · vérifié" if data.get('verified') else ""
                            result_data['tool_result']['summary'] = f"{data.get('path', '')} · {state}{verified}".strip(" ·")
                    elif tool_name == 'write_files':
                        files = data.get('files', []) if isinstance(data.get('files', []), list) else []
                        created = data.get('created', []) if isinstance(data.get('created', []), list) else []
                        updated = data.get('updated', []) if isinstance(data.get('updated', []), list) else []
                        preview_paths = [
                            str(item.get('path', '')).strip()
                            for item in files[:5]
                            if isinstance(item, dict) and item.get('path')
                        ]
                        preview = ", ".join(preview_paths)
                        if len(files) > len(preview_paths):
                            preview += f", +{len(files) - len(preview_paths)}"
                        counts = (
                            f"{len(created)} créé(s), {len(updated)} modifié(s)"
                            if created or updated
                            else f"{data.get('count', len(files))} fichier(s) écrit(s)"
                        )
                        result_data['tool_result']['count'] = data.get('count', len(files))
                        result_data['tool_result']['files'] = files[:30]
                        result_data['tool_result']['created'] = created[:30]
                        result_data['tool_result']['updated'] = updated[:30]
                        result_data['tool_result']['summary'] = f"{counts} · {preview}" if preview else counts
                    elif tool_name == 'delete_file':
                        result_data['tool_result']['path'] = data.get('path', '')
                        result_data['tool_result']['verified'] = data.get('verified', False)
                        verified = " · vérifié" if data.get('verified') else ""
                        result_data['tool_result']['summary'] = f"{data.get('path', '')} · supprimé{verified}".strip(" ·")
                    elif tool_name == 'clear_workspace':
                        deleted = data.get('deleted', []) if isinstance(data.get('deleted', []), list) else []
                        kept = data.get('kept', []) if isinstance(data.get('kept', []), list) else []
                        result_data['tool_result']['deleted'] = deleted[:30]
                        result_data['tool_result']['kept'] = kept[:30]
                        result_data['tool_result']['count'] = data.get('count', len(deleted))
                        result_data['tool_result']['summary'] = f"{data.get('count', len(deleted))} élément(s) supprimé(s)"
                    elif tool_name == 'bash':
                        result_data['tool_result']['output'] = data.get('output', '')[:2000]
                        result_data['tool_result']['return_code'] = data.get('return_code', -1)
                        result_data['tool_result']['summary'] = f"exit {data.get('return_code', -1)}"
                    elif tool_name == 'search':
                        result_data['tool_result']['results'] = data.get('results', [])[:20]
                        count = len(data.get('results', []) or [])
                        result_data['tool_result']['path'] = data.get('path', '')
                        result_data['tool_result']['summary'] = f"{count} résultat(s)"
                    elif tool_name == 'glob':
                        result_data['tool_result']['files'] = data.get('files', [])[:30]
                        result_data['tool_result']['path'] = data.get('path', '')
                        result_data['tool_result']['summary'] = f"{data.get('total', len(data.get('files', [])))} fichier(s)"
                    elif tool_name == 'web_search':
                        result_data['tool_result']['results'] = data.get('results', [])[:8]
                    elif tool_name == 'web_fetch':
                        result_data['tool_result']['summary'] = f"Page lue: {data.get('title', data.get('url', ''))}"
                        result_data['tool_result']['content'] = data.get('content', '')[:2000]
                    elif tool_name == 'delegate_subagent':
                        result_data['tool_result']['summary'] = f"Subagent {data.get('agent_type', '')}: {data.get('status', '')}"
                        result_data['tool_result']['files'] = [
                            item.get('path', '')
                            for item in data.get('files', [])[:8]
                            if isinstance(item, dict)
                        ]
                    elif tool_name == 'load_skill':
                        skill = data.get('skill', {})
                        result_data['tool_result']['summary'] = f"Skill chargé: {skill.get('id', '')}"
                    elif tool_name == 'open_workspace':
                        result_data['tool_result']['summary'] = f"Dossier ouvert: {data.get('path', workspace_path)}"
                    elif tool_name == 'write_todos':
                        todos = data.get('todos', []) if isinstance(data.get('todos', []), list) else []
                        result_data['tool_result']['todos'] = todos[:8]
                        result_data['tool_result']['counts'] = data.get('counts', {})
                        result_data['tool_result']['summary'] = data.get('summary') or f"{len(todos)} étape(s)"
                    elif tool_name == 'ask_clarification':
                        result_data['tool_result']['question'] = data.get('question', '')
                        result_data['tool_result']['options'] = data.get('options', [])[:4] if isinstance(data.get('options', []), list) else []
                        result_data['tool_result']['summary'] = data.get('question', '')

                yield f"data: {json.dumps(result_data)}\n\n"

                # Log erreur si échec
                if (
                    not result.get('success')
                    and result.get('error')
                    and not (permission_info and permission_info.get('requires_confirmation'))
                ):
                    print(f"[TERMINAL] Erreur: {result.get('error')} → IA va auto-corriger")
                    yield f"data: {json.dumps({'auto_correction': True, 'error': result.get('error')})}\n\n"

            elif event_type == 'approval_required':
                tool_name = event.get('tool_name', '')
                args = event.get('args', {}) or {}
                path = workspace_path if tool_name == 'open_workspace' else args.get(
                    'path',
                    args.get(
                        'pattern',
                        args.get(
                            'command',
                            args.get('query', args.get('url', args.get('skill_id', args.get('task', '')))),
                        ),
                    ),
                )
                if job_manager and terminal_job_id:
                    job_manager.update(
                        terminal_job_id,
                        status="running",
                        phase="approval_required",
                        progress=None,
                        message=f"Approval required: {tool_name}"[:160],
                    )
                print(f"[TERMINAL] Approval required: {tool_name}({path})")
                yield f"data: {json.dumps({'approval_required': {'action': tool_name, 'path': path, 'args': args, 'permission': event.get('permission', {}), 'reason': event.get('reason', '')}})}\n\n"

            elif event_type == 'done':
                token_stats = event.get('token_stats', {})
                print(f"[TERMINAL] Terminé - Tokens: {token_stats.get('total', 0)} (prompt: {token_stats.get('prompt_tokens', 0)}, completion: {token_stats.get('completion_tokens', 0)})")
                if job_manager and terminal_job_id:
                    job_manager.complete(
                        terminal_job_id,
                        message="Terminal request complete",
                        artifact={"token_stats": token_stats},
                    )
                yield f"data: {json.dumps({'done': True, 'token_stats': token_stats, 'full_response': event.get('full_response', ''), 'approval_required': event.get('approval_required', False)})}\n\n"
                return

            elif event_type == 'error':
                print(f"[TERMINAL] Erreur: {event.get('message', '')}")
                if job_manager and terminal_job_id:
                    job_manager.fail(terminal_job_id, event.get('message', 'Erreur inconnue'))
                yield f"data: {json.dumps({'error': event.get('message', 'Erreur inconnue'), 'done': True})}\n\n"
                return

        # Fallback si la boucle se termine sans event 'done'
        if job_manager and terminal_job_id:
            job_manager.complete(terminal_job_id, message="Terminal request complete")
        yield f"data: {json.dumps({'done': True})}\n\n"

    def generate():
        try:
            yield from _generate_terminal_events()
        finally:
            active_run_registry.release(terminal_run_key, terminal_run_owner)

    response = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )
    if job_manager and terminal_job_id:
        def _close_terminal_stream():
            job = job_manager.get(terminal_job_id)
            if job and job.get("status") not in {"done", "error", "cancelled"}:
                # Safety net for browser disconnects: durable job state and
                # resource leases must not remain active just because the SSE
                # client disappeared before the agent emitted a final event.
                job_manager.cancel(terminal_job_id, "Terminal stream closed")
            active_run_registry.release(terminal_run_key, terminal_run_owner)

        response.call_on_close(_close_terminal_stream)

    return response


# ========== WORKSPACE ENDPOINTS ==========

@terminal_bp.route('/workspace/list', methods=['POST'])
def workspace_list():
    """Liste les fichiers d'un workspace"""
    from core.workspace_tools import list_files
    try:
        data = request.json
        workspace_path = data.get('workspace_path', '')
        relative_path = data.get('path', '')

        if not workspace_path or not os.path.isdir(workspace_path):
            return jsonify({'success': False, 'error': 'Workspace invalide'}), 400

        result = list_files(workspace_path, relative_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@terminal_bp.route('/workspace/read', methods=['POST'])
def workspace_read():
    """Lit un fichier du workspace"""
    from core.workspace_tools import read_file
    try:
        data = request.json
        workspace_path = data.get('workspace_path', '')
        file_path = data.get('path', '')

        if not workspace_path or not os.path.isdir(workspace_path):
            return jsonify({'success': False, 'error': 'Workspace invalide'}), 400

        result = read_file(workspace_path, file_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@terminal_bp.route('/workspace/search', methods=['POST'])
def workspace_search():
    """Recherche dans les fichiers du workspace"""
    from core.workspace_tools import search_files
    try:
        data = request.json
        workspace_path = data.get('workspace_path', '')
        pattern = data.get('pattern', '')
        file_filter = data.get('file_filter', '*')

        if not workspace_path or not os.path.isdir(workspace_path):
            return jsonify({'success': False, 'error': 'Workspace invalide'}), 400

        result = search_files(workspace_path, pattern, file_filter)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@terminal_bp.route('/workspace/glob', methods=['POST'])
def workspace_glob():
    """Trouve des fichiers par pattern glob"""
    from core.workspace_tools import glob_files
    try:
        data = request.json
        workspace_path = data.get('workspace_path', '')
        pattern = data.get('pattern', '')

        if not workspace_path or not os.path.isdir(workspace_path):
            return jsonify({'success': False, 'error': 'Workspace invalide'}), 400

        result = glob_files(workspace_path, pattern)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@terminal_bp.route('/workspace/summary', methods=['POST'])
def workspace_summary():
    """Retourne un résumé du workspace"""
    from core.workspace_tools import get_workspace_summary
    try:
        data = request.json
        workspace_path = data.get('workspace_path', '')

        if not workspace_path or not os.path.isdir(workspace_path):
            return jsonify({'success': False, 'error': 'Workspace invalide'}), 400

        result = get_workspace_summary(workspace_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@terminal_bp.route('/workspace/validate', methods=['POST'])
def workspace_validate():
    """Valide un chemin de workspace"""
    try:
        data = request.json
        workspace_path = data.get('path', '')

        if not workspace_path:
            return jsonify({'valid': False, 'error': 'Chemin vide'})

        # Normaliser le chemin
        workspace_path = os.path.normpath(workspace_path)

        if not os.path.exists(workspace_path):
            return jsonify({'valid': False, 'error': 'Chemin inexistant'})

        if not os.path.isdir(workspace_path):
            return jsonify({'valid': False, 'error': 'Ce n\'est pas un dossier'})

        # Obtenir le nom du dossier
        name = os.path.basename(workspace_path)

        # Compter les fichiers
        try:
            file_count = sum(1 for _ in os.scandir(workspace_path) if _.is_file())
            dir_count = sum(1 for _ in os.scandir(workspace_path) if _.is_dir())
        except:
            file_count = 0
            dir_count = 0

        return jsonify({
            'valid': True,
            'path': workspace_path,
            'name': name,
            'file_count': file_count,
            'dir_count': dir_count
        })
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)})


@terminal_bp.route('/workspace/browse', methods=['POST'])
def workspace_browse():
    """Open a native folder picker on the local JoyBoy machine."""
    try:
        data = request.json or {}
        initial_dir = data.get('initial_dir') or os.path.expanduser('~')
        if not os.path.isdir(initial_dir):
            initial_dir = os.path.expanduser('~')

        selected = None
        picker_errors = []

        if platform.system().lower() == 'windows':
            try:
                encoded_initial = base64.b64encode(initial_dir.encode('utf-8')).decode('ascii')
                # Flask handles requests outside the UI thread, so tkinter can
                # fail silently on Windows. Launching a short STA PowerShell
                # process gives us a real native folder dialog, like Codex.
                script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$initial = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_initial}'))
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Ouvrir un projet JoyBoy'
$dialog.ShowNewFolderButton = $true
if ([System.IO.Directory]::Exists($initial)) {{
    $dialog.SelectedPath = $initial
}}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $dialog.SelectedPath
}} else {{
    Write-Output '__JOYBOY_CANCELLED__'
}}
"""
                result = subprocess.run(
                    ['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-Command', script],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                )
                if result.returncode == 0:
                    output = (result.stdout or '').strip().splitlines()
                    selected = output[-1].strip() if output else ''
                    if selected == '__JOYBOY_CANCELLED__':
                        return jsonify({'valid': False, 'cancelled': True})
                else:
                    picker_errors.append((result.stderr or result.stdout or 'PowerShell folder picker failed').strip())
            except Exception as exc:
                picker_errors.append(str(exc))

        if not selected:
            selected = _browse_with_tkinter(initial_dir, picker_errors)

        if selected == '__JOYBOY_CANCELLED__':
            return jsonify({'valid': False, 'cancelled': True})

        if not selected:
            details = '; '.join(error for error in picker_errors if error)
            return jsonify({
                'valid': False,
                'cancelled': False,
                'error': 'Impossible d’ouvrir le sélecteur de dossier.' + (f' Détail: {details}' if details else '')
            }), 500

        return jsonify(_workspace_payload(selected, cancelled=False))
    except Exception as e:
        return jsonify({'valid': False, 'cancelled': False, 'error': str(e)}), 500


def _browse_with_tkinter(initial_dir, picker_errors):
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        picker_errors.append(f'tkinter indisponible: {exc}')
        return None

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        root.update()
        try:
            selected = filedialog.askdirectory(
                parent=root,
                initialdir=initial_dir,
                title='Ouvrir un projet JoyBoy'
            )
        finally:
            root.destroy()
        return selected or '__JOYBOY_CANCELLED__'
    except Exception as exc:
        picker_errors.append(f'tkinter: {exc}')
        return None


def _workspace_payload(path, cancelled=False):
    workspace_path = os.path.normpath(path)
    if not os.path.isdir(workspace_path):
        return {'valid': False, 'cancelled': cancelled, 'error': 'Ce n\'est pas un dossier'}

    name = os.path.basename(workspace_path) or workspace_path
    try:
        file_count = sum(1 for entry in os.scandir(workspace_path) if entry.is_file())
        dir_count = sum(1 for entry in os.scandir(workspace_path) if entry.is_dir())
    except Exception:
        file_count = 0
        dir_count = 0

    return {
        'valid': True,
        'cancelled': cancelled,
        'path': workspace_path,
        'name': name,
        'file_count': file_count,
        'dir_count': dir_count
    }


@terminal_bp.route('/workspace/open', methods=['POST'])
def workspace_open():
    """Open a validated workspace folder in the local file explorer."""
    try:
        data = request.json or {}
        workspace_path = os.path.abspath(os.path.normpath(data.get('path') or ''))
        if not os.path.isdir(workspace_path):
            return jsonify({'success': False, 'error': 'Dossier introuvable ou invalide'}), 400

        system = platform.system().lower()
        if system == 'windows':
            os.startfile(workspace_path)  # type: ignore[attr-defined]
        elif system == 'darwin':
            subprocess.Popen(['open', workspace_path])
        else:
            subprocess.Popen(['xdg-open', workspace_path])

        return jsonify({'success': True, 'path': workspace_path})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@terminal_bp.route('/workspace/check-model', methods=['POST'])
def workspace_check_model():
    """Vérifie si le modèle supporte le function calling pour les workspaces"""
    from core.workspace_tools import is_model_tool_capable
    try:
        data = request.json
        model = data.get('model', '')

        capable = is_model_tool_capable(model)

        return jsonify({
            'success': True,
            'model': model,
            'tool_capable': capable,
            'message': 'Ce modèle supporte les outils workspace' if capable else 'Ce modèle ne supporte pas les outils workspace nativement'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
