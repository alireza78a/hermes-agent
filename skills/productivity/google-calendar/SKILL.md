---
name: google-calendar
description: Manage Google Calendar events via gcalcli CLI.
version: 1.0.0
author: community
license: MIT
metadata:
  hermes:
    tags: [Productivity, Calendar, Google, Scheduling]
    homepage: https://github.com/insanum/gcalcli
---

# Google Calendar (gcalcli)

`gcalcli` is a CLI client for Google Calendar. Use it to list, search, add, edit, and delete events without opening a browser.

## Prerequisites

1. Install gcalcli:
   ```bash
   pip install gcalcli
   ```

2. Authenticate (one-time, interactive — requires a browser):
   ```bash
   gcalcli init
   ```
   This opens an OAuth flow. Credentials are cached in `~/.gcalcli_oauth`. After initial setup, all commands run non-interactively.

3. Verify:
   ```bash
   gcalcli list
   ```

## Hermes Integration Notes

- All commands after initial `gcalcli init` are fully non-interactive and work directly via `terminal()`.
- Use `--nocolor` to avoid ANSI escape codes in output.
- Use `--details` flags to get structured info for parsing.
- Dates accept natural language (`today`, `tomorrow`, `next monday`) or ISO format (`2025-03-10`).
- `gcalcli init` requires interactive OAuth — use `terminal(command="gcalcli init", pty=true)` if credentials aren't set up yet.
- To target a specific calendar, use `--cal "Calendar Name"` (partial match, case-insensitive).

## Common Operations

### List Calendars

```bash
gcalcli list --nocolor
```

### View Today's Events

```bash
gcalcli agenda today tomorrow --nocolor
```

### View a Date Range

```bash
gcalcli agenda 2025-03-10 2025-03-17 --nocolor
```

### Weekly View

```bash
gcalcli calw --nocolor
```

### Monthly View

```bash
gcalcli calm --nocolor
```

### Search Events

```bash
gcalcli search "meeting" --nocolor
```

Search within a date range:

```bash
gcalcli search "standup" 2025-03-01 2025-03-31 --nocolor
```

### Add a Quick Event

```bash
gcalcli quick "Lunch with Alice tomorrow at 1pm"
```

### Add a Detailed Event

```bash
gcalcli add \
  --title "Team Sync" \
  --when "2025-03-12 10:00" \
  --duration 60 \
  --description "Weekly team sync meeting" \
  --where "Zoom" \
  --cal "Work" \
  --noprompt
```

`--noprompt` skips the interactive confirmation — always include this in Hermes.

### Add an All-Day Event

```bash
gcalcli add \
  --title "Company Holiday" \
  --when "2025-03-17" \
  --allday \
  --noprompt
```

### Edit an Event

gcalcli doesn't support direct non-interactive edits. To update an event:
1. Delete the old event (see below)
2. Re-add it with corrected details using `gcalcli add --noprompt`

### Delete an Event

```bash
gcalcli delete "Team Sync" --noprompt
```

Delete within a date range to avoid deleting recurring instances unintentionally:

```bash
gcalcli delete "Team Sync" 2025-03-12 2025-03-13 --noprompt
```

### Import from iCalendar File

```bash
gcalcli import meeting.ics --noprompt
```

### Export Events as CSV

gcalcli doesn't have a direct CSV export, but agenda output can be redirected:

```bash
gcalcli agenda 2025-03-01 2025-04-01 --nocolor --tsv > events.tsv
```

`--tsv` outputs tab-separated values: `start_date`, `start_time`, `end_date`, `end_time`, `title`.

### Reminders

Add an event with a reminder:

```bash
gcalcli add \
  --title "Call dentist" \
  --when "2025-03-15 09:00" \
  --duration 15 \
  --reminder 30 \
  --noprompt
```

`--reminder` accepts minutes before the event.

## Multiple Accounts

gcalcli supports multiple Google accounts via config profiles. Store configs in separate files and point to them with `--configFolder`:

```bash
gcalcli --configFolder ~/.gcalcli_work agenda today tomorrow
gcalcli --configFolder ~/.gcalcli_personal agenda today tomorrow
```

## Debugging

```bash
gcalcli --debug agenda today tomorrow
```

## Tips

- `--noprompt` is essential for all write operations in Hermes — without it, gcalcli waits for `[Y/n]` confirmation and hangs.
- Event titles in `delete` and `search` are substring matches; be specific to avoid unintended deletions.
- `gcalcli quick` understands natural language times via Google's own parser — useful for casual scheduling.
- For recurring events, prefer `--cal` scoping and date ranges on `delete` to avoid bulk deletion of the series.
