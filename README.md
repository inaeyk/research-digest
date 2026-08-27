# Research Digest v0.4.0

Research Digest is a local-first, personalized research-monitoring
application. It currently monitors arXiv, screens new papers against
natural-language research interests, performs deeper analysis only on promising
papers, creates cross-paper digests, and lets you build a persistent scientific
Library.

This release is arXiv-first and abstract-level. It is designed for a local,
single-user research workflow, not as a universal information extractor or a
cloud collaboration service. The default analyzer path can use the
ChatGPT-authenticated Codex CLI, so an OpenAI API key is not required for the
default Codex setup. OpenAI API mode remains available as an optional provider.

```
arXiv
  |
  v
Date selection
  |
  v
Abstract preselection
  |
  v
Full relevance analysis
  |
  v
Daily synthesis
  |
  v
Feedback / calibration
  |
  v
Library / tags / notes / connections
```

Papers rejected during abstract preselection do not receive expensive full
analysis or generated commentary. They remain visible with source metadata,
links, their original abstract on demand, and a Save to Library action.

## v0.4.0 highlights

- Source-date coverage now represents complete source retrieval, independent
  of Interest Profile analysis, and survives application or machine restarts.
- Retrieved source-date corpora remain reusable across profile edits, so those
  edits do not require redundant source retrieval. Completed analyses remain
  reusable across retries when their profile and analysis semantics are
  unchanged.
- Digest workers run independently from the browser and Streamlit UI. Active
  runs can be rediscovered after UI restart and explicitly cancelled while
  retaining completed work and source coverage.
- Article headers consistently show source-provided author metadata.
- Windows 11 with WSL2 has an owned Desktop launcher and Task Scheduler
  automation; macOS has an owned `Research Digest.app` and launchd automation.
- Linux/WSL and Darwin use exact process ownership for UI and provider lifecycle
  operations. The macOS bootstrap rejects Python older than 3.11 before it
  creates a virtual environment.

Windows 11 with WSL2 and macOS are human-qualified on their tested
environments. Two environment-only smokes remain deferred: Windows launch plus
real Codex execution immediately after `wsl --shutdown`, and macOS login/logout
or full restart. Finder launch, real Codex analysis, cancellation, fallback
ports, and launchd invocation passed on real Mac hardware.

## Installation and First Run

Research Digest requires Python 3.11 or newer. Check the interpreter before
creating a virtual environment:

```bash
python3 -c 'import sys; print(sys.version.split()[0]); raise SystemExit(0 if sys.version_info >= (3, 11) else "Research Digest requires Python 3.11+")'
```

From a checkout of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On macOS, the guarded bootstrap performs that version check before creating
`.venv` and can discover a versioned `python3.11`–`python3.14` executable when
the active `python3` is older:

```bash
./scripts/bootstrap_macos.sh
source .venv/bin/activate
```

If needed, select an installed interpreter explicitly:

```bash
RESEARCH_DIGEST_PYTHON=/path/to/python3.12 ./scripts/bootstrap_macos.sh
```

If no compatible interpreter is installed, use a current installer from
python.org or Homebrew, then rerun the bootstrap. It will not create `.venv`
with Python 3.10 or older.

For development tools as well:

```bash
python -m pip install -e ".[dev]"
```

Check that the command is installed:

```bash
research-digest --version
research-digest status
```

### Everyday Windows and macOS Launch

Install the platform launcher once:

```bash
research-digest install-launcher
```

On Windows 11 with WSL2 this creates the owned **Research Digest** Desktop
shortcut. On macOS it creates the owned user-local app at:

```text
~/Applications/Research Digest.app
```

After that, open **Research Digest** normally from the Windows Desktop or macOS
Finder/Dock. Research Digest starts or reuses one local UI server and opens it
in the platform default browser. No WSL or macOS Terminal window needs to
remain open.

Power-user UI commands are:

```bash
research-digest launch
research-digest ui-status --json
research-digest ui-stop
research-digest uninstall-launcher
```

`launch` is idempotent: repeated or rapid launches reuse the same exact server.
If port 8501 belongs to another application, Research Digest leaves it alone and
uses a bounded fallback port. UI logs and process registration live below the
Research Digest user-data directory, not in the repository.

