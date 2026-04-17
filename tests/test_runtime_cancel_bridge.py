from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from web.routes.runtime import _bridge_runtime_cancel_to_generation_flags


class RuntimeCancelBridgeTest(unittest.TestCase):
    def test_unrelated_runtime_cancel_does_not_set_global_generation_cancel(self) -> None:
        app_module = SimpleNamespace(
            generation_cancelled=False,
            active_generations={"active-gen": {"cancelled": False}},
            generations_lock=threading.Lock(),
        )

        bridged = _bridge_runtime_cancel_to_generation_flags(app_module, "old-orphan-job")

        self.assertFalse(bridged)
        self.assertFalse(app_module.generation_cancelled)
        self.assertFalse(app_module.active_generations["active-gen"]["cancelled"])

    def test_matching_runtime_cancel_marks_only_that_generation(self) -> None:
        app_module = SimpleNamespace(
            generation_cancelled=False,
            active_generations={
                "active-gen": {"cancelled": False},
                "other-gen": {"cancelled": False},
            },
            generations_lock=threading.Lock(),
        )

        bridged = _bridge_runtime_cancel_to_generation_flags(app_module, "active-gen")

        self.assertTrue(bridged)
        self.assertFalse(app_module.generation_cancelled)
        self.assertTrue(app_module.active_generations["active-gen"]["cancelled"])
        self.assertFalse(app_module.active_generations["other-gen"]["cancelled"])


if __name__ == "__main__":
    unittest.main()
