# reg-comments-weekly

A weekly look at which regulations.gov dockets are drawing comments: the busiest ones, new ones, sudden jumps, and comment periods about to close.

Counts come from the [spicy-regs](https://github.com/civictechdc/spicy-regs) mirror of regulations.gov, read straight from its public parquet files. The counts involve no model; the optional sampled summaries (below) do. Unofficial; not affiliated with regulations.gov.

## How it works

A GitHub Action runs Tuesday mornings. `src/collect.py` counts the comments posted in the last complete Monday-to-Sunday week, per docket, and compares them with the week before and the average of the four weeks before that. `src/report.py` turns that into a digest by fixed rules (the thresholds are named constants at the top of the file). `src/run.py` writes `digests/<week>.md` and a CSV of every docket that week in `digests/data/`, and the Action posts the digest as a GitHub issue.

Things to know before you read a digest:
- **"Posted" is when the agency made a comment public, not when someone submitted it.** Recent submission dates are incomplete because agencies post late.
- **Agencies often post in batches.** A docket whose week is mostly one day gets a "likely a batch" note. A big number then means a backlog was released.
- **The mirror can run a little below regulations.gov.** `scripts/validate_against_api.py` compares a week with the API and writes the result to `proof/`. Run it with your own key (`REGULATIONS_GOV_API_KEY`); the shared demo key allows only a few calls an hour.
- **Dockets with few comments in the week are left out** of the sections, though they're in the CSV.

## Sampled summaries (optional)

With `--samples K`, the run also draws a random sample of comments (25 by default) for each of the top K dockets and has Claude Sonnet 5.5 summarize what they say. It needs `ANTHROPIC_API_KEY` (and `ANTHROPIC_WORKSPACE_ID` if your key needs one); the Action turns it on only when that secret exists. What the model does and doesn't do:
- The sample is deterministic (ordered by md5 of the comment ID and the week), so it can be redrawn. `digests/samples/<week>.json` holds the comment IDs, text hashes, labels and themes, not the comment text, so a reader can check any comment on regulations.gov.
- Form letters are found by script (word-triplet similarity), not by the model. In a first test the model called four comments "identical" when none were exact copies.
- The model labels each comment's stance and groups comments into themes. Stance counts are computed by script from those labels, and Claude Haiku 5.5 labels stance independently; the digest says how often the two agreed. Theme counts are the model's grouping and approximate.
- The model is told not to quote comments or repeat names or other personal details, and emails and phone numbers are removed before any text goes to a model. That instruction isn't enforced by code, so skim a digest before you publish it.
- A sample of 25 is not a poll.

## Running

    python -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python src/run.py                          # last complete week
    .venv/bin/python src/run.py --today 2026-11-10       # pretend it's another day
    ANTHROPIC_API_KEY=... .venv/bin/python src/run.py --samples 3   # add sampled summaries for the top 3 dockets
    .venv/bin/python scripts/validate_against_api.py --week 2026-10-26
    .venv/bin/pip install pytest && .venv/bin/python -m pytest tests

`agency_names.json` is a snapshot of regulations.gov's agency list, copied from [regulations-comment-explorer](https://github.com/abigailhaddad/regulations-comment-explorer).

## License

MIT (see `LICENSE`).