The lifecycles are deliberately separate:

- Closing the browser does not stop or cancel a digest.
- `ui-stop` stops only the Streamlit UI server; an active digest continues.
- **Cancel digest** stops the active digest but does not disable its schedule.
- Stopping or restarting the UI does not change source coverage or start catch-up.

### Codex Authentication

The default analyzer can use the Codex CLI and its saved ChatGPT
authentication:

```bash
codex login status
codex login
```

ChatGPT subscription access and OpenAI API billing are separate. Codex-backed
operation uses the Codex CLI login state. OpenAI API mode is optional and uses
`OPENAI_API_KEY`.

The Windows shortcut and macOS app intentionally never store API keys or
authentication tokens. If optional OpenAI API mode is used, `OPENAI_API_KEY`
must already be available to the non-interactive application environment;
Codex CLI authentication continues to use its normal saved login state.

On macOS, run `install-launcher` from a Terminal where `research-digest` and,
when Codex-backed analysis or Library intelligence is used, `codex` resolve
successfully. The installer captures their exact executable
directories—and the directory of an interpreter declared through a validated
`/usr/bin/env` shebang, such as `node`—in the app's non-secret PATH, because
Finder apps do not load interactive shell startup files. If either tool or its
runtime moves (for example after a virtual-environment, Homebrew, npm, or nvm
change), rerun
`research-digest install-launcher`. Both Apple Silicon and Intel installs are
supported without architecture-specific paths where Python and the declared
dependencies support the current macOS release. The package requires Python
3.11 or newer and declares no additional project-specific historical macOS
floor beyond its Python/dependency support.

For foreground/manual debugging, the existing server command remains available:

```bash
research-digest serve
```

`serve` prints the local browser URL and keeps the manual Streamlit server path
separate from the everyday detached launcher. You normally do not need to run
`streamlit run` directly.

To use OpenAI API mode instead of Codex:

```bash
export RESEARCH_DIGEST_ANALYZER=openai
export OPENAI_API_KEY=...
research-digest doctor
```

Never store API keys in the repository, SQLite database, or checked-in config.

## UI Pages

### Today

Run a date-based digest, inspect the current results, give feedback, save
papers to the Library, and view the date-status calendar.

### Library

Browse saved papers, search and filter them, manage tags, notes, collections,
AI tag suggestions, and related-paper connections.

### History

Review immutable digest runs. History keeps manual and scheduled runs
distinguishable and preserves what each run requested and produced.

### Interests

Create and edit natural-language Interest Profiles. Each profile has its own
description and relevance threshold.

### Sources

Configure the arXiv source, including enabled categories. Category order is not
meaningful for source identity; equivalent category sets are treated as the same
source scope.

### Settings

Manage analysis controls, Library intelligence settings, the Scoring Guide,
automation, backups, data paths, and diagnostics.

## Running a Digest

Today is date-native. Choose one of:

- latest available arXiv source date
- Single date
- contiguous source-date range
- Selected dates

Research Digest retrieves all eligible papers from the selected arXiv source
dates. The normal workflow does not ask you to choose an arbitrary maximum
number of articles. Computational effort is controlled by preselection, caching,
and the model-effort setting.

For arXiv, Research Digest source dates use `America/Chicago`. A paper is
assigned to a source date by converting its authoritative arXiv publication
timestamp to Chicago local time using timezone database rules. Research Digest
does not try to duplicate arXiv mailing or announcement-page cutoff semantics.

History preserves individual runs. A later run of the same date can reuse valid
cached analyses while keeping earlier run records intact.

### Cancelling a Digest

While a digest is active, Today and Settings show its durable progress and an
application **Cancel digest** button. Use that button to cancel backend retrieval,
analysis, or Library work. Streamlit's top-right Stop control only stops the current
page script; it is not the Research Digest cancellation control.

The worker is local and independent of the Streamlit server. If the browser is
refreshed or the UI is stopped and reopened with `research-digest launch`, the UI
reattaches to the active run and offers the same cancellation control. Completed
retrieval and valid partial analyses are preserved for retry. Power users can use
the same cancellation service:

```bash
research-digest cancel --run-id RUN_ID
```

Cancelling a scheduled run does not disable the daily schedule.

