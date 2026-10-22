# Critic research: how reviewers audit, and how AI judges fail

Retrieved 2026-10-22. This file is the evidence base for the audit critic ([ADR-0013](../decisions/0013-adversarial-critic-for-audits.md)) and its rubric ([critic-rubric.md](critic-rubric.md)). Primary sources come first. Anything taken from a secondary source or not yet confirmed is marked **unverified**.

## 1. How Medicare reviewers judge a record against an LCD

**Clinical review judgment has two steps.** In Program Integrity Manual (PIM) ch. 3, the reviewer first builds a clinical picture from the whole record, then applies the policy to that picture. Judgment can't make up for missing documentation, and it can't override a policy requirement. LCDs and their policy articles count as policy. Reviews are done by licensed nurses, therapists or physicians.
- Sources: CMS transmittal R11529PI (2022), https://hhs.gov/guidance/sites/default/files/hhs-guidance-documents/R11529PI.pdf, and PIM ch. 3, https://www.cms.gov/Regulations-and-Guidance/Guidance/Manuals/Downloads/pim83c03.pdf

**What the critic takes from this:**
- A fact counts only if the record states it. A plausible inference doesn't count.
- The policy text is the standard, so the critic never "relaxes" a criterion on clinical grounds.
- Gold labels must say "insufficient" when a fact is missing, never "met".

**Contractors publish documentation checklists.** Noridian's JD DME PAP checklist (last updated 9/30/2026) lists the sleep test as "AHI or RDI ≥ 15 events per hour with a minimum of 30 events; or AHI or RDI ≥ 5 and ≤ 14 events per hour with minimum 10 events and documentation of..." and the "F2F re-evaluation by the treating physician between the 31st and 91st day after initiating" therapy.
- Source: https://med.noridianmedicare.com/documents/2230715/26734435/Documentation+Checklist+-+Positive+Airway+Pressure+(PAP).pdf
- **What the critic takes from this:** a contractor checklist is the closest public stand-in for how a reviewer reads the LCD. The critic checks a case against both the LCD and the checklist.

**Medicare Advantage plans must use fully established Medicare criteria.** Under 42 CFR 422.101(b)(6), added by CMS-4201-F, a plan can't add internal criteria when an NCD or LCD fully sets the criteria.
- **Unverified:** this comes from secondary summaries, e.g. King & Spalding, https://kslaw.com/news-and-insights/new-medicare-advantage-regulations-add-provider-and-beneficiary-protections-against-plan-utilization-management-policies. Check it against eCFR before quoting it in the letter template.

## 2. The three rule questions (primary text from the MCD export, `data/raw/mcd/`)

### 2a. PAP minimum event counts (`pap-osa.yaml` `ahi_threshold`)
LCD L33718 v52, Coverage Indications, says it in two places:
- In the criteria: "greater than or equal to 15 events per hour with a minimum of 30 events; or ... 5 and less than or equal to 14 events per hour with a minimum of 10 events and documentation of..."
- In the definitions: "If the AHI or RDI is calculated based on less than 2 hours of sleep or recording time, the total number of recorded events used to calculate the AHI or RDI (respectively) must be at least the number of events that would have been required in a 2 hour period (i.e., must reach ≥30 events without symptoms or ≥10 events with symptoms)."

The arithmetic: 30 events is 15 per hour times 2 hours, and 10 events is 5 per hour times 2 hours. Over any recording of 2 hours or more, an AHI at the threshold already implies the minimum count. Our rule requires an explicit `event_count` for every test, so a full-night study that reports only the AHI comes out "insufficient". The LCD's own explanation suggests that's stricter than reviewers apply. The Step 7 rule review decides.

### 2b. PAP re-evaluation window (`pap-osa.yaml` `reevaluation`)
- **L33718 v52:** "no sooner than the 31st day but no later than the 91st day after initiating therapy."
- **Noridian policy reminder** (last updated Nov 4, 2016) has the same wording. It adds that if the re-evaluation happens after day 91 and shows benefit, coverage resumes from that date. It also says a hospital or SNF stay suspends the trial period. Source: https://med.noridianmedicare.com/web/jddme/policies/dmd-articles/policy-reminder-pap-devices-continued-coverage-beyond-the-first-three-months-of-therapy
- **CGS physician guide:** "Between the 31st and 91st day after initiating PAP therapy." Source: https://cgsmedicare.com/pdf/dme_ordering/pap_devices.pdf
- **No source says whether the start date is day 0 or day 1.** Our rule (ADR-0012) reads the start as day 1, so a gap of 30 days is the 31st day. If the start is day 0 instead, the window is a gap of 31 to 91 days. The two readings differ only for a re-evaluation exactly 30 days or 91 days after start. This is a real ambiguity in the policy, not an error.

### 2c. Facet "moderate" pain (`facet-joint.yaml` `pain_and_function`)
- **LCD L38841 v20:** "Moderate to severe chronic neck or low back pain, predominantly axial, that causes functional deficit measured on pain or disability scale*". The footnote names acceptable scales (verbal rating, NRS, VAS for pain; PDAS, ODI, Roland Morris and others for disability). It requires the same pain scale at baseline and at each follow-up, and a disability scale at baseline. **The LCD gives no numeric cut-off for "moderate."**
- **Published cut points disagree.** The NRS (Numeric Rating Scale) is the 0 to 10 pain score, where 0 is no pain and 10 is the worst imaginable.

