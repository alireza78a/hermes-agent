"""Test interrupt propagation from parent to child agents.

Reproduces the CLI scenario: user sends a message while delegate_task is
running, main thread calls parent.interrupt(), child should stop.
"""

import threading
import unittest
from unittest.mock import MagicMock

from tools.interrupt import install_interrupt_event


class TestInterruptPropagationToChild(unittest.TestCase):
    """Verify interrupt propagates from parent to child agent."""

    def setUp(self):
        self._event = threading.Event()
        install_interrupt_event(self._event)

    def tearDown(self):
        self._event.clear()

    def test_parent_interrupt_sets_child_flag(self):
        """When parent.interrupt() is called, child._interrupt_requested should be set."""
        from run_agent import AIAgent

        parent = AIAgent.__new__(AIAgent)
        parent._interrupt_event = threading.Event()
        parent._interrupt_requested = False
        parent._interrupt_message = None
        parent._active_children = []
        parent._active_children_lock = threading.Lock()
        parent.quiet_mode = True

        child = AIAgent.__new__(AIAgent)
        child._interrupt_event = threading.Event()
        child._interrupt_requested = False
        child._interrupt_message = None
        child._active_children = []
        child._active_children_lock = threading.Lock()
        child.quiet_mode = True

        parent._active_children.append(child)

        parent.interrupt("new user message")

        assert parent._interrupt_requested is True
        assert child._interrupt_requested is True
        assert child._interrupt_message == "new user message"

    def test_child_clear_interrupt_clears_own_event(self):
        """child.clear_interrupt() clears the child's own per-agent Event."""
        from run_agent import AIAgent

        child = AIAgent.__new__(AIAgent)
        child._interrupt_event = threading.Event()
        child._interrupt_requested = True
        child._interrupt_message = "msg"
        child.quiet_mode = True
        child._active_children = []
        child._active_children_lock = threading.Lock()

        child._interrupt_event.set()
        assert child._interrupt_event.is_set()

        child.clear_interrupt()
        assert child._interrupt_requested is False
        assert not child._interrupt_event.is_set()

    def test_interrupt_during_child_api_call_detected(self):
        """Interrupt set during _interruptible_api_call is detected promptly."""
        from run_agent import AIAgent

        child = AIAgent.__new__(AIAgent)
        child._interrupt_event = threading.Event()
        child._interrupt_requested = False
        child._interrupt_message = None
        child._active_children = []
        child._active_children_lock = threading.Lock()
        child.quiet_mode = True
        child.api_mode = "chat_completions"
        child.log_prefix = ""
        child._client_kwargs = {"api_key": "test", "base_url": "http://localhost:1234"}

        # Install the child's interrupt Event into the current thread's ContextVar
        # so _interruptible_api_call can see it.
        install_interrupt_event(child._interrupt_event)

        # Synchronization gates — no time.sleep ordering
        api_call_entered = threading.Event()
        api_call_release = threading.Event()

        mock_client = MagicMock()
        def blocking_api_call(**kwargs):
            api_call_entered.set()
            api_call_release.wait(timeout=10)
            return MagicMock()
        mock_client.chat.completions.create = blocking_api_call
        mock_client.close = MagicMock()
        child.client = mock_client

        def set_interrupt_when_ready():
            api_call_entered.wait(timeout=5)
            child.interrupt("stop!")
            api_call_release.set()  # unblock mock so thread can clean up

        t = threading.Thread(target=set_interrupt_when_ready, daemon=True)
        t.start()

        try:
            child._interruptible_api_call({"model": "test", "messages": []})
            self.fail("Should have raised InterruptedError")
        except InterruptedError:
            pass  # expected
        finally:
            api_call_release.set()
            t.join(timeout=2)
            mock_client.close.assert_called()

    def test_concurrent_interrupt_propagation(self):
        """Simulates exact CLI flow: parent runs delegate in thread, main thread interrupts."""
        from run_agent import AIAgent

        parent = AIAgent.__new__(AIAgent)
        parent._interrupt_event = threading.Event()
        parent._interrupt_requested = False
        parent._interrupt_message = None
        parent._active_children = []
        parent._active_children_lock = threading.Lock()
        parent.quiet_mode = True

        child = AIAgent.__new__(AIAgent)
        child._interrupt_event = threading.Event()
        child._interrupt_requested = False
        child._interrupt_message = None
        child._active_children = []
        child._active_children_lock = threading.Lock()
        child.quiet_mode = True

        parent._active_children.append(child)

        # Synchronization gate — no time.sleep ordering
        child_loop_entered = threading.Event()
        child_detected = threading.Event()

        def simulate_child_loop():
            child_loop_entered.set()
            while not child._interrupt_requested:
                child._interrupt_event.wait(timeout=0.05)
            child_detected.set()

        child_thread = threading.Thread(target=simulate_child_loop, daemon=True)
        child_thread.start()

        child_loop_entered.wait(timeout=5)
        parent.interrupt("user typed something new")

        detected = child_detected.wait(timeout=1.0)
        assert detected, "Child never detected the interrupt!"
        child_thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
