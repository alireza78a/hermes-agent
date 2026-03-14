# CODE REVIEW REPORT

- Verdict: NEEDS REVISION
- Blockers: 2 | High: 4 | Medium: 4

---

## Blockers

### 1. `flush_memories` can strip legitimate conversation messages on API failure

**File:** `/Users/alireza/hermes-agent/run_agent.py`, lines 2614-2622

```python
finally:
    # Strip flush artifacts: remove everything from the flush message onward.
    while messages and messages[-1].get("_flush_sentinel") != _sentinel:
        messages.pop()
        if not messages:
            break
    if messages and messages[-1].get("_flush_sentinel") == _sentinel:
        messages.pop()
```

**Bug:** If the flush API call succeeds and returns tool calls that get appended as tool-result messages to `messages`, those are correctly cleaned up. However, if the `_sentinel` marker itself was never appended (e.g., `messages` is a separate copy and the `flush_msg` append at line 2520 failed silently, or an exception occurs between `messages.append(flush_msg)` and the try block), the `while` loop will pop ALL messages from the list until it is empty, because it will never find the sentinel. This destroys the entire conversation history.

**Concrete failure mode:** The messages list is passed by reference from `_compress_context` and ultimately from the main `run_conversation` loop. If for any reason the sentinel is not found (e.g. a concurrent interrupt modifies the list between the append and the finally block), every message gets popped. The conversation is irrecoverably lost in-memory.

**Fix:** Before the loop, verify the sentinel exists in the list. If it is not found, skip the cleanup entirely:

```python
finally:
    sentinel_idx = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("_flush_sentinel") == _sentinel:
            sentinel_idx = idx
            break
    if sentinel_idx is not None:
        del messages[sentinel_idx:]
```

---

### 2. RotatingFileHandler added to root logger on every `AIAgent.__init__`, causing handler leak

**File:** `/Users/alireza/hermes-agent/run_agent.py`, lines 307-314

```python
_error_file_handler = RotatingFileHandler(
    _error_log_path, maxBytes=2 * 1024 * 1024, backupCount=2,
)
_error_file_handler.setLevel(logging.WARNING)
_error_file_handler.setFormatter(RedactingFormatter(
    '%(asctime)s %(levelname)s %(name)s: %(message)s',
))
logging.getLogger().addHandler(_error_file_handler)
```

**Bug:** Every time a new `AIAgent` is instantiated, a new `RotatingFileHandler` is added to the root logger. The gateway creates a fresh `AIAgent` per message. In a long-running gateway process handling hundreds of messages, this accumulates hundreds of file handlers, each holding an open file descriptor to `errors.log`. Every subsequent log message is written N times (once per handler). This is a file descriptor leak and a performance degradation that grows linearly with usage.

**Concrete failure mode:** After a few hundred agent instantiations in a gateway/daemon process, the process exhausts file descriptors (OS limit, typically 1024) and starts failing with `OSError: [Errno 24] Too many open files`. Even before hitting that limit, log output volume multiplies with each new agent.

**Fix:** Guard the handler registration. Either use a module-level flag, or check if the root logger already has a handler writing to that path:

```python
_root = logging.getLogger()
_already_has_error_handler = any(
    isinstance(h, RotatingFileHandler) and getattr(h, 'baseFilename', '').endswith('errors.log')
    for h in _root.handlers
)
if not _already_has_error_handler:
    _error_file_handler = RotatingFileHandler(...)
    ...
    _root.addHandler(_error_file_handler)
```

---

## High Priority

### 3. Trajectory conversion indexes tool responses by position, not by `tool_call_id` -- mismatches when tool results are reordered or missing

**File:** `/Users/alireza/hermes-agent/run_agent.py`, line 1031

```python
"name": msg["tool_calls"][len(tool_responses)]["function"]["name"] if len(tool_responses) < len(msg["tool_calls"]) else "unknown",
```

**Bug:** This code assumes tool-result messages appear in the exact same order as the `tool_calls` array in the preceding assistant message. It uses `len(tool_responses)` as a positional index into `msg["tool_calls"]`. However, after context compression, interrupt-based tool skipping, or error recovery, tool results can be reordered, some can be missing, or extra stub results can be injected. When the position does not match, the wrong tool name is associated with the wrong result in the trajectory output.

**Concrete failure mode:** Saved trajectories (used for training data) contain incorrect tool name-to-result mappings, corrupting training data silently.

**Fix:** Look up the tool name by matching `tool_call_id` from the tool result message against the `id` fields in `msg["tool_calls"]`, rather than relying on positional indexing:

```python
tc_id = tool_msg.get("tool_call_id", "")
tool_name = "unknown"
for tc in msg["tool_calls"]:
    if tc.get("id") == tc_id or tc.get("call_id") == tc_id:
        tool_name = tc["function"]["name"]
        break
```

---

### 4. `_hydrate_todo_store` unconditionally calls `_set_interrupt(False)` -- clears a legitimate pending interrupt

**File:** `/Users/alireza/hermes-agent/run_agent.py`, line 1311

