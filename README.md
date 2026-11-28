# reg-comments-weekly

A weekly look at which regulations.gov dockets are drawing public comments: the busiest ones, new ones, sudden jumps, and comment periods about to close. Unofficial; not affiliated with regulations.gov.

## Links

- Website and RSS feed: [reg-comments-weekly.abigailhaddad.com](https://reg-comments-weekly.abigailhaddad.com)
- How this is made: [reg-comments-weekly.abigailhaddad.com/about](https://reg-comments-weekly.abigailhaddad.com/about)
- Sign up (Federal Data Stories, topic "Regulations.gov weekly"): [data-stories.abigailhaddad.com](https://data-stories.abigailhaddad.com/#subscribe)
- Data source: the [spicy-regs](https://github.com/civictechdc/spicy-regs) mirror of regulations.gov

## How it works

- Weekly run: [run.py](src/run.py), scheduled by [weekly.yml](.github/workflows/weekly.yml), which commits [digests/](digests) and opens the digest as a GitHub issue
- Counts: [collect.py](src/collect.py); digest rules: [report.py](src/report.py)
- Rules, prompts and model settings: [config/reg-comments-weekly.yaml](config/reg-comments-weekly.yaml)
- Optional Claude text, checked in code: [opening.py](src/opening.py) (opening paragraph), [sample.py](src/sample.py) (sampled comment summaries). The sample instructions not to quote or name commenters are not enforced by code, so skim a digest before publishing it.
- Mirror vs. regulations.gov API check: [scripts/validate_against_api.py](scripts/validate_against_api.py), results in [proof/](proof)
- Website: [build_site.py](src/build_site.py), deployed by [site.yml](.github/workflows/site.yml)

## Running locally

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/run.py --help
.venv/bin/pip install pytest && .venv/bin/python -m pytest tests
```

## License

MIT (see [LICENSE](LICENSE)).
