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

### Known limits

The Step 7 rule review ([docs/audit/rule-review.md](docs/audit/rule-review.md), [ADR-0015](docs/decisions/0015-rule-review-changes.md)) left these out of the rules on purpose:

- **PAP:** a re-evaluation after day 91 counts, but coverage restarts only from that visit's date; PAIR says so in the criterion text and doesn't compute the gap. The 120-day deadline for an E0470 swap, the trial pause for a hospital or nursing-facility stay, and whether the face-to-face evaluation before the sleep test or the re-evaluation was in person, with the treating practitioner, aren't modeled. PAIR checks only their dates.
- **Facet joint:** PAIR doesn't check that the same pain scale was used at baseline, after each diagnostic block and at each follow-up (L38841 footnote). Blocks less than 2 weeks apart come out unmet even when the record documents the clinical exception the LCD allows.

### Interpretations

The policy text doesn't settle these points, so PAIR picks a reading. Each one is PAIR's choice, not CMS guidance:

- **Facet "moderate" pain:** L38841 gives no number. PAIR treats a pain score of 4 or more out of 10, or a verbal "moderate" or "severe" rating, as moderate to severe. Boonstra et al. 2014 put the start of "moderate" at 3.5, so a score of 3.5 comes out unmet under PAIR's cut-off.
- **PAP re-evaluation window:** L33718 says "no sooner than the 31st day but no later than the 91st day" without saying how to count. PAIR counts the start date as day 1, so the visit must be at least 30 days after the start.
- **Facet baseline disability scale and sustained relief:** PAIR requires a baseline disability scale and block relief that lasted as long as the agent should. Both follow the LCD's wording, but notes rarely state them, so many facet records come out insufficient. The two Step 7 critics read the baseline disability requirement differently; PAIR applies it because every facet request it handles is for treatment.

## Not legal or medical advice

PAIR is a research prototype. Review any letter it drafts before sending it, and contact your State Health Insurance Assistance Program (SHIP) for free help with an appeal.

## License

PAIR's code is MIT licensed (see `LICENSE`). Third-party data and models carry their own terms:

- MCD exports: LCD text can reference CPT codes, which are AMA copyright. PAIR quotes coverage text only and doesn't redistribute CPT descriptors.
- IMR data: used for noncommercial research and never redistributed. [TODO: quote the CHHS portal terms]
- [TODO: MiniCheck CC BY-NC, when the verifier is added]

Thanks to [Fight Health Insurance](https://github.com/fighthealthinsurance/fighthealthinsurance) (Apache 2.0), whose open IMR work showed this dataset's value for appeals. PAIR's loaders are written separately.
