# IMR dataset schema

Source: California Department of Managed Health Care (DMHC), "Independent Medical Review (IMR) Determinations, Trend", via the [CHHS Open Data Portal](https://data.chhs.ca.gov/dataset/independent-medical-review-imr-determinations-trend). Downloaded by `scripts/download_imr.py` (`make data`). The data is never committed or redistributed.

## Snapshot this schema was written against

| Fact | Value |
|---|---|
| Retrieved | 2026-10-15 (portal resource last modified 2026-06-01) |
| SHA-256 | `f68951823f6ffc09566cc190d97b2808e0269a069843efe809a3f5f90d4c893b` |
| Rows | 42,749 |
| Columns | 14 |
| Report years | 2001 to 2026 (2026 is partial: 546 rows) |
| Overturned | 52.5% (22,445 overturned, 20,304 upheld) |
| Planned time split | train ≤2022: 34,512 · calibrate 2023: 2,246 · test ≥2024: 5,991 |

If the portal updates the file, `tests/score/test_imr_data.py::test_real_dataset_matches_documented_schema` skips with a message to refresh this page.

## Columns

Role decides what code may do with a column. Only `feature` and `year` columns reach the strength model. `load_imr_features` never reads the post-decision or findings columns from disk.

| Column | Loaded as | Role | Meaning | Levels / missing |
|---|---|---|---|---|
| `ReferenceID` | string | id | Unique case id, e.g. `MN26-46990` | |
| `ReportYear` | Int16 → `report_year` | year | Year the case was reported | 2001 to 2026 |
| `DiagnosisCategory` | category | feature | Main diagnosis category | 48 / 0 |
| `DiagnosisSubCategory` | category | feature | Secondary diagnosis category | 532 / 2 |
| `TreatmentCategory` | category | feature | Main treatment category, e.g. `DME` | 58 / 0 |
| `TreatmentSubCategory` | category | feature | Secondary treatment category | 498 / 1 |
| `Determination` | Int8 → `label` | label | `Overturned Decision of Health Plan` = 1, `Upheld Decision of Health Plan` = 0 | 2 / 0 |
| `Type` | category | feature | Case type: Medical Necessity, Experimental/Investigational, Urgent Care | 3 / 0 |
| `AgeRange` | category | feature | Age band, e.g. `51 to 64` | 7 / 691 |
| `PatientGender` | category | feature | Female, Male, Other | 3 / 691 |
| `IMRType` | category | feature | Review track: Standard or Expedited, set when the case is filed | 2 / 0 |
| `DaysToReview` | (not loaded) | post_decision | Days the review took | |
| `DaysToAdopt` | (not loaded) | post_decision | Days until the decision was adopted | |
| `Findings` | (not loaded as a feature) | findings | Reviewer's written summary, written after the decision | mean 1,811 characters |

Blank `AgeRange` and `PatientGender` values (the same 691 rows) load as missing, not as an empty category.

## Leakage rules

- `Findings`, `DaysToReview` and `DaysToAdopt` only exist once the review is over, so they would leak the outcome into the model. They are never features. A test checks both the constant lists and the loaded frame.
- `Findings` is available only through `load_imr_findings`, for mining argument patterns used as drafting examples (spec §5.4).
- Any new column in a future file makes the loader fail until it is reviewed and added to `IMR_SCHEMA` with a role.

## Differences from the official data dictionary

The portal's data dictionary PDF (last updated 2020-05-06) no longer matches the file:

- It lists a numeric `PaientAge` (sic). The file has a banded `AgeRange` instead.
- It doesn't list `IMRType`, `DaysToReview` or `DaysToAdopt`.
- The spec's "IMR type (medical necessity / experimental-investigational / urgent care)" is the `Type` column. `IMRType` is the Standard/Expedited track.

## Terms

The CKAN metadata for this dataset has no license field. PAIR uses the data for noncommercial research only, and doesn't redistribute it or altered copies of it (spec §5.1).
