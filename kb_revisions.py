# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.48"]
# ///
"""Save SUMO Knowledge Base revisions for one user into a SQLite database.

See https://github.com/thunderbird/knowledgebase-issues/issues/252

Examples:
    uv run kb_revisions.py scrape --user rtanglao --locale en-US
    uv run kb_revisions.py history --since 2026-06-01
    uv run kb_revisions.py report --approved-since 2026-06-01

Before the first run, install the browser:
    uv run --with playwright playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

BASE_URL = "https://support.mozilla.org"
PAGE_TIMEOUT_MS = 60_000

COLUMNS = """
    revision_id              INTEGER PRIMARY KEY,
    locale                   TEXT,
    article_slug             TEXT,
    article_title            TEXT,
    article_url              TEXT,
    revision_url             TEXT,
    previous_revision_id     INTEGER,
    created                  TEXT,
    creator_name             TEXT,
    creator_url              TEXT,
    comment                  TEXT,
    reviewed                 INTEGER,
    reviewed_date            TEXT,
    reviewed_by              TEXT,
    is_approved              INTEGER,
    is_current               INTEGER,
    ready_for_l10n           INTEGER,
    readied_for_l10n_date    TEXT,
    readied_for_l10n_by      TEXT,
    status                   TEXT,
    source                   TEXT,
    content_html             TEXT,
    info_json                TEXT,
    scraped_at               TEXT"""

# revisions: the revisions of one user, from the revisions list.
# article_revisions: every revision, by every editor, of the articles that
# the history command reads. "significance" comes from the history page.
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS revisions ({COLUMNS}
);
CREATE INDEX IF NOT EXISTS idx_revisions_status_reviewed
    ON revisions (status, reviewed_date);
CREATE INDEX IF NOT EXISTS idx_revisions_article ON revisions (article_slug);
CREATE TABLE IF NOT EXISTS article_revisions ({COLUMNS},
    significance             TEXT
);
CREATE INDEX IF NOT EXISTS idx_article_revisions_article
    ON article_revisions (article_slug, created);
"""

# JavaScript that reads one page of the revisions list.
LIST_JS = """
() => {
  const rows = [...document.querySelectorAll('#revisions-fragment li:not(.header)')];
  const items = rows.map(li => {
    const rev = li.querySelector('.date a');
    const diff = li.querySelector('a.show-diff');
    const title = li.querySelector('.title a');
    return {
      revision_url: rev ? rev.href : null,
      diff_url: diff ? diff.href : null,
      article_title: title ? title.textContent.trim() : null,
      article_url: title ? title.href : null,
      locale: (li.querySelector('.title .locale') || {}).textContent?.trim() || null,
    };
  }).filter(i => i.revision_url);
  const next = document.querySelector('.pagination li.next a');
  return {items, next: next ? next.href : null};
}
"""

# JavaScript that reads the history page of one article. The rows are
# newest first, and the page has no pagination.
HISTORY_JS = """
() => [...document.querySelectorAll('#revision-list tr[id^="rev-list-"]')].map(tr => {
  const a = tr.querySelector('td.date a');
  return {
    revision_url: a ? a.href : null,
    significance: (tr.querySelector('td.significance') || {}).textContent?.trim() || '',
  };
}).filter(r => r.revision_url)
"""

# JavaScript that reads one revision page. It keeps every item in the
# "Revision Information" list, so that no field is lost.
REVISION_JS = """
() => {
  const info = [...document.querySelectorAll('.revision-info li')].map(li => {
    const label = (li.querySelector('strong') || {}).textContent?.trim().replace(/:$/, '') || '';
    const span = li.querySelector('span');
    const t = span ? span.querySelector('time') : null;
    const a = span ? span.querySelector('a') : null;
    return {
      label,
      text: span ? span.textContent.trim() : '',
      datetime: t ? t.getAttribute('datetime') : null,
      href: a ? a.href : null,
    };
  });
  const src = document.querySelector('#doc-source textarea');
  const content = document.querySelector('#doc-content');
  const h1 = document.querySelector('article.wiki-doc h1');
  return {
    info,
    article_title: h1 ? h1.textContent.trim() : null,
    source: src ? src.value : null,
    content_html: content ? content.innerHTML.trim() : null,
  };
}
"""


