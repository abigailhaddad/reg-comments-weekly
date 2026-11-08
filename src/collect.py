"""Weekly comment counts per docket, from the spicy-regs mirror of regulations.gov.

Reads three parquet files over HTTP range requests (no download, no API key):
  comments.parquet   one row per comment: docket_id, agency_code, posted_date, receive_date, ...
  dockets.parquet    docket_id, title, docket_type, ...
  documents.parquet  docket_id, comment_start_date, comment_end_date, ...

Counts are by POSTED date (the day the agency made the comment public), not the day it was
submitted. Submitted dates are incomplete for recent days because agencies post late, and
agencies often post in bulk, so a jump here can mean a backlog was released, not a surge of
public interest. The report flags weeks where most of a docket's posts came on one day.

A week is Monday to Sunday, by the date part of posted_date.
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb

SOURCE = "https://r2.spicy-regs.dev"
N_PRIOR = 4          # prior weeks averaged to judge a jump
MIN_CANDIDATE = 200  # comments in the week before a docket is considered for any section


def week_bounds(today: date) -> tuple[date, date]:
    """The most recent complete Monday-to-Sunday week strictly before `today`."""
    end = today - timedelta(days=today.weekday() + 1)
    return end - timedelta(days=6), end


def quote_list(ids: list[str]) -> str:
    return ",".join("'" + i.replace("'", "''") + "'" for i in ids)


def freshness(con, src: str, today: date) -> str:
    """Latest posted date in the mirror (ignoring junk future dates)."""
    return con.sql(f"""select max(substr(posted_date, 1, 10))
        from read_parquet('{src}/comments.parquet')
        where substr(posted_date, 1, 10) <= '{today.isoformat()}'""").fetchall()[0][0]


def weekly_counts(con, src: str, ws: date, we: date) -> list[dict]:
    """Every docket with posts in the week: this week, last week, and the mean of the 4 weeks before."""
    lo = ws - timedelta(days=7 * N_PRIOR)
    pws = ws - timedelta(days=7)
    rows = con.sql(f"""
        WITH c AS (
          SELECT docket_id, agency_code, CAST(substr(posted_date, 1, 10) AS DATE) AS d
          FROM read_parquet('{src}/comments.parquet')
          WHERE substr(posted_date, 1, 10) BETWEEN '{lo}' AND '{we}'
        )
        SELECT docket_id, any_value(agency_code),
               sum((d BETWEEN DATE '{ws}' AND DATE '{we}')::INT),
               sum((d BETWEEN DATE '{pws}' AND DATE '{ws - timedelta(days=1)}')::INT),
               sum((d BETWEEN DATE '{lo}' AND DATE '{ws - timedelta(days=1)}')::INT) / {N_PRIOR}.0
        FROM c GROUP BY 1
        HAVING sum((d BETWEEN DATE '{ws}' AND DATE '{we}')::INT) > 0
        ORDER BY 3 DESC, 1""").fetchall()
    return [{"docket_id": r[0], "agency": r[1], "this_week": int(r[2]), "prior_week": int(r[3]),
             "prior_avg": float(r[4])} for r in rows]


def week_totals(con, src: str, ws: date, we: date) -> dict:
    """Comments posted in the week and the week before, and how many dockets had any."""
    pws = ws - timedelta(days=7)
    r = con.sql(f"""
        SELECT sum((substr(posted_date, 1, 10) BETWEEN '{ws}' AND '{we}')::INT),
               sum((substr(posted_date, 1, 10) BETWEEN '{pws}' AND '{ws - timedelta(days=1)}')::INT),
               count(DISTINCT CASE WHEN substr(posted_date, 1, 10) BETWEEN '{ws}' AND '{we}' THEN docket_id END)
        FROM read_parquet('{src}/comments.parquet')
        WHERE substr(posted_date, 1, 10) BETWEEN '{pws}' AND '{we}'""").fetchall()[0]
    return {"this_week": int(r[0] or 0), "prior_week": int(r[1] or 0), "dockets": int(r[2] or 0)}


def busiest_day(con, src: str, ids: list[str], ws: date, we: date) -> dict[str, tuple[str, int]]:
    """For each docket, the day with the most posts in the week and that day's count."""
    rows = con.sql(f"""
        SELECT docket_id, substr(posted_date, 1, 10) AS d, count(*) AS n
        FROM read_parquet('{src}/comments.parquet')
        WHERE docket_id IN ({quote_list(ids)}) AND substr(posted_date, 1, 10) BETWEEN '{ws}' AND '{we}'
        GROUP BY 1, 2""").fetchall()
    best: dict[str, tuple[str, int]] = {}
    for docket, d, n in rows:
        if docket not in best or n > best[docket][1]:
            best[docket] = (d, int(n))
    return best


def history(con, src: str, ids: list[str]) -> dict[str, dict]:
    """Total comments in the mirror and the first posted date (dates before 1990 are junk)."""
    rows = con.sql(f"""
        SELECT docket_id, count(*),
               min(CASE WHEN substr(posted_date, 1, 4) >= '1990' THEN substr(posted_date, 1, 10) END)
        FROM read_parquet('{src}/comments.parquet')
        WHERE docket_id IN ({quote_list(ids)})
        GROUP BY 1""").fetchall()
    return {r[0]: {"total": int(r[1]), "first_posted": r[2]} for r in rows}


def docket_info(con, src: str, ids: list[str]) -> dict[str, dict]:
    """Title, type, and the latest comment-period end date among the docket's documents."""
    info = {i: {"title": "", "type": "", "closes": None} for i in ids}
    for docket, title, kind in con.sql(f"""
            SELECT docket_id, any_value(title), any_value(docket_type)
            FROM read_parquet('{src}/dockets.parquet')
            WHERE docket_id IN ({quote_list(ids)}) GROUP BY 1""").fetchall():
        info[docket].update(title=title or "", type=kind or "")
    for docket, closes in con.sql(f"""
            SELECT docket_id, max(substr(comment_end_date, 1, 10))
            FROM read_parquet('{src}/documents.parquet')
            WHERE docket_id IN ({quote_list(ids)})
              AND substr(comment_end_date, 1, 4) BETWEEN '2000' AND '2100'
            GROUP BY 1""").fetchall():
        info[docket]["closes"] = closes
    return info


def collect(today: date, src: str = SOURCE) -> dict:
    con = duckdb.connect()
    ws, we = week_bounds(today)
    counts = weekly_counts(con, src, ws, we)
    cands = [c for c in counts if c["this_week"] >= MIN_CANDIDATE]
    ids = [c["docket_id"] for c in cands]
    extra = ({"busiest": busiest_day(con, src, ids, ws, we), "history": history(con, src, ids),
              "info": docket_info(con, src, ids)} if ids else {"busiest": {}, "history": {}, "info": {}})
    return {"week_start": ws, "week_end": we, "today": today, "counts": counts, "candidates": cands,
            "totals": week_totals(con, src, ws, we), "data_through": freshness(con, src, today), **extra}
