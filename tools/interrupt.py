"""Per-agent interrupt signaling for all tools.

Each AIAgent owns a dedicated threading.Event stored in a ContextVar.
Tools call get_interrupt_event() / is_interrupted() which resolve to the
current agent's Event — so one agent's interrupt never affects another.

Usage in tools:
    from tools.interrupt import is_interrupted
    if is_interrupted():
        return {"output": "[interrupted]", "returncode": 130}
"""

import contextvars
import threading

_interrupt_event_var: contextvars.ContextVar[threading.Event] = contextvars.ContextVar(
    "_interrupt_event_var",
    default=None,
)


def install_interrupt_event(event: threading.Event) -> None:
    """Bind *event* as the interrupt signal for the current context.

    Called at the top of AIAgent.run_conversation() and by tests.
    """
    _interrupt_event_var.set(event)


def get_interrupt_event() -> threading.Event:
    """Return the interrupt Event for the current agent context.

    If no agent context has been installed (e.g. bare script), returns
    a fresh never-set Event so callers never crash on NoneType.
    """
    event = _interrupt_event_var.get(None)
    if event is None:
        return threading.Event()  # fail-safe: never-set Event
    return event


def set_interrupt(active: bool) -> None:
    """Called by the agent to signal or clear the interrupt."""
    event = _interrupt_event_var.get(None)
    if event is None:
        return
    if active:
        event.set()
    else:
        event.clear()


def is_interrupted() -> bool:
    """Check if an interrupt has been requested. Safe to call from any thread."""
    event = _interrupt_event_var.get(None)
    if event is None:
        return False
    return event.is_set()
