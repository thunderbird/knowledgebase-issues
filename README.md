# Thunderbird SUMO KB Issues


**NB: For SUMO KB articles for Firefox and all other Mozilla Corporation products, please use Bugzilla** after reading **[How to submit a SUMO Knowledge Base content request](https://support.mozilla.org/en-US/kb/submit-sumo-knowledge-base-content-request)**. NOT this repo. **

* This repo is for tracking Thunderbird support.mozilla.org (SUMO) Knowledge Base (KB) issues. It also contains software that helps to track KB articles.
* We require all those who participate in this repo to agree and adhere to the [Mozilla Community Participation Guidelines](https://www.mozilla.org/about/governance/policies/participation/) 
* **This repo will now handle issues for  SUMO Knowledge base articles for all MZLA free products**: Thunderbird for Android, Thunderbird Desktop and in the future Thunderbird for iOS. For Thunderbird pro, please contact the team via the support form at: https://support.tb.pro/hc/en-us/requests/new if there are issues with the TB Pro KB articles (staff and volunteers can also use Matrix, [#Thunderbird Pro Early Birds](https://matrix.to/#/#tb-pro-early-birds:mozilla.org) and Slack (#mzla-birdfooding) of course)

## Reports

These reports are for SUMO user `rtanglao`, starting on June 1, 2026. Click a column heading to sort the table.

- [Articles changed, with articles created before June 1 that changed substantially](https://thunderbird.github.io/knowledgebase-issues/reports/rtanglao_changed_since_2026-06-01_filtered_with_older.html). This report leaves out "New in Thunderbird Desktop" and "New in Thunderbird for Android".
- [Articles changed, without the articles that rtanglao created](https://thunderbird.github.io/knowledgebase-issues/reports/rtanglao_changed_since_2026-06-01_filtered.html). This report also leaves out the two "New in Thunderbird" articles.
- [All articles changed](https://thunderbird.github.io/knowledgebase-issues/reports/rtanglao_changed_since_2026-06-01.html)
- [Articles with an approved revision](https://thunderbird.github.io/knowledgebase-issues/reports/rtanglao_approved_since_2026-06-01.html)

The Markdown versions of these reports are in the [reports folder](https://github.com/thunderbird/knowledgebase-issues/tree/main/reports). Issue #257 describes how the scripts measure a change.

## Browse the KB revisions database with Datasette

`kb_revisions.sql` is a text copy of the database that `kb_revisions.py` makes. You can browse it with [Datasette](https://datasette.io/), in the cloud or on your computer.

### In the cloud (Datasette Lite)

Open this link in a browser:

https://lite.datasette.io/?sql=https://raw.githubusercontent.com/thunderbird/knowledgebase-issues/main/kb_revisions.sql

Datasette Lite runs in your browser. You do not install anything. The link loads the latest `kb_revisions.sql` from `main`. The file is 22 MB, so the first page takes a few seconds. Changes that you make stay in your browser tab.

### From the command line

You need [uv](https://docs.astral.sh/uv/).

1. Make the database from the SQL file:

   ```
   uv run kb_revisions.py import
   ```

2. Start Datasette:

   ```
   uv run --with datasette datasette kb_revisions.sqlite
   ```

3. Open http://127.0.0.1:8001 in a browser.

The `source` and `content_html` columns contain full articles. To hide them on a table page, add `?_nocol=source&_nocol=content_html` to the end of the URL.