def yes_no(text: str | None) -> int | None:
    if text is None:
        return None
    value = text.strip().lower()
    if value == "yes":
        return 1
    if value == "no":
        return 0
    return None


def wait_for(page: Page, url: str, selector: str, timeout_ms: int = PAGE_TIMEOUT_MS) -> None:
    """Load a URL and wait until the SUMO content is on the page.

    SUMO can first show a Fastly "Client Challenge" page. If it does, you
    complete the challenge in the browser window, and then SUMO shows the
    real page.
    """
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    page.wait_for_selector(selector, state="attached", timeout=timeout_ms)


def parse_revision(data: dict, list_item: dict) -> dict:
    """Turn the raw page data into one database row."""
    row: dict = {
        "info_json": json.dumps(data["info"], ensure_ascii=False),
        "source": data["source"],
        "content_html": data["content_html"],
        "article_title": list_item.get("article_title") or data["article_title"],
        "article_url": list_item.get("article_url"),
        "revision_url": list_item["revision_url"],
        "locale": list_item.get("locale"),
    }

    path = urlparse(list_item["revision_url"]).path  # /en-US/kb/<slug>/revision/<id>
    match = re.search(r"/kb/([^/]+)/revision/(\d+)", path)
    if match:
        row["article_slug"] = match.group(1)
        row["revision_id"] = int(match.group(2))

    if list_item.get("diff_url"):
        query = parse_qs(urlparse(list_item["diff_url"]).query)
        if query.get("from"):
            row["previous_revision_id"] = int(query["from"][0])

    for item in data["info"]:
        label, text, when, href = item["label"], item["text"], item["datetime"], item["href"]
        if label == "Revision id":
            row["revision_id"] = int(text)
        elif label == "Created":
            row["created"] = when or text
        elif label == "Creator":
            row["creator_name"] = text
            row["creator_url"] = href
        elif label == "Comment":
            row["comment"] = text
        elif label == "Reviewed" and when:
            row["reviewed_date"] = when
        elif label == "Reviewed":
            row["reviewed"] = yes_no(text)
        elif label == "Reviewed by":
            row["reviewed_by"] = text
        elif label == "Is approved?":
            row["is_approved"] = yes_no(text)
        elif label == "Is current revision?":
            row["is_current"] = yes_no(text)
        elif label == "Readied for localization by":
            row["readied_for_l10n_by"] = text
        elif label == "Readied for localization" and when:
            row["readied_for_l10n_date"] = when
        elif label == "Ready for localization":
            row["ready_for_l10n"] = yes_no(text)

    if row.get("is_approved") == 1:
        row["status"] = "approved"
    elif row.get("reviewed") == 1 or row.get("reviewed_date"):
        row["status"] = "rejected"
    else:
        row["status"] = "unreviewed"

    row["scraped_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return row


def save(db: sqlite3.Connection, row: dict, table: str = "revisions") -> None:
    columns = list(row)
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "revision_id")
    db.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(revision_id) DO UPDATE SET {updates}",
        [row[c] for c in columns],
    )
    db.commit()


def known_ids(db: sqlite3.Connection) -> set[int]:
    return {r[0] for r in db.execute("SELECT revision_id FROM revisions")}


def revision_id_from_url(url: str) -> int | None:
    match = re.search(r"/revision/(\d+)", url)
    return int(match.group(1)) if match else None


