"""App-server request/response boundaries with a real JSONL subprocess fixture."""
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import subprocess
import sys
import os

from core.bridge.codex import CodexClient


class CodexProtocolTests(unittest.TestCase):
    def make_client(self, status="completed"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        program = root / "codex-fixture"
        program.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''
            import json,sys
            def emit(value):
                print(json.dumps(value),flush=True)
            for line in sys.stdin:
                request=json.loads(line)
                if 'method' not in request:
                    continue
                method=request['method']
                if method=='initialized': continue
                if method=='initialize': result={}
                elif method=='account/read': result={'account':{'type':'chatgpt','planType':'example','email':'must-not-escape@example.test'}}
                elif method=='model/list': result={'data':[{'id':'fixture-model','model':'fixture-model','isDefault':True}], 'nextCursor':None}
                elif method=='config/read': result={'config':{'mcp_servers':{'inherited':{'enabled':True}},'plugins':{'example-plugin':{'enabled':True}}}}
                elif method=='mcpServerStatus/list': result={'data':[], 'nextCursor':None}
                elif method in ('thread/start','thread/resume'):
                    assert request['params']['sandbox']=='read-only'
                    assert request['params']['approvalPolicy']=='never'
                    assert request['params']['config']['mcp_servers']['inherited']['enabled'] is False
                    assert request['params']['config']['plugins']['example-plugin']['enabled'] is False
                    assert request['params']['config']['features']['apps'] is False
                    result={'thread':{'id':'fixture-thread'}}
                elif method=='turn/start':
                    assert request['params']['sandboxPolicy']=={'type':'readOnly','networkAccess':False}
                    # A valid notification can precede the RPC response.
                    emit({'method':'item/agentMessage/delta','params':{'threadId':'fixture-thread','turnId':'fixture-turn','delta':'Hello'}})
                    emit({'method':'item/completed','params':{'threadId':'fixture-thread','turnId':'fixture-turn','item':{'id':'message','type':'agentMessage','text':'Hello'}}})
                    result={'turn':{'id':'fixture-turn'}}
                else: result={}
                emit({'id':request['id'],'result':result})
                if method=='turn/start':
                    emit({'method':'turn/completed','params':{'threadId':'fixture-thread','turn':{'id':'fixture-turn','status':STATUS}}})
        ''').replace("STATUS", repr(status)), encoding="utf-8")
        real_popen = subprocess.Popen
        def start_fixture(*args, **kwargs):
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            return real_popen([sys.executable, str(program)], **kwargs)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "image-key-placeholder"}):
            with patch("core.bridge.codex.subprocess.Popen", side_effect=start_fixture):
                client = CodexClient(root, executable=str(program))
        self.addCleanup(client.close)
        return client

    def test_model_catalog_account_redaction_and_early_events(self):
        client = self.make_client()
        status = client.status()
        self.assertEqual(status["auth_type"], "chatgpt")
        self.assertNotIn("email", str(status))
        self.assertEqual(status["models"][0]["id"], "fixture-model")
        result = client.chat("hello")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "Hello")

    def test_failed_or_interrupted_turn_is_never_success(self):
        for status in ("failed", "interrupted"):
            client = self.make_client(status)
            with self.assertRaisesRegex(RuntimeError, status):
                client.chat("hello")

    def test_resume_and_vision_attachment_protocol(self):
        client = self.make_client()
        result = client.chat("hello", thread_id="fixture-thread", image_paths=["/example/image.png"])
        self.assertEqual(result["thread_id"], "fixture-thread")


if __name__ == "__main__":
    unittest.main()
