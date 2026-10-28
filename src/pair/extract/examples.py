"""Few-shot examples for LangExtract, one synthetic note per policy (no real PHI).

Extraction classes are the checklist's rule variables. Each extraction carries
two attributes: ``value`` (the normalizable value; for bools, the variable's own
truth, ADR-0012) and ``status`` (asserted / negated / uncertain). Every
``extraction_text`` is copied verbatim from the example text (tested).
"""

from langextract import data as lx

Example = lx.ExampleData


def _x(cls: str, text: str, value: str, status: str = "asserted") -> lx.Extraction:
    """One example extraction."""
    return lx.Extraction(cls, text, attributes={"value": value, "status": status})


_PAP_TEXT = (
    "SYNTHETIC EXAMPLE. Sleep medicine visit 01/12/2026: seen in person for loud snoring and witnessed apneas. "
    "Reports daytime sleepiness. Denies morning headaches.\n"
    "Home sleep test 02/02/2026: total recording time 6.1 hours, AHI 22.4 events/hour, "
    "131 total respiratory events.\n"
    "CPAP started 02/20/2026. Device download, 30 consecutive days within the first 3 months: "
    "used 4 hours or more on 76% of nights.\n"
    "Follow-up visit 04/01/2026: sleepiness much improved on CPAP."
)

_OXYGEN_TEXT = (
    "SYNTHETIC EXAMPLE. Pulmonology visit 03/03/2026: I ordered resting oximetry and reviewed the results "
    "with the patient. Outpatient, no recent hospital stay. Tested during this visit while short of breath. "
    "Arterial blood gas 03/03/2026 at rest on room air: PaO2 54 mmHg, SpO2 87%. "
    "Testing was performed by the hospital's clinical laboratory. "
    "Mild ankle edema. No pulmonary hypertension on echo. "
    "Plan: home oxygen is expected to improve dyspnea and exercise tolerance."
)

_OXYGEN_INPATIENT_TEXT = (
    "SYNTHETIC EXAMPLE. Hospital discharge summary: admitted for a COPD exacerbation. "
    "Arterial blood gas 04/13/2026 at rest on room air: PaO2 53 mmHg. The inpatient laboratory ran the study. "
    "Discharged home 04/14/2026 on 2 L oxygen."
)

_OXYGEN_SUPPLIER_TEXT = (
    "SYNTHETIC EXAMPLE. Overnight oximetry 05/02/2026 done at home by a respiratory therapist from the "
    "home medical equipment company that supplies the oxygen."
)

_FACET_TEXT = (
    "SYNTHETIC EXAMPLE. Pain clinic 05/10/2026: chronic axial low back pain for 8 months, rated 7/10, "
    "described as severe, "
    "limits walking and work (ODI 42%), taken as the baseline disability scale. "
    "Failed 12 weeks of physical therapy and NSAIDs. "
    "No radicular symptoms; straight leg raise negative; no neurogenic claudication; no synovial cyst on MRI. "
    "MRI: facet arthropathy L4-5, no fracture, tumor or infection. "
    "Two medial branch blocks each gave 85% relief, lasting about 6 hours as expected for bupivacaine. "
    "First block 03/02/2026, second block 03/23/2026."
)