def scrape(args: argparse.Namespace) -> None:
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    have = known_ids(db)

    query = urlencode({"locale": args.locale, "users": args.user})
    list_url: str | None = f"{BASE_URL}/{args.locale}/kb/revisions?{query}"

    added = 0
    page_number = 0
    with sync_playwright() as p:
        # A saved browser profile keeps the challenge cookie between runs.
        context = p.chromium.launch_persistent_context(
            args.profile_dir, headless=not args.headed)
        page = context.pages[0] if context.pages else context.new_page()
        while list_url:
            page_number += 1
            if args.max_pages and page_number > args.max_pages:
                break
            print(f"List page {page_number}: {list_url}", file=sys.stderr)
            if page_number == 1:
                print("  If the browser shows a challenge, complete it in the window.",
                      file=sys.stderr)
            wait_for(page, list_url, "#revisions-fragment",
                     args.challenge_timeout * 1000 if page_number == 1 else PAGE_TIMEOUT_MS)
            listing = page.evaluate(LIST_JS)
            items = listing["items"]
            todo = [
                i for i in items
                if args.refresh or revision_id_from_url(i["revision_url"]) not in have
            ]

            for item in todo:
                time.sleep(args.delay)
                url = urljoin(BASE_URL, item["revision_url"])
                try:
                    wait_for(page, url, ".revision-info")
                except PlaywrightTimeout:
                    print(f"  Timeout, skipped: {url}", file=sys.stderr)
                    continue
                row = parse_revision(page.evaluate(REVISION_JS), item)
                save(db, row)
                have.add(row["revision_id"])
                added += 1
                print(f"  Saved {row['revision_id']} {row['article_title']} "
                      f"({row['status']})", file=sys.stderr)

            # The list is newest first. If a full page has only known
            # revisions, the older pages are known too.
            if items and not todo and not args.all_pages:
                print("  All revisions on this page are already saved. Stopped.",
                      file=sys.stderr)
                break

            list_url = listing["next"]
            if list_url:
                time.sleep(args.delay)
        context.close()

    print(f"Saved {added} revisions to {args.db}.", file=sys.stderr)


def history(args: argparse.Namespace) -> None:
    """Save every revision of each article that the user touched since a date."""
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    articles = db.execute(
        """
        SELECT article_slug, MAX(article_title), MAX(article_url), MAX(locale)
        FROM revisions
        WHERE substr(created, 1, 10) >= ? AND creator_url LIKE ?
        GROUP BY article_slug ORDER BY article_slug
        """,
        (args.since, f"%/user/{args.user}/"),
    ).fetchall()
    print(f"{len(articles)} articles with a revision by {args.user} since {args.since}.",
          file=sys.stderr)
    if not articles:
        print(f"Run 'scrape --user {args.user}' first.", file=sys.stderr)

    have = {r[0] for r in db.execute("SELECT revision_id FROM article_revisions")}
    mine = {r[0] for r in db.execute("SELECT revision_id FROM revisions")}
    column_names = [c.split()[0] for c in COLUMNS.strip().split(",\n")]

    added = 0
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            args.profile_dir, headless=not args.headed)
        page = context.pages[0] if context.pages else context.new_page()
        print("If the browser shows a challenge, complete it in the window.", file=sys.stderr)
        for number, (slug, title, article_url, locale) in enumerate(articles, 1):
            locale = locale or "en-US"
            url = f"{BASE_URL}/{locale}/kb/{slug}/history"
            print(f"Article {number}/{len(articles)}: {title}", file=sys.stderr)
            try:
                wait_for(page, url, "#revision-list",
                         args.challenge_timeout * 1000 if number == 1 else PAGE_TIMEOUT_MS)
            except PlaywrightTimeout:
                print(f"  Timeout, skipped: {url}", file=sys.stderr)
                continue
            rows = page.evaluate(HISTORY_JS)

            for i, hist in enumerate(rows):
                rev_id = revision_id_from_url(hist["revision_url"])
                older = rows[i + 1]["revision_url"] if i + 1 < len(rows) else None
                previous = revision_id_from_url(older) if older else None
                if rev_id in have and not args.refresh:
                    db.execute("UPDATE article_revisions SET significance = ? "
                               "WHERE revision_id = ?", (hist["significance"], rev_id))
                    continue
                if rev_id in mine and not args.refresh:
                    # Copy the saved row. No download is necessary.
                    cols = ", ".join(column_names)
                    db.execute(
                        f"INSERT OR REPLACE INTO article_revisions ({cols}, significance) "
                        f"SELECT {cols}, ? FROM revisions WHERE revision_id = ?",
                        (hist["significance"], rev_id))
                    db.execute("UPDATE article_revisions SET previous_revision_id = ? "
                               "WHERE revision_id = ?", (previous, rev_id))
                    db.commit()
                    have.add(rev_id)
                    continue
                time.sleep(args.delay)
                rev_url = urljoin(BASE_URL, hist["revision_url"])
                try:
                    wait_for(page, rev_url, ".revision-info")
                except PlaywrightTimeout:
                    print(f"  Timeout, skipped: {rev_url}", file=sys.stderr)
                    continue
                item = {"revision_url": rev_url, "article_title": title,
                        "article_url": article_url, "locale": locale}
                row = parse_revision(page.evaluate(REVISION_JS), item)
                row["previous_revision_id"] = previous
                row["significance"] = hist["significance"]
                save(db, row, "article_revisions")
                have.add(rev_id)
                added += 1
                print(f"  Saved {rev_id} by {row.get('creator_name')} ({row['status']})",
                      file=sys.stderr)
            db.commit()
            time.sleep(args.delay)
        context.close()

    total = db.execute("SELECT COUNT(*) FROM article_revisions").fetchone()[0]
    print(f"Downloaded {added} revisions. article_revisions has {total} rows.",
          file=sys.stderr)