```python
    if last_todo_response:
        self._todo_store.write(last_todo_response, merge=False)
        if not self.quiet_mode:
            print(f"{self.log_prefix}... Restored {len(last_todo_response)} todo item(s) from history")
    _set_interrupt(False)  # <--- Always runs
```

**Bug:** `_set_interrupt(False)` is called unconditionally at the end of `_hydrate_todo_store`, regardless of whether there was actually an interrupt. This method is called from `run_conversation` (line 3084) which is invoked while the agent could have a pending interrupt from a different thread. Clearing the global interrupt flag here means a legitimately requested interrupt (e.g., user sent a new message while the agent was loading) is silently discarded.

**Concrete failure mode:** In the gateway, a user sends a new message while a previous `run_conversation` is starting up. The interrupt is set, but `_hydrate_todo_store` clears it. The agent continues the stale conversation instead of breaking out to handle the new message.

**Fix:** Remove the `_set_interrupt(False)` call from `_hydrate_todo_store`. The interrupt state is already managed by `clear_interrupt()` at line 3240 (`self.clear_interrupt()`) at the appropriate place in `run_conversation`.

---

### 5. `iteration_budget` is reset every turn, defeating shared budget with subagents

**File:** `/Users/alireza/hermes-agent/run_agent.py`, line 3075

```python
self.iteration_budget = IterationBudget(self.max_iterations)
```

**Bug:** At the start of every `run_conversation` call, the iteration budget is replaced with a fresh `IterationBudget(self.max_iterations)`. The class docstring and `__init__` parameter say the budget is "shared with subagents" -- a parent creates an `IterationBudget` and passes it to children via the `iteration_budget` parameter so they share a single cap. However, this line replaces it unconditionally, so if a child agent was given a parent's budget object, the parent loses any usage the child consumed: the next parent turn creates a brand new budget with full capacity. The shared-budget feature is thus broken for multi-turn conversations.

**Concrete failure mode:** In a multi-turn CLI session, a subagent delegation consumes 30 of 90 iterations. On the next user message, the parent resets to a fresh 90-iteration budget. The total budget of 90 is effectively ignored -- the system can consume 90 iterations per user turn indefinitely.

**Fix:** Only create a new budget if one was not externally provided:

```python
if iteration_budget is None:
    # Only reset for top-level agents on new turns
    self.iteration_budget = IterationBudget(self.max_iterations)
# else: keep the shared budget from parent
```

Or better: never reset the budget in `run_conversation`. If the intent is per-turn budgets, document that explicitly and don't accept `iteration_budget` in `__init__`.

---

### 6. Context compressor `_sanitize_tool_pairs` inserts stub results after assistant messages, but can insert them after the WRONG assistant message

**File:** `/Users/alireza/hermes-agent/agent/context_compressor.py`, lines 255-267

```python
patched: List[Dict[str, Any]] = []
for msg in messages:
    patched.append(msg)
    if msg.get("role") == "assistant":
        for tc in msg.get("tool_calls") or []:
            cid = self._get_tool_call_id(tc)
            if cid in missing_results:
                patched.append({
                    "role": "tool",
                    "content": "[Result from earlier conversation ...]",
                    "tool_call_id": cid,
                })
messages = patched
```

**Bug:** The stub results are inserted immediately after each assistant message that contains a tool_call with a missing result. This is correct when there is only one such assistant message. However, if an assistant message with tool_calls is followed by another assistant message with tool_calls (both missing results), the stubs for the first assistant message are inserted between them. This is valid. The real problem is: after compression, an assistant message might appear later in the list (e.g., in the "tail" section), and its original tool results were in the summarized middle. The stubs are inserted right after that assistant message, which is correct placement. But if the same `call_id` appears in both the head and tail (unlikely but possible after copy/paste in history or ID collisions from providers returning short IDs), the stub would be placed after the first occurrence, not the correct one. More importantly: if the assistant message at position X has tool_calls A and B, and B's result exists at position X+2 but A's result was dropped, the code inserts A's stub at X+1. Then B's existing result is at X+3. But the existing result was already counted in `result_call_ids`, so B is NOT in `missing_results`. This is actually correct. After deeper analysis, this particular method is sound for the single-occurrence case.

No action needed on this one after deeper analysis. Removing from the report count.

---

## Medium Priority

### 7. `_convert_to_trajectory_format` can crash with `AttributeError` when `tool_content` is `None`

**File:** `/Users/alireza/hermes-agent/run_agent.py`, line 1024

```python
tool_content = tool_msg["content"]
try:
    if tool_content.strip().startswith(("{", "[")):
```

**Bug:** If `tool_msg["content"]` is `None` (which can happen when a tool returns None or when an error path sets content to None), calling `.strip()` on it raises `AttributeError`. While the `except` clause catches `AttributeError`, this masks a real `None` content issue: `json.dumps` at line 1029 will serialize the None as `null`, which is probably fine. But the `AttributeError` catch is doing the right thing accidentally. However, `tool_msg["content"]` could also be missing entirely (KeyError), which is NOT caught.

**Fix:** Use `tool_content = tool_msg.get("content") or ""` for safety.

---