## Interests and Relevance

An Interest Profile is a natural-language description of what you want the
digest to surface. For example:

```text
I am interested in higher-dimensional gravity, compactification,
black-hole dynamics, Kaluza-Klein spectra, and related numerical methods.
Surface adjacent work when there is a concrete scientific connection.
```

Each profile has a relevance threshold. A fully analyzed paper is treated as
relevant to that profile when:

```text
relevance_score >= relevance_threshold
```

Profiles can be created and edited independently. Suggested Interests may
propose new profiles from repeated feedback, but Research Digest never silently
rewrites an existing profile.

## Model Effort and Preselection

Model effort controls the tradeoff between speed/cost and false-negative risk.
It is the user-facing version of the internal preselection setting.

```text
model_effort = 1 - preselection_fraction

Stage-1 cutoff
  = preselection_fraction x relevance_threshold
```

At 100% Model effort, almost everything proceeds to full analysis. At lower
effort, Stage 1 filters more aggressively.

Worked example: suppose your profile relevance threshold is `0.70` and Model
effort is `40%`. A 40% effort setting corresponds to a preselection fraction of
`0.60`, so the Stage-1 cutoff is:

```text
0.60 x 0.70 = 0.42
```

A new paper with an abstract-level preselection score of at least `0.42`
proceeds to full analysis. A paper below `0.42` is screened out and shown with
its original abstract available on demand.

Higher Model effort sends more papers to full analysis and reduces the chance
of missing indirectly relevant papers, but requires more Codex or model work.
Lower Model effort makes runs faster and more selective, with more risk of
missing borderline papers. A 40% effort setting does not mean exactly 40% of
papers will be analyzed; it sets the Stage-1 cutoff.

New v0.3.0 configurations default to 40% Model effort. Existing saved settings
are preserved on upgrade.

## Two-Stage Analysis

### Stage 1: Abstract Preselection

Stage 1 reads title, abstract, and basic metadata. It is batched and cheaper
than full analysis. It answers a recall-oriented question:

```text
From the title and abstract alone, how plausible is it that deeper analysis
would find this paper meaningfully relevant to the selected Interest Profile?
```

It returns an ordinal preselection score in `0..1`. The score is not a
calibrated probability. Papers below the Stage-1 cutoff do not receive full
analysis.

### Stage 2: Full Relevance Analysis

Stage 2 is the deeper abstract-level analysis for papers that pass Stage 1, or
for papers with already valid cached analyses. It can produce:

- relevance score
- relevance reason
- summary
- why it matters
- reading priority
- matched topics

Preselection score and final relevance score answer related but different
questions. Both are ordinal model judgments, not calibrated probabilities.

## Preselected-Out Papers

A preselected-out paper intentionally receives no generated scientific
commentary. Its card shows only source metadata, arXiv/PDF links, Show abstract,
and Save to Library.

If Stage 1 does not find enough evidence to justify deeper analysis, Research
Digest avoids spending additional model effort. You can still inspect the
original abstract yourself and save the paper if it matters to you.

## Feedback

Research Digest asks two separate questions:

```text
Does this paper match "<profile>"?
Yes / No

Are you personally interested in this paper?
Yes / No
```

These are intentionally different.

- Matches profile + interested: the profile fit was right and you care about
  the paper.
- Matches profile + not personally interested: the profile fit may still be
  correct; you simply do not want this paper.
- Outside profile + personally interested: the paper may reveal another
  interest you want to follow.
- Outside profile + not interested: useful negative profile-fit evidence.

Profile-match feedback is what calibrates the profile/relevance system.
Personal interest does not redefine profile correctness. Outside-profile but
personally interesting examples can contribute to Suggested Interests.

## Quantitative Calibration

Research Digest may occasionally ask:

```text
How relevant is this paper to this profile, from 0 to 1?
```

The default is a 20% chance per completed digest run, with at most one
calibration request per run. The candidate is selected from analyzed papers that
finished below the profile relevance threshold. Preselected-out papers are not
chosen.

The model's relevance score is hidden before you answer to reduce anchoring.
Your score and the model score are stored separately. v0.3.0 collects this
calibration evidence but does not automatically rewrite the scoring function
from a small number of samples.

## Suggested Interests