def report(args: argparse.Namespace) -> None:
    db = sqlite3.connect(args.db)
    rows = db.execute(
        """
        SELECT article_title, article_url, COUNT(*) AS approved_revisions,
               MAX(reviewed_date) AS last_approved
        FROM revisions
        WHERE status = 'approved' AND substr(reviewed_date, 1, 10) >= ?
          AND creator_url LIKE ?
        GROUP BY article_slug
        ORDER BY article_title COLLATE NOCASE
        """,
        (args.approved_since, f"%/user/{args.user}/"),
    ).fetchall()
    for title, url, count, last in rows:
        print(f"{title}\t{url}\t{count}\t{last[:10]}")
    print(f"{len(rows)} articles with an approved revision since "
          f"{args.approved_since}.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="kb_revisions.sqlite",
                        help="SQLite database file (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scrape", help="download revisions into the database")
    s.add_argument("--user", default="rtanglao", help="SUMO user name (default: %(default)s)")
    s.add_argument("--locale", default="en-US", help="KB locale (default: %(default)s)")
    s.add_argument("--delay", type=float, default=2.0,
                   help="seconds to wait between page loads (default: %(default)s)")
    s.add_argument("--refresh", action="store_true",
                   help="download revisions again, also if they are already saved")
    s.add_argument("--all-pages", action="store_true",
                   help="read every list page, also after a page with only saved revisions")
    s.add_argument("--max-pages", type=int, default=0,
                   help="stop after this number of list pages (default: no limit)")
    s.add_argument("--headed", action="store_true", help="show the browser window")
    s.add_argument("--profile-dir", default=".kb_revisions_browser",
                   help="browser profile folder that keeps cookies (default: %(default)s)")
    s.add_argument("--challenge-timeout", type=int, default=300,
                   help="seconds to wait on the first page for the challenge (default: %(default)s)")
    s.set_defaults(func=scrape)

    h = sub.add_parser("history", help="save every revision of the articles you touched")
    h.add_argument("--user", default="rtanglao", help="SUMO user name (default: %(default)s)")
    h.add_argument("--since", default="2026-06-01", metavar="YYYY-MM-DD",
                   help="articles with one of your revisions on or after this date "
                        "(default: %(default)s)")
    h.add_argument("--delay", type=float, default=2.0,
                   help="seconds to wait between page loads (default: %(default)s)")
    h.add_argument("--refresh", action="store_true",
                   help="download revisions again, also if they are already saved")
    h.add_argument("--headed", action="store_true", help="show the browser window")
    h.add_argument("--profile-dir", default=".kb_revisions_browser",
                   help="browser profile folder that keeps cookies (default: %(default)s)")
    h.add_argument("--challenge-timeout", type=int, default=300,
                   help="seconds to wait on the first page for the challenge "
                        "(default: %(default)s)")
    h.set_defaults(func=history)

    r = sub.add_parser("report", help="list articles with approved revisions")
    r.add_argument("--user", default="rtanglao", help="SUMO user name (default: %(default)s)")
    r.add_argument("--approved-since", required=True, metavar="YYYY-MM-DD",
                   help="first review date to include")
    r.set_defaults(func=report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
