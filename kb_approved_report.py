# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Report the KB articles with an approved revision since a date.

See https://github.com/thunderbird/knowledgebase-issues/issues/254

The script reads kb_revisions.sqlite (made by kb_revisions.py) and writes
two files:

    <out-dir>/approved_since_<date>.md    Markdown table
    <out-dir>/approved_since_<date>.html  HTML table to paste into Google Docs

Each article has one row. The date is the date of the last approved
revision of the article.

Examples:
    uv run kb_approved_report.py
    uv run kb_approved_report.py --since 2026-06-01 --sort title
"""

from __future__ import annotations

import argparse
import html
import sqlite3
import sys
from datetime import date
from pathlib import Path

QUERY = """
SELECT substr(MAX(reviewed_date), 1, 10) AS last_approved,
       article_title,
       article_url
FROM revisions
WHERE status = 'approved' AND substr(reviewed_date, 1, 10) >= ?
GROUP BY article_slug
"""
# In SQLite, the bare columns in a query with MAX() come from the row with
# the maximum value. So the title is the title of the last approved revision.

SORT_SCRIPT = """<script>
// Click a column heading to sort the table. Google Docs does not keep this.
document.querySelectorAll('th').forEach((th, col) => {
  th.style.cursor = 'pointer';
  th.addEventListener('click', () => {
    const body = th.closest('table').tBodies[0];
    const asc = th.dataset.asc !== 'true';
    th.dataset.asc = asc;
    [...body.rows]
      .sort((a, b) => a.cells[col].innerText.localeCompare(b.cells[col].innerText) * (asc ? 1 : -1))
      .forEach(r => body.appendChild(r));
  });
});
</script>"""


def load_rows(db_path: str, since: str, sort: str) -> list[tuple[str, str, str]]:
    db = sqlite3.connect(db_path)
    rows = db.execute(QUERY, (since,)).fetchall()
    if sort == "title":
        rows.sort(key=lambda r: r[1].casefold())
    else:
        rows.sort(key=lambda r: (r[0], r[1].casefold()), reverse=True)
    return rows


def markdown_escape(text: str) -> str:
    for ch in "\\[]|":
        text = text.replace(ch, "\\" + ch)
    return text


def to_markdown(rows, since: str) -> str:
    lines = [
        f"# KB articles with approved revisions since {since}",
        "",
        "| Date | Article |",
        "| --- | --- |",
    ]
    for day, title, url in rows:
        lines.append(f"| {day} | [{markdown_escape(title)}]({url}) |")
    lines += ["", f"{len(rows)} articles."]
    return "\n".join(lines) + "\n"


def to_html(rows, since: str) -> str:
    body = "\n".join(
        f'    <tr><td>{html.escape(day)}</td>'
        f'<td><a href="{html.escape(url)}">{html.escape(title)}</a></td></tr>'
        for day, title, url in rows
    )
    title = f"KB articles with approved revisions since {since}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ font-family: Arial, sans-serif; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #999; padding: 4px 8px; text-align: left; }}
  th {{ background: #eee; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p>Open this file in a browser, select the table, copy it, and paste it into Google Docs.</p>
<table>
  <thead><tr><th>Date</th><th>Article</th></tr></thead>
  <tbody>
{body}
  </tbody>
</table>
<p>{len(rows)} articles.</p>
{SORT_SCRIPT}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="kb_revisions.sqlite",
                        help="SQLite database file (default: %(default)s)")
    parser.add_argument("--since", default="2026-06-01", metavar="YYYY-MM-DD",
                        help="first approval date to include (default: %(default)s)")
    parser.add_argument("--sort", choices=["date", "title"], default="date",
                        help="date sorts newest first, title sorts A to Z (default: %(default)s)")
    parser.add_argument("--out-dir", default="reports",
                        help="folder for the report files (default: %(default)s)")
    args = parser.parse_args()

    date.fromisoformat(args.since)  # Stops with an error if the date is not valid.
    if not Path(args.db).exists():
        sys.exit(f"{args.db} does not exist. Run kb_revisions.py scrape first.")

    rows = load_rows(args.db, args.since, args.sort)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"approved_since_{args.since}.md"
    html_path = out / f"approved_since_{args.since}.html"
    md_path.write_text(to_markdown(rows, args.since), encoding="utf-8")
    html_path.write_text(to_html(rows, args.since), encoding="utf-8")
    print(f"{len(rows)} articles. Wrote {md_path} and {html_path}.", file=sys.stderr)


if __name__ == "__main__":
    main()
