# Release Candidate Scheduler Live Smoke

Status: required before final release acceptance.

This smoke validates the repaired WSL2/Windows Task Scheduler environment for a
Codex-backed digest run. Do not put API keys, Codex tokens, OAuth material, or
copied Codex auth files into the task action.

## Preconditions

Run these from an interactive WSL shell:

```bash
command -v codex
codex login status
research-digest --version
research-digest doctor
research-digest status
```

Expected:

- `command -v codex` prints the interactive Codex executable path.
- `codex login status` reports ChatGPT login.
- `research-digest doctor` does not report a Codex provider failure.

## Remove Or Update Existing Task

If you want a clean reinstall:

```bash
research-digest schedule remove
research-digest schedule install --time 07:30 --distro Ubuntu
```

If you want to update in place, `install` is idempotent and uses Task Scheduler
`-Force`:

```bash
research-digest schedule install --time 07:30 --distro Ubuntu
```

Use the intended Windows local schedule time in place of `07:30`.

## Inspect Generated Action

From WSL:

```bash
powershell.exe -NoProfile -Command "$task = Get-ScheduledTask -TaskName 'Research Digest Daily'; $task.Actions | Format-List Execute,Arguments"
```

Verify:

- `Execute` is `C:\windows\system32\wsl.exe` or equivalent.
- `Arguments` include `--exec env`.
- `Arguments` include `RESEARCH_DIGEST_ANALYZER=codex`.
- `Arguments` include `PATH=<codex-dir>:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`, where `<codex-dir>` is the directory printed by `dirname "$(command -v codex)"`.
- `Arguments` invoke the installed `research-digest run`.
- `Arguments` do not include `OPENAI_API_KEY`, `CODEX_API_KEY`, `auth.json`, access tokens, refresh tokens, or other authentication material.

## Trigger And Verify

Trigger the task:

```bash
powershell.exe -NoProfile -Command "Start-ScheduledTask -TaskName 'Research Digest Daily'"
```

Wait for the task to finish, then inspect Windows result:

```bash
powershell.exe -NoProfile -Command "Get-ScheduledTaskInfo -TaskName 'Research Digest Daily' | Format-List LastRunTime,LastTaskResult"
```

Expected:

- `LastTaskResult` is `0`.

Inspect Research Digest state:

```bash
research-digest status
research-digest doctor
```

Expected:

- a new scheduled run appears after the manual run used for comparison.
- the new run is `COMPLETED`, not `ANALYSIS_UNAVAILABLE`.
- `retrieved`, `preselected`, and `analyzed` counts are nonzero when arXiv returns eligible papers.
- `doctor` does not warn that the schedule lacks the current Codex directory.

If the task reports `ANALYSIS_UNAVAILABLE` and `codex: not found`, reinstall the
schedule from an interactive shell where `command -v codex` works, then inspect
the generated `PATH` again.
