# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Report the KB articles that a user changed substantially since a date.

See https://github.com/thunderbird/knowledgebase-issues/issues/257

The script reads the article_revisions table in kb_revisions.sqlite. Fill
it first:
    uv run kb_revisions.py history --user NAME --since 2026-06-01 --headed

Method:
  * A run is a group of back-to-back revisions by the user. It counts as
    one edit, because people often save work in progress.
  * The script compares the words of the last revision in the run with the
    words of the revision before the run. All of the user's revisions
    count, approved or not.
  * percent changed = 100 x (words added + words removed in all runs) /
    (words before the first run + words after the last run), at most 100.
  * Only en-US articles count. Pages named "Template:..." do not count.
    Redirect pages (source starts with "REDIRECT") do not count.

Examples:
    uv run kb_changed_report.py
    uv run kb_changed_report.py --user NAME --since 2026-06-01 --threshold 20
"""

from __future__ import annotations

import argparse
import html
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from kb_approved_report import SORT_SCRIPT, markdown_escape


@dataclass
class ArticleChange:
    title: str
    url: str
    last_date: str
    words_added: int
    words_removed: int
    words_before: int
    words_after: int
    runs: int

    @property
    def percent(self) -> float:
        if self.words_before == 0:
            return 100.0
        total = self.words_before + self.words_after
        return min(100.0, 100.0 * (self.words_added + self.words_removed) / total)


def word_diff(old: list[str], new: list[str]) -> tuple[int, int]:
    """Return (words added, words removed)."""
    added = removed = 0
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def baseline(revisions: list[sqlite3.Row], run_start: int) -> sqlite3.Row | None:
    """Find the revision that the run changed.

    This is the last approved revision before the run. If there is none,
    it is the revision just before the run. The first revision of an
    article has no baseline.
    """
    earlier = revisions[:run_start]
    for rev in reversed(earlier):
        if rev["status"] == "approved":
            return rev
    return earlier[-1] if earlier else None


def analyze(revisions: list[sqlite3.Row], user_url: str, since: str) -> ArticleChange | None:
    def mine(rev: sqlite3.Row) -> bool:
        return (rev["creator_url"] or "").endswith(user_url)

    # Find the runs: [start, end] index pairs of back-to-back user revisions.
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(revisions):
        if mine(revisions[i]):
            j = i
            while j + 1 < len(revisions) and mine(revisions[j + 1]):
                j += 1
            if revisions[j]["created"][:10] >= since:
                runs.append((i, j))
            i = j + 1
        else:
            i += 1
    if not runs:
        return None

    added = removed = 0
    words_before = None
    for start, end in runs:
        base = baseline(revisions, start)
        old = (base["source"] or "").split() if base else []
        new = (revisions[end]["source"] or "").split()
        if words_before is None:
            words_before = len(old)
        a, r = word_diff(old, new)
        added += a
        removed += r

    last = revisions[runs[-1][1]]
    return ArticleChange(
        title=last["article_title"],
        url=last["article_url"],
        last_date=last["created"][:10],
        words_added=added,
        words_removed=removed,
        words_before=words_before or 0,
        words_after=len((last["source"] or "").split()),
        runs=len(runs),
    )


def load(db_path: str, user: str, since: str) -> list[ArticleChange]:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    user_url = f"/user/{user}/"
    slugs = [r[0] for r in db.execute(
        """
        SELECT DISTINCT article_slug FROM article_revisions
        WHERE creator_url LIKE ? AND substr(created, 1, 10) >= ?
          AND locale = 'en-US' AND article_title NOT LIKE 'Template:%'
        """,
        (f"%{user_url}", since),
    )]
    changes = []
    for slug in slugs:
        revisions = db.execute(
            "SELECT * FROM article_revisions WHERE article_slug = ? "
            "ORDER BY created, revision_id",
            (slug,),
        ).fetchall()
        if (revisions[-1]["source"] or "").lstrip().upper().startswith("REDIRECT"):
            continue  # A redirect left after a rename. It is not an article.
        change = analyze(revisions, user_url, since)
        if change:
            changes.append(change)
    changes.sort(key=lambda c: (-c.percent, c.title.casefold()))
    return changes


def to_markdown(changes, user, since, threshold) -> str:
    lines = [
        f"# KB articles changed by {user} since {since}",
        "",
        f"Substantial means {threshold:g}% or more of the words changed. "
        "See issue #257 for the method.",
        "",
        "| Date | Article | Percent changed | Words added | Words removed | Substantial |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for c in changes:
        lines.append(
            f"| {c.last_date} | [{markdown_escape(c.title)}]({c.url}) | {c.percent:.0f} "
            f"| {c.words_added} | {c.words_removed} | {'yes' if c.percent >= threshold else 'no'} |"
        )
    count = sum(c.percent >= threshold for c in changes)
    lines += ["", f"{len(changes)} articles. {count} substantial."]
    return "\n".join(lines) + "\n"


def to_html(changes, user, since, threshold) -> str:
    rows = "\n".join(
        f"    <tr><td>{c.last_date}</td>"
        f'<td><a href="{html.escape(c.url)}">{html.escape(c.title)}</a></td>'
        f'<td style="text-align:right">{c.percent:.0f}</td>'
        f'<td style="text-align:right">{c.words_added}</td>'
        f'<td style="text-align:right">{c.words_removed}</td>'
        f"<td>{'yes' if c.percent >= threshold else 'no'}</td></tr>"
        for c in changes
    )
    title = f"KB articles changed by {user} since {since}"
    count = sum(c.percent >= threshold for c in changes)
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
<p>Substantial means {threshold:g}% or more of the words changed.
Open this file in a browser, select the table, copy it, and paste it into Google Docs.</p>
<table>
  <thead><tr><th>Date</th><th>Article</th><th>Percent changed</th><th>Words added</th><th>Words removed</th><th>Substantial</th></tr></thead>
  <tbody>
{rows}
  </tbody>
</table>
<p>{len(changes)} articles. {count} substantial.</p>
{SORT_SCRIPT}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="kb_revisions.sqlite",
                        help="SQLite database file (default: %(default)s)")
    parser.add_argument("--user", default="rtanglao", help="SUMO user name (default: %(default)s)")
    parser.add_argument("--since", default="2026-06-01", metavar="YYYY-MM-DD",
                        help="first revision date to include (default: %(default)s)")
    parser.add_argument("--threshold", type=float, default=20.0,
                        help="percent changed that counts as substantial (default: %(default)s)")
    parser.add_argument("--out-dir", default="reports",
                        help="folder for the report files (default: %(default)s)")
    args = parser.parse_args()

    date.fromisoformat(args.since)  # Stops with an error if the date is not valid.
    if not Path(args.db).exists():
        sys.exit(f"{args.db} does not exist. Run kb_revisions.py scrape and history first.")

    changes = load(args.db, args.user, args.since)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.user}_changed_since_{args.since}"
    (out / f"{stem}.md").write_text(
        to_markdown(changes, args.user, args.since, args.threshold), encoding="utf-8")
    (out / f"{stem}.html").write_text(
        to_html(changes, args.user, args.since, args.threshold), encoding="utf-8")
    count = sum(c.percent >= args.threshold for c in changes)
    print(f"{len(changes)} articles, {count} substantial. "
          f"Wrote {out / stem}.md and .html.", file=sys.stderr)


if __name__ == "__main__":
    main()