When you repeatedly mark papers as outside the current profile but personally
interesting, Research Digest can suggest a new Interest Profile.

Suggested Interests require multiple coherent examples. You review and edit the
profile name and description before creating it. Nothing is created
automatically, and dismissals are remembered.

## Library

The Library is explicit user curation. Saving a paper:

- saves the stable Article identity
- marks you as personally interested in the paper
- does not automatically change whether the paper matches the current profile
- does not duplicate the Article if it appears in multiple digest runs

Unsaving removes the paper from the Library view. It does not delete the
Article, History, analyses, feedback, or notes from the database, and it does
not automatically mean "not interested."

Library features include:

- AI-generated tags
- user tags
- visible tag provenance
- removal and suppression of unwanted AI tags
- personal notes
- collections/projects
- search and filtering
- related-paper and scientific connection suggestions
- Show abstract

## Library Connections

Research Digest can identify possible relationships between a new or saved
paper and papers in your Library. These are model-generated scientific
suggestions, not facts.

Connection confidence means confidence in the stated paper-to-paper
relationship based on the bounded evidence inspected. It does not mean profile
relevance, and it is not a statistical confidence interval or calibrated
probability.

Settings includes:

```text
Automatic Library connections: ON / OFF
Automatic Library relevance threshold: 0.90 by default
```

The `0.90` threshold applies to the new paper's final profile relevance score.
It decides whether Research Digest is allowed to spend extra model effort
automatically comparing that paper against the Library.

If automatic connections are off, digest runs perform no automatic Library
connection model work. Manual Find Library connections remains available.

## Scoring Guide

Open Settings -> Scoring Guide for the current values and exact explanations of
the app's quantitative controls. It covers:

- relevance score
- relevance threshold
- preselection score
- Model effort
- Stage-1 cutoff
- automatic Library threshold
- Library connection confidence
- human calibration score

The important rule is that these are ordinal heuristic model scores unless the
app explicitly says otherwise. They are not calibrated probabilities.

## Scheduling and Automation

Daily automation is managed from Settings -> Automation. A normal user should
not need to run scheduler commands after launching the app.

Automation controls include:

- Automatic daily digest
- daily time
- Catch up missed source dates
- Catch up from
- Run now
- schedule state, next run, and previous run
- coverage calendar

Catch up from `DATE` means process every still-uncovered eligible source date
from that date through the latest available source date. Successful manual runs
also count as covered when they satisfy the same retrieval and digest-success
rules. Failed, partial, or interrupted dates remain eligible for retry.

The scheduler backend is selected by platform:

- Windows/WSL uses Windows Task Scheduler.
- macOS uses an owned per-user LaunchAgent under `~/Library/LaunchAgents`.

Schedule times use the operating system's local time and daylight-saving rules.
Neither backend stores API keys or Codex authentication material.

Settings can inspect, install, update, and disable the schedule. Run now is an
explicit action; simply opening Settings does not process pending dates.

## History and Date Coverage

History stores immutable run records. Manual, scheduled, and Run now executions
are distinguishable. Completed, failed, partial, and empty dates remain
inspectable.

History by itself is not long-term semantic memory. The Library is the
persistent workspace for saved papers, notes, tags, collections, and scientific
connections.

Date coverage is scoped only to source semantics, not Interest Profile
semantics. Reordering the same arXiv category set, for example `hep-th` plus
`gr-qc` versus `gr-qc` plus `hep-th`, does not create a new source scope.
Actually changing the category set does; editing a profile does not.

## Long-Running Digests

Multi-date digests can take several minutes when many papers require new
analysis. Progress reporting uses real pipeline stages rather than invented
percentages, including retrieval, preselection, full analysis, Library context,
and synthesis.

Repeated runs can be faster because valid analyses and Library connection
results are reused where their semantic cache identity still applies.

## Data, Backup, and Upgrades

Research Digest stores persistent user data outside the source checkout by
default. On Linux and WSL this is normally:

```text
~/.local/share/research-digest/
~/.config/research-digest/
```

On macOS, both data and config default below:

```text
~/Library/Application Support/Research Digest/
```

The app bundle contains no database or runtime state. On Windows, Research
Digest continues to use its established WSL per-user paths. Inspect the active
paths with:

```bash
research-digest status
research-digest status --json
```

Useful non-secret overrides:

```bash
export RESEARCH_DIGEST_DB=/absolute/path/to/research_digest.sqlite3
export RESEARCH_DIGEST_DATA_DIR=/absolute/path/to/data-dir
export RESEARCH_DIGEST_CONFIG_DIR=/absolute/path/to/config-dir
```

Create a SQLite backup from Settings -> Data or from the CLI:

```bash
research-digest backup
research-digest backup --export-json
```

Code upgrades are separate from persistent user data. Database and config
migrations are versioned, deterministic, and additive where possible. Before a
manual upgrade or recovery, run:

```bash
research-digest doctor
research-digest backup --export-json
```

## CLI Quick Reference

The UI is the normal workflow after launch. The CLI remains useful for power
users, automation, and recovery.

```bash
research-digest --version
research-digest launch [--port 8501] [--no-browser] [--json]
research-digest ui-status [--json]
research-digest ui-stop [--json]
research-digest install-launcher [--distro NAME] [--json]
research-digest uninstall-launcher [--json]
research-digest serve [--port 8501] [--host localhost]
research-digest run [--json]
research-digest status [--json]
research-digest doctor [--json] [--network]
research-digest backup [--output PATH] [--export-json] [--json]
research-digest schedule status [--json]
research-digest schedule install --time HH:MM [--distro NAME] [--backend auto|windows|launchd] [--json]
research-digest schedule remove [--json]
research-digest recover-abandoned-run --run-id ID [--force-uninspectable-owner] [--json]
```

`recover-abandoned-run` is for an interrupted or abandoned running digest. It
marks the stale run terminal through application logic and preserves History; it
is not part of normal daily use.

## Troubleshooting

Start with:

```bash
research-digest doctor
research-digest status
```

For launcher or UI-server problems on either platform, inspect:

```bash
research-digest ui-status --json
```

The status includes the exact owned PID, actual URL, and UI log path when a
registered server exists. A failed `launch` does not open a dead browser tab and
reports the diagnostic log path.

If Codex analysis fails, check:

```bash
codex login status
codex login
```

If automation looks wrong, inspect Settings -> Automation. A schedule can be
enabled, disabled, or unavailable/unknown if the scheduler cannot be inspected.
A nonzero previous task result describes the last execution outcome; it does not
by itself mean the schedule is off.

If a digest was interrupted by shutdown or a terminated scheduler process,
`research-digest status` and `doctor` can identify the stale run. Use
`recover-abandoned-run` only when you have confirmed the owner process is gone,
and make a backup before manual recovery work.

## Privacy and Security

Research Digest is local-first. The primary store is a local SQLite database.
Config and data live in per-user directories by default.

Scheduled tasks do not embed API keys or Codex authentication material. Codex
ChatGPT authentication remains managed by the Codex CLI. `.env` files,
databases, credentials, caches, build outputs, and runtime state should not be
committed to Git.

Article titles, abstracts, notes, and other external text are treated as
untrusted input in model prompts. Do not store secrets in article notes or
profile text.

## Known Limitations

- arXiv is the only source pool and source family.
- Analysis is abstract-level; full-paper/PDF deep reading is deferred.
- Model scores are ordinal judgments, not calibrated probabilities.
- Library connections are model inferences and should be reviewed critically.
- Windows/WSL and macOS are human-qualified on their tested environments. The
  documented Windows cold-WSL-start/real-Codex and macOS login/logout or
  full-restart smokes remain deferred.
- Research Digest is local and single-user; it has no multi-user or cloud
  collaboration layer.

## Roadmap

Possible future work includes:

- additional source adapters and websites
- optional full-paper analysis
- further empirical relevance calibration

No timeline is promised.

## Developer Notes

The main implementation lives under `src/research_digest`. Streamlit UI pages
are under `src/research_digest/ui`. Retrieval logic lives behind source
adapters, and model access lives behind provider interfaces so deterministic
tests can avoid live arXiv or OpenAI access.

Common checks:

```bash
pytest
ruff check .
mypy --strict src tests
python -m compileall src tests
git diff --check
```

Campaign qualification details, migration evidence, and audit reports are kept
under `docs/campaigns/`.
