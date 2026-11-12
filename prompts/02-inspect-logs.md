# Prompt 2: inspect the session logs

Paste this into Claude Code from the repo root. It only inspects. It builds nothing.

```
Look at my Claude Code session logs under ~/.claude/projects.
Do not copy any prompt text or file contents out of them.
Write docs/SCHEMA.md describing only the structure:
- the record types and their fields
- where token usage is recorded, and at what level (per model call, per tool call, or per session)
- how a tool call links to its result
- how to tell which file, URL, or search each tool call touched
- anything that looks missing for building a per-step cost breakdown
Finish with a short list of open questions.
```

When it is done, bring docs/SCHEMA.md back to the planning chat. The parser prompt gets
written from it.