EXAMPLES: dict[str, list[Example]] = {
    "pap-osa": [
        Example(
            text=_PAP_TEXT,
            extractions=[
                _x("evaluation_date", "Sleep medicine visit 01/12/2026", "2026-01-12"),
                _x("symptoms_or_conditions", "loud snoring", "snoring"),
                _x("symptoms_or_conditions", "daytime sleepiness", "daytime sleepiness"),
                _x("symptoms_or_conditions", "morning headaches", "morning headaches", "negated"),
                _x("sleep_test_date", "Home sleep test 02/02/2026", "2026-02-02"),
                _x("sleep_or_recording_hours", "total recording time 6.1 hours", "6.1"),
                _x("ahi", "AHI 22.4 events/hour", "22.4"),
                _x("event_count", "131 total respiratory events", "131"),
                _x("therapy_start_date", "CPAP started 02/20/2026", "2026-02-20"),
                _x("window_in_first_90_days", "30 consecutive days within the first 3 months", "true"),
                _x("pct_nights_4h_best_30d", "used 4 hours or more on 76% of nights", "76"),
                _x("reevaluation_date", "Follow-up visit 04/01/2026", "2026-04-01"),
                _x("symptoms_improved", "sleepiness much improved on CPAP", "true"),
            ],
        )
    ],
    "home-oxygen": [
        Example(
            text=_OXYGEN_TEXT,
            extractions=[
                _x("practitioner_ordered_and_reviewed", "I ordered resting oximetry and reviewed the results", "true"),
                _x("rx_from_inpatient_stay", "Outpatient, no recent hospital stay", "false"),
                _x("symptoms_noted_at_test", "Tested during this visit while short of breath", "true"),
                _x("test_date", "Arterial blood gas 03/03/2026", "2026-03-03"),
                _x("tested_by_qualified_provider", "Testing was performed by the hospital's clinical laboratory", "true"),
                _x("at_rest_on_room_air", "at rest on room air", "true"),
                _x("pao2", "PaO2 54 mmHg", "54"),
                _x("spo2", "SpO2 87%", "87"),
                _x("group2_conditions", "Mild ankle edema", "edema"),
                _x("group2_conditions", "pulmonary hypertension", "pulmonary hypertension", "negated"),
                _x("expected_to_improve", "home oxygen is expected to improve dyspnea", "true"),
            ],
        ),
        Example(
            text=_OXYGEN_INPATIENT_TEXT,
            extractions=[
                _x("rx_from_inpatient_stay", "admitted for a COPD exacerbation", "true"),
                _x("test_date", "Arterial blood gas 04/13/2026", "2026-04-13"),
                _x("at_rest_on_room_air", "at rest on room air", "true"),
                _x("pao2", "PaO2 53 mmHg", "53"),
                _x("tested_by_qualified_provider", "The inpatient laboratory ran the study", "true"),
                _x("discharge_date", "Discharged home 04/14/2026", "2026-04-14"),
            ],
        ),
        Example(
            text=_OXYGEN_SUPPLIER_TEXT,
            extractions=[
                _x("test_date", "Overnight oximetry 05/02/2026", "2026-05-02"),
                _x(
                    "tested_by_qualified_provider",
                    "by a respiratory therapist from the home medical equipment company that supplies the oxygen",
                    "false",
                ),
            ],
        ),
    ],
    "facet-joint": [
        Example(
            text=_FACET_TEXT,
            extractions=[
                _x("pain_is_axial", "axial low back pain", "true"),
                _x("pain_duration_months", "for 8 months", "8"),
                _x("pain_score", "rated 7/10", "7"),
                _x("pain_severity_verbal", "described as severe", "severe"),
                _x("functional_deficit_documented", "limits walking and work (ODI 42%)", "true"),
                _x("disability_scale_at_baseline", "taken as the baseline disability scale", "true"),
                _x("conservative_care_failed", "Failed 12 weeks of physical therapy and NSAIDs", "true"),
                _x("untreated_radiculopathy", "No radicular symptoms", "false"),
                _x("untreated_neurogenic_claudication", "no neurogenic claudication", "false"),
                _x("radiculopathy_from_synovial_cyst", "no synovial cyst on MRI", "false"),
                _x("other_pathology_found", "no fracture, tumor or infection", "false"),
                _x("blocks_with_80pct_relief", "Two medial branch blocks each gave 85% relief", "2"),
                _x("relief_duration_consistent_with_agent", "lasting about 6 hours as expected for bupivacaine", "true"),
                _x("first_block_date", "First block 03/02/2026", "2026-03-02"),
                _x("second_block_date", "second block 03/23/2026", "2026-03-23"),
            ],
        )
    ],
}


def examples_for(policy_id: str) -> list[Example]:
    """The few-shot examples for a policy.

    Raises:
        KeyError: If the policy has no examples.
    """
    return EXAMPLES[policy_id]