### 8. `auxiliary_is_nous` is a module-level global that is set but never reset -- stale state across agent instances

**File:** `/Users/alireza/hermes-agent/agent/auxiliary_client.py`, line 66

```python
auxiliary_is_nous: bool = False
```

And at line 429:

```python
def _try_nous() -> Tuple[Optional[OpenAI], Optional[str]]:
    nous = _read_nous_auth()
    if not nous:
        return None, None
    global auxiliary_is_nous
    auxiliary_is_nous = True
```

**Bug:** Once `_try_nous()` is called and succeeds, `auxiliary_is_nous` is set to `True` and never reset to `False`. If Nous auth is later revoked (e.g., token expires, user switches providers), subsequent calls to `get_auxiliary_extra_body()` will still return Nous-specific `tags` in `extra_body`, even when the auxiliary client is now backed by OpenRouter or another provider. This sends invalid/unexpected fields to non-Nous providers.

**Concrete failure mode:** Some providers reject unknown fields in `extra_body`, causing API errors. Even when not rejected, the Nous product attribution tag `"product=hermes-agent"` is sent to non-Nous providers.

**Fix:** Reset `auxiliary_is_nous = False` at the beginning of `_resolve_auto()` and `_resolve_forced_provider()`, so it reflects the current resolution, not a stale one.

---

### 9. `_compress_context` mutates `messages` in-place via `flush_memories` before returning a new compressed list

**File:** `/Users/alireza/hermes-agent/run_agent.py`, lines 2631-2633

```python
def _compress_context(self, messages: list, system_message: str, *, approx_tokens: int = None) -> tuple:
    self.flush_memories(messages, min_turns=0)
    compressed = self.context_compressor.compress(messages, current_tokens=approx_tokens)
```

**Bug:** `flush_memories` appends a flush message to `messages`, makes an API call, and then strips the flush artifacts in its `finally` block. However, if the flush API call fails in a way that adds unexpected messages (e.g., assistant response + tool results), and the finally-block cleanup has the sentinel bug described in Blocker #1, `messages` can be left in a corrupted state. The `compress()` call then operates on a corrupted `messages` list, producing a corrupted compressed output.

Even without the sentinel bug: `flush_memories` mutates `messages` in place (append + pop), but `compress()` operates on the same list. If an exception in `compress()` after `flush_memories` succeeds leaves messages in a half-mutated state, the caller (the main loop) now has a messages list that had flush artifacts transiently added and removed, but any exception leaves an inconsistent state.

**Fix:** Pass a copy of messages to `flush_memories`, or restructure so that `flush_memories` does not mutate the messages list that is about to be compressed.

---

### 10. Race condition in `_interruptible_api_call` -- `client.close()` while background thread is using it

**File:** `/Users/alireza/hermes-agent/run_agent.py`, lines 2157-2166

```python
if self._interrupt_requested:
    # Force-close the HTTP connection to stop token generation
    try:
        self.client.close()
    except Exception:
        pass
    # Rebuild the client for future calls (cheap, no network)
    try:
        self.client = OpenAI(**self._client_kwargs)
    except Exception:
        pass
    raise InterruptedError("Agent interrupted during API call")
```

**Bug:** The main thread calls `self.client.close()` while the background thread `_call()` (line 2148) is still actively using the same `self.client` object for an in-flight request. After closing, the main thread immediately reassigns `self.client` to a new instance. Meanwhile, the background thread may still be referencing the old (now closed) client and could raise an unexpected exception. That exception is stored in `result["error"]` but is never checked because the main thread already raised `InterruptedError`.

This is mostly safe because the background thread is a daemon thread and the `InterruptedError` short-circuits the caller. However, the background thread can continue running after the interrupt (daemon threads are not immediately killed), potentially accessing the old closed client and producing log noise or interfering with the new client in edge cases where `_call()` modifies shared state (e.g., updating `result["response"]` after the main thread already moved on).

**Fix:** After `raise InterruptedError`, the thread is orphaned. This is generally acceptable for a daemon thread, but consider setting a flag that `_call()` checks before writing to `result`, to avoid late-arriving results overwriting state on a future call if the same `result` dict is somehow reused.

---

## Good Practices

- The `_sanitize_tool_pairs` method in `context_compressor.py` is well-designed: it handles both orphaned tool results and missing tool results symmetrically, which is exactly what is needed after summarization drops middle turns.
- The context probing mechanism (stepping down through `CONTEXT_PROBE_TIERS` and caching discovered limits) is a robust way to handle unknown model context lengths without requiring manual configuration.
- The interrupt mechanism with small sleep increments (0.2s polling) during retry waits is a good pattern for responsive interruption.
- The sentinel-based cleanup in `flush_memories` is a good idea in principle (avoiding identity-based checks that could break with list copies), even though the implementation has the edge case noted above.
- The `_build_assistant_message` method properly normalizes both SimpleNamespace and dict-style tool calls into a consistent format, handling multiple ID schemes (call_id, response_item_id, fc_ prefix).
- The prompt injection scanner in `prompt_builder.py` (`_scan_context_content`) is a good defense-in-depth measure for context files.
