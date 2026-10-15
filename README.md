# PAIR: Appeal Copilot

PAIR helps a patient or caregiver respond to a Medicare Advantage prior authorization denial. You give it the denial letter and your records. It checks each requirement in the Medicare coverage rule (NCD or LCD) that applies, lists the evidence you still need, and drafts an appeal letter where every sentence quotes the policy clause and the record line it relies on. It also gives a strength estimate with a range, and tells you to talk to a counselor when it isn't sure.

The language model only reads and words things. A checklist written as code decides whether each requirement is met, and a verifier checks every sentence in the letter against its sources.

**Status:** Phase 0. This is a project scaffold only, with no pipeline code yet.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
make setup   # install the pinned environment
make test    # run the tests with coverage
make help    # list all targets
```

## Data and privacy

PAIR is built and tested on synthetic patients only. No real patient data goes into this repository, its tests or its logs. Downloaded datasets live under `data/`, which is gitignored.

## Not legal or medical advice

PAIR is a research prototype. Review any letter it drafts before sending it, and contact your State Health Insurance Assistance Program (SHIP) for free help with an appeal.

## License

PAIR's code is MIT licensed (see `LICENSE`). Third-party data and models carry their own terms, which will be listed here as they are added. [TODO: IMR noncommercial terms, MiniCheck CC BY-NC, MCD AMA/CPT terms]
