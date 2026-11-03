# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose of this repository

The repository uses GitHub Issues to track problems in Knowledge Base (KB) articles. These articles are on support.mozilla.org (SUMO). The repository also contains software that helps to track KB articles.

## kb_revisions.py

`kb_revisions.py` saves the KB revisions of one SUMO user into SQLite (issue #252). It is a single uv script with PEP 723 metadata. There is no build, lint, or test setup.

```
uv run --with playwright playwright install chromium   # one time
uv run kb_revisions.py scrape --headed --all-pages     # first full run
uv run kb_revisions.py scrape --headed                 # later runs, new revisions only
uv run kb_revisions.py report --approved-since 2026-06-01
```

`--user` and `--locale` select the revisions list. The defaults are `rtanglao` and `en-US`. The database is `kb_revisions.sqlite`, and the browser profile is `.kb_revisions_browser/`. Git ignores both.

SUMO shows a Fastly puzzle to the Playwright browser. The script cannot solve it, so the user solves it in the `--headed` window. The script waits `--challenge-timeout` seconds (default 300) on the first page. The saved profile keeps the clearance between runs. Do not add code that hides automation from Fastly.

The script reads list pages newest first. Without `--all-pages`, it stops at the first list page on which all revisions are already saved. JavaScript in `LIST_JS` and `REVISION_JS` reads the pages. `parse_revision` maps the "Revision Information" labels to columns, and `info_json` keeps all raw items.

## Scope of the issues

The repository tracks KB issues for all free MZLA products:

- Thunderbird Desktop
- Thunderbird for Android
- Thunderbird for iOS (in the future)

Issues for SUMO KB articles about Firefox and other Mozilla Corporation products do not belong here. Send those reporters to Bugzilla. Before they file a bug, they read this guide: [How to submit a SUMO Knowledge Base content request](https://support.mozilla.org/en-US/kb/submit-sumo-knowledge-base-content-request).

Issues for Thunderbird Pro (TB Pro) KB articles also do not belong here. Send those reporters to the support form at https://support.tb.pro/hc/en-us/requests/new. Staff and volunteers can also use Matrix: [#Thunderbird Pro Early Birds](https://matrix.to/#/#tb-pro-early-birds:mozilla.org). They can also use the Slack channel #mzla-birdfooding.

All participants must follow the [Mozilla Community Participation Guidelines](https://www.mozilla.org/about/governance/policies/participation/).

## Working in this repository

Use the `gh` CLI for issue operations, for example `gh issue list` and `gh issue view <number>`.

## kb_approved_report.py

`kb_approved_report.py` reads `kb_revisions.sqlite` and writes the approved-articles report for issue #254. It has no dependencies. The output goes to `reports/`, and the reports are public in Git.

```
uv run kb_approved_report.py --since 2026-06-01 --sort date
```