| Study | Population | Moderate band |
|---|---|---|
| Serlin et al. 1995, *Pain* 61:277 | 470 cancer patients, worst pain vs interference | 5 to 6 (mild 1 to 4) |
| Paul et al. 2005 (unverified, via the review below) | cancer pain | 5 to 7 |
| Boonstra et al. 2016, *Front Psychol* | chronic musculoskeletal pain | 6 to 7 overall; 4 to 6 in low-catastrophizing patients |

  Sources: Boonstra 2016, https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5043012/. A review of cut points, https://apm.amegroups.org/article/view/7959/8893.
- **What follows:** a cut-off of 4 is a common clinical convention, and it matches one subgroup, but it's the most lenient reading in the literature. The rule review has to choose and document a threshold. It also has to decide what happens when only a disability scale is given, since the LCD accepts "pain or disability scale."

## 3. Judging synthetic clinical notes

**PDQI-9.** The Physician Documentation Quality Instrument has 9 items, each scored 1 to 5: up to date, accurate, thorough, useful, organized, comprehensible, succinct, synthesized, internally consistent. It has an inter-rater ICC of 0.83 (ICC measures how much two raters agree; 1 is perfect).
- Source: Stetson et al. 2012, https://pmc.ncbi.nlm.nih.gov/articles/PMC3347480
- **What the critic takes from this:** the realism check uses the items that matter for synthetic notes (accurate, internally consistent, organized, synthesized) rather than an open-ended "does it sound real."

**Known failure patterns in AI-written notes:**
- **Context and time:** misread clinical context, timing confusion, wrong measurements and invented claims (CSIRO/NLM preprint, May 2026, https://arxiv.org/pdf/2605.17775).
- **Section patterns:** errors cluster in Plan sections, while omissions cluster in exam and HPI (ED discharge-summary study, via search summary; **unverified**).
- **Planted errors spread:** models repeat or elaborate on a planted wrong value in up to 83% of cases (via search summary; **unverified**).

What the critic looks for:
- dates out of order
- values that contradict each other across documents
- vital signs or lab values that are physiologically impossible
- template echo, where the case spec's wording leaks into a note
- missing standard sections, such as a sleep report with an AHI but no recording time

## 4. How AI judges fail, and the counter-measures

**Leniency is the main failure.**
- *Judging the Judges* (Thakur et al., GEM 2025, https://arxiv.org/abs/2406.12624) found a bias toward leniency even in the best judges. It also found that a high percent agreement can hide large score gaps, so Cohen's kappa should be reported too. Kappa is agreement corrected for chance: 0 means chance-level, 1 means perfect.
- A NUS project page reports judges catching valid outputs more than 96% of the time but invalid outputs less than 25% of the time, and proposes a "minority veto" across judges (https://aicet.comp.nus.edu.sg/llm-as-a-judge-bias; **not peer-reviewed**).

**Other biases:**
- self-preference (judges favor text from their own model family)
- superficial-quality bias toward fluent or long text
- position bias
- Sources: survey, https://arxiv.org/pdf/2411.15594; Zhou et al., https://arxiv.org/html/2409.16788v1

**Healthcare judge studies rarely mitigate any of this.** A scoping review of 49 studies found 36 with no bias mitigation and only 1 with a structured rubric (MedJUDGE, https://arxiv.org/pdf/2604.25933).

**Testing a judge with injected errors is established practice.**
- MEDEC (https://arxiv.org/pdf/2412.19260) builds clinical notes with one injected error each, of five types: diagnosis, management, treatment, pharmacotherapy and causal organism. It scores whether the error is flagged, where it is, and how it's corrected. Doctors still beat LLMs on it.
- A 2026 follow-up (https://arxiv.org/pdf/2608.16643) pairs each error note with its clean twin, so false alarms are measured too.

## 5. Design rules derived for the critic

1. **Fail unless proven.** A pass needs a verbatim quote from the case or the policy. A pass with no quote is a fail (the counter to leniency, §4).
2. **Blind, then compare.** The critic labels each criterion from the notes alone before it sees `gold_*` or `states`, then explains each disagreement. This prevents anchoring on the answer key.
3. **Policy text is the standard.** The critic applies the LCD wording, and any contractor checklist, the way PIM clinical review judgment does. It doesn't use clinical intuition (§1).
4. **Different model family.** Claude judges cases that Gemini wrote, which limits self-preference (§4). The critic never judges PAIR output that it wrote itself.
5. **Tested before trusted.** A seeded-fault set with clean twins measures the catch rate and the false-alarm rate, as in MEDEC (§4). The fault types include the AI-note failures from §3.
6. **Report kappa.** When the critic is compared with Nithin's Phase 5 audit, report Cohen's kappa alongside percent agreement.
7. **Mechanical first.** Exact checks (spans, offsets, rule re-runs, clause text) run in tested Python, so the critic spends its judgment only on what code can't check.
