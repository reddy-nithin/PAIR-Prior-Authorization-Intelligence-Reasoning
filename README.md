# PAIR: Appeal Copilot

PAIR helps a patient or caregiver respond to a Medicare Advantage prior authorization denial. You give it the denial letter and your records. It checks each requirement in the Medicare coverage rule (NCD or LCD) that applies, lists the evidence you still need, and drafts an appeal letter where every sentence quotes the policy clause and the record line it relies on. It also gives a strength estimate with a range, and tells you to talk to a counselor when it isn't sure.

The language model only reads and words things. A checklist written as code decides whether each requirement is met, and a verifier checks every sentence in the letter against its sources.

**Status:** Phase 1. Typed contracts, three policy checklists quoted from CMS, and a typed loader for real appeal outcomes are in place. The pipeline itself comes next.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
make setup   # install the pinned environment
make test    # run the tests with coverage
make help    # list all targets
```

## Data and privacy

PAIR is built and tested on synthetic patients only. No real patient data goes into this repository, its tests or its logs. Downloaded datasets live under `data/`, which is gitignored. `make data` fetches:

- **CMS Medicare Coverage Database** exports (NCDs and LCDs). Policy clauses in `policies/*.yaml` are quoted from them word for word, and a test checks every quote against the download.
- **California DMHC Independent Medical Review determinations** (42,749 decisions since 2001), used for historical appeal base rates. These are California commercial-plan reviews, not Medicare. See `docs/data/imr-schema.md`.

## Current policy coverage

| Policy | Sources | What is modeled |
|---|---|---|
| PAP devices for sleep apnea | NCD 240.4, LCD L33718 | E0601 initial coverage and continued use (adherence, re-evaluation) |
| Home oxygen | NCD 240.2, LCD L33797 | Group I testing at rest and Group II; not sleep or exercise testing, not Group III |
| Facet joint interventions | LCD L38841 (WPS) | General indications and the diagnostic-block requirement before initial RFA |

## Not legal or medical advice

PAIR is a research prototype. Review any letter it drafts before sending it, and contact your State Health Insurance Assistance Program (SHIP) for free help with an appeal.

## License

PAIR's code is MIT licensed (see `LICENSE`). Third-party data and models carry their own terms:

- MCD exports: LCD text can reference CPT codes, which are AMA copyright. PAIR quotes coverage text only and doesn't redistribute CPT descriptors.
- IMR data: used for noncommercial research and never redistributed. [TODO: quote the CHHS portal terms]
- [TODO: MiniCheck CC BY-NC, when the verifier is added]

Thanks to [Fight Health Insurance](https://github.com/fighthealthinsurance/fighthealthinsurance) (Apache 2.0), whose open IMR work showed this dataset's value for appeals. PAIR's loaders are written separately.
