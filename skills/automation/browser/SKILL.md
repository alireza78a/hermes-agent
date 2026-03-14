---
name: browser
description: Automate web browsers via Browserbase cloud + browser tools.
version: 1.0.0
author: community
license: MIT
metadata:
  hermes:
    tags: [Browser, Automation, Browserbase, Web, Scraping]
    homepage: https://www.browserbase.com
---

# Browser Automation (Browserbase)

Hermes browser tools run a real Chrome instance in the **Browserbase cloud** — no local browser needed. Basic stealth (fingerprint randomization, CAPTCHA solving) and residential proxies are always active.

## Prerequisites

1. **Browserbase account** — sign up at [browserbase.com](https://www.browserbase.com) and create a project.

2. **Environment variables** in `~/.hermes/.env`:
   ```
   BROWSERBASE_API_KEY=your_api_key
   BROWSERBASE_PROJECT_ID=your_project_id
   ```

3. **agent-browser CLI** (Node.js):
   ```bash
   # Install globally
   npm install -g agent-browser

   # Or install locally in the hermes-agent repo root
   npm install
   ```
   Verify: `agent-browser --version`

## Available Tools

| Tool | Purpose |
|---|---|
| `browser_navigate` | Go to a URL; creates a session if none exists |
| `browser_snapshot` | Get accessibility tree of current page with `@eN` refs |
| `browser_click` | Click an element by its `@eN` ref |
| `browser_type` | Type into an input by its `@eN` ref (clears field first) |
| `browser_scroll` | Scroll up or down |
| `browser_back` | Navigate back in browser history |
| `browser_press` | Press a keyboard key (Enter, Tab, Escape, ArrowDown, etc.) |
| `browser_get_images` | List all images on the page with URLs and alt text |
| `browser_vision` | Screenshot + vision-AI analysis for visual understanding |
| `browser_close` | **Close session and release Browserbase quota** |

## The @eN Ref Workflow (Core Pattern)

**Always snapshot before interacting.** The accessibility tree assigns numbered refs (`@e1`, `@e2`, ...) to every interactive element. These refs are the only reliable way to target elements.

```
1. browser_navigate(url)      → loads the page
2. browser_snapshot()         → get the accessibility tree with @eN refs
3. browser_click("@e5")       → click using a ref from the snapshot
   OR browser_type("@e3", "hello")
4. browser_snapshot()         → re-snapshot after any interaction to get updated refs
5. ... repeat as needed ...
6. browser_close()            → ALWAYS call this at the end
```

**Refs are not stable across snapshots.** After any click, type, or navigation, call `browser_snapshot()` again before the next interaction — refs may have changed.

## Always Call browser_close

Every open session consumes Browserbase quota. **Always call `browser_close()` when done**, even if the task failed. Wrap multi-step workflows in a try/finally pattern mentally — if anything goes wrong mid-task, still close.

Session inactivity timeout is 5 minutes (`BROWSER_INACTIVITY_TIMEOUT`). Idle sessions are auto-closed, but don't rely on this — explicit close is faster and frees quota immediately.

## Common Workflows

### Navigate and Fill a Form

```
1. browser_navigate("https://example.com/contact")
2. browser_snapshot()
   → look for input refs: "@e3 textbox 'Name'", "@e4 textbox 'Email'", "@e7 button 'Submit'"
3. browser_type("@e3", "Alice Smith")
4. browser_type("@e4", "alice@example.com")
5. browser_click("@e7")
6. browser_snapshot()   → verify confirmation message appeared
7. browser_close()
```

### Log In to a Site

```
1. browser_navigate("https://example.com/login")
2. browser_snapshot()
3. browser_type("@eN", "your@email.com")    ← ref for email input
4. browser_type("@eN", "yourpassword")       ← ref for password input
5. browser_press("Enter")                    ← or browser_click on the login button ref
6. browser_snapshot()                        ← verify you're now logged in
7. ... continue your task ...
8. browser_close()
```

If the login page has a CAPTCHA, Browserbase's built-in solver handles it automatically — just proceed normally. If it fails, use `browser_vision("Is there a CAPTCHA? What does it look like?")` to diagnose.

### Scrape Dynamic Content

For content that requires JavaScript execution or user interaction to appear (infinite scroll, tabs, accordions):

```
1. browser_navigate("https://example.com/data")
2. browser_snapshot()              → initial content
3. browser_scroll("down")         → trigger lazy-load
4. browser_snapshot()              → more content now visible
5. browser_scroll("down")         → repeat as needed
6. browser_snapshot(full=True)    → get complete page text for extraction
7. browser_close()
```

Use `browser_snapshot(full=True)` when you need all text content, not just interactive elements.

### Handle Dropdowns and Selects

```
1. browser_snapshot()
   → find the dropdown ref, e.g. "@e8 combobox 'Country'"
2. browser_click("@e8")           → open the dropdown
3. browser_snapshot()             → options now visible with their refs
4. browser_click("@e15")          → click the desired option ref
```

For `<select>` elements some sites use `browser_type` with the option value rather than clicking.

### Click Through Pagination

```
1. browser_navigate("https://example.com/results")
2. browser_snapshot()
3. ... extract page 1 content ...
4. browser_snapshot()
   → find "Next" button, e.g. "@e22 link 'Next'"
5. browser_click("@e22")
6. browser_snapshot()
7. ... extract page 2 content ...
8. browser_close()
```

### Download / Find File URLs

```
1. browser_navigate("https://example.com/reports")
2. browser_snapshot()
   → find download link ref, e.g. "@e9 link 'Download PDF'"
3. browser_get_images()           → also check for image URLs if needed
4. browser_click("@e9")           → triggers download in the Browserbase session
   Note: file downloads happen in the cloud — use web_extract or terminal/curl
   to actually retrieve the file once you have the direct URL
5. browser_close()
```

## Vision Fallback Pattern

Use `browser_vision` when the accessibility tree is ambiguous, empty, or the page relies heavily on visual layout:

```python
# Accessibility tree unclear about what's on screen:
browser_vision("What is shown on the current page? Is there a login form, an error, or a dashboard?")

# Verify a visual action worked:
browser_click("@e5")
browser_vision("Did the modal close successfully? What is visible now?")

# Diagnose a stuck flow:
browser_vision("Is there a CAPTCHA, cookie banner, or modal blocking the page?")
```

Vision uses a vision-capable auxiliary model (configured separately). Fall back to it freely — it's cheaper than getting stuck in a broken loop.

## Pitfalls and Gotchas

### Never Click Without Snapshotting First
Refs (`@eN`) don't exist until you call `browser_snapshot()`. Calling `browser_click("@e5")` without a preceding snapshot will fail with a "ref not found" error.

### Re-Snapshot After Every Interaction
After `browser_click`, `browser_type`, `browser_press`, or `browser_navigate`, the page changes. Old refs are stale. Always call `browser_snapshot()` before the next interaction.

### Session Quota Limits
Each Browserbase account has a concurrent session limit. If you hit it, `browser_navigate` fails with a quota error. Always `browser_close()` between unrelated tasks. If you have multiple tasks, use different `task_id` values to keep sessions isolated.

### Prefer web_search / web_extract for Simple Retrieval
Browser tools are for **interaction** (forms, login, dynamic content). For reading a public static page, `web_extract` is faster and free. Only spin up a browser session when you actually need to click, scroll, or fill things in.

### Snapshots Over 8000 Chars Are Auto-Summarized
Very large pages get their accessibility tree truncated or LLM-summarized. If you need the raw full content, use `browser_snapshot(full=True)` or `browser_get_images()` for image-heavy pages.

### Cookie Banners and Modals
If a cookie consent banner or modal appears after navigation, it will block the underlying page refs. Dismiss it first:
```
browser_snapshot()
→ find "Accept" or "Dismiss" button ref
browser_click("@eN")
browser_snapshot()   → now the real page is accessible
```

### CAPTCHA Handling
Browserbase's basic stealth solves most visual CAPTCHAs automatically. If a CAPTCHA persists:
1. `browser_vision("Describe the CAPTCHA on screen")` to diagnose
2. Enable advanced stealth: `BROWSERBASE_ADVANCED_STEALTH=true` (requires Scale Plan)
3. If it's a Cloudflare or hCaptcha challenge, advanced stealth is the only reliable option

## Environment Tuning

```bash
# Disable proxies (faster, less anti-bot protection)
BROWSERBASE_PROXIES=false

# Enable advanced stealth (Scale Plan required)
BROWSERBASE_ADVANCED_STEALTH=true

# Extend session timeout to 30 minutes (milliseconds)
BROWSERBASE_SESSION_TIMEOUT=1800000

# Extend inactivity auto-close timeout (seconds, default 300)
BROWSER_INACTIVITY_TIMEOUT=600
```
