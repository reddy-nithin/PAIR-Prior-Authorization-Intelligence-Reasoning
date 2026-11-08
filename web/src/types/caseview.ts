/* Generated from src/types/caseview.schema.json by `npm run gen:types`. Do not edit. */

export type CaseId = string;
export type Critical = boolean;
export type Heading = string;
export type Id = string;
export type Clause = string;
export type Label = string;
export type Title = string;
export type Url = string;
export type CharEnd = number;
export type CharStart = number;
export type DocId = string;
export type Quote = string;
export type Quotes = SourceSpan[];
export type Icon = string;
export type Label1 = string;
/**
 * Outcome of one criterion.
 *
 * ``met``: evidence satisfies the rule. ``unmet``: evidence contradicts it.
 * ``insufficient``: no usable evidence, or only negated, vague or conflicting
 * evidence.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "CriterionStatus".
 */
export type CriterionStatus = "met" | "unmet" | "insufficient";
export type Trace = string;
export type Criteria = CriterionView[];
export type Codes = string[];
export type Date = string;
export type PolicyRef1 = string | null;
export type ReasonPlain = string;
export type ReasonText = string;
export type Service = string;
export type DocId1 = string;
export type Text = string;
export type Title1 = string;
export type Documents = DocumentView[];
export type CriterionId = string;
export type Heading1 = string;
export type Message = string;
export type Items = GapItem[];
export type Who = string;
export type GapGroups = GapGroup[];
export type Name = string;
export type Note = string;
export type Url1 = string;
export type HelpLinks = LinkView[];
export type Dropped = number;
export type CriterionId1 = string;
export type Heading2 = string;
export type Message1 = string;
export type NotArgued = NotArgued1[];
export type CriterionId2 = string;
/**
 * What the verifier decided about a sentence, in display terms.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "Decision".
 */
export type Decision = "kept" | "flagged" | "not_evaluated" | "dropped" | "quoted";
export type DecisionLabel = string;
export type LetterEnd = number | null;
export type LetterStart = number | null;
export type Score = number | null;
export type Text1 = string;
export type Sentences = SentenceView[];
export type Text2 = string;
export type Unconfirmed = SentenceView[];
export type Mode = "cached" | "live";
export type PolicyId = string | null;
export type PolicyTitle = string | null;
export type SafetyNotice = string;
export type SchemaVersion = 1;
export type Abstain = boolean;
export type BaseRate = number | null;
export type DataNote = string;
export type High = number | null;
export type Action = string;
export type CriterionId3 = string;
export type Heading3 = string;
export type PIfFixed = number | null;
export type Improve = ImproveView[];
export type Low = number | null;
export type NSimilar = number;
export type P = number | null;
export type Reason = string | null;
export type CriterionId4 = string;
export type Effect = "raises" | "lowers" | "no change";
export type Heading4 = string;
export type Steps = StepView[];
export type Supported = boolean;
export type UnsupportedReason = string | null;

/**
 * Everything the 7 screens show for one case.
 */
export interface CaseView {
  case_id: CaseId;
  criteria: Criteria;
  denial: DenialView | null;
  documents: Documents;
  gap_groups: GapGroups;
  help_links: HelpLinks;
  letter: LetterView | null;
  mode: Mode;
  overall: StatusView | null;
  policy_id: PolicyId;
  policy_title: PolicyTitle;
  run: Run;
  safety_notice: SafetyNotice;
  schema_version?: SchemaVersion;
  strength: StrengthView | null;
  supported: Supported;
  unsupported_reason: UnsupportedReason;
}
/**
 * Screen 3: one row of "where you stand".
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "CriterionView".
 */
export interface CriterionView {
  critical: Critical;
  heading: Heading;
  id: Id;
  policy: PolicyClause;
  quotes: Quotes;
  status: StatusView;
  trace: Trace;
}
/**
 * A verbatim clause and the document it is from.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "PolicyClause".
 */
export interface PolicyClause {
  clause: Clause;
  source: PolicyRef;
}
/**
 * One coverage document, e.g. ``LCD L33718``, with its MCD link.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "PolicyRef".
 */
export interface PolicyRef {
  label: Label;
  title: Title;
  url: Url;
}
/**
 * Exact characters in one record.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "SourceSpan".
 */
export interface SourceSpan {
  char_end: CharEnd;
  char_start: CharStart;
  doc_id: DocId;
  quote: Quote;
}
/**
 * A criterion status as icon name + words (color is never the only signal).
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "StatusView".
 */
export interface StatusView {
  icon: Icon;
  label: Label1;
  status: CriterionStatus;
}
/**
 * Screen 2: why they said no.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "DenialView".
 */
export interface DenialView {
  cited_rule: PolicyRef | null;
  codes: Codes;
  date: Date;
  policy_ref: PolicyRef1;
  reason_plain: ReasonPlain;
  reason_text: ReasonText;
  service: Service;
}
/**
 * A record the source panel can show and highlight.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "DocumentView".
 */
export interface DocumentView {
  doc_id: DocId1;
  text: Text;
  title: Title1;
}
/**
 * Screen 4: the gaps one person or office can fix.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "GapGroup".
 */
export interface GapGroup {
  items: Items;
  who: Who;
}
/**
 * One thing to ask for.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "GapItem".
 */
export interface GapItem {
  criterion_id: CriterionId;
  heading: Heading1;
  message: Message;
  status: StatusView;
}
/**
 * A place to get free help.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "LinkView".
 */
export interface LinkView {
  name: Name;
  note: Note;
  url: Url1;
}
/**
 * Screen 5: the letter, its clickable sentences, and what was kept out.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "LetterView".
 */
export interface LetterView {
  dropped: Dropped;
  not_argued: NotArgued;
  sentences: Sentences;
  text: Text2;
  unconfirmed: Unconfirmed;
}
/**
 * A criterion the letter leaves out, and what would let it be argued.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "NotArgued".
 */
export interface NotArgued1 {
  criterion_id: CriterionId1;
  heading: Heading2;
  message: Message1;
  status: StatusView;
}
/**
 * One letter sentence with its sources; offsets into the letter when it is shown there.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "SentenceView".
 */
export interface SentenceView {
  criterion_id: CriterionId2;
  decision: Decision;
  decision_label: DecisionLabel;
  letter_end: LetterEnd;
  letter_start: LetterStart;
  policy: PolicyClause;
  record: SourceSpan;
  score: Score;
  text: Text1;
}
export interface Run {
  [k: string]: string;
}
/**
 * Screen 6: the range and breakdown, or "get a human" with no numbers.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "StrengthView".
 */
export interface StrengthView {
  abstain: Abstain;
  base_rate: BaseRate;
  data_note: DataNote;
  high: High;
  improve: Improve;
  low: Low;
  n_similar: NSimilar;
  p: P;
  reason: Reason;
  steps: Steps;
}
/**
 * What helps, with the estimate if fixed (None when abstaining).
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "ImproveView".
 */
export interface ImproveView {
  action: Action;
  criterion_id: CriterionId3;
  heading: Heading3;
  p_if_fixed: PIfFixed;
}
/**
 * One criterion's effect on the estimate.
 *
 * This interface was referenced by `CaseView`'s JSON-Schema
 * via the `definition` "StepView".
 */
export interface StepView {
  criterion_id: CriterionId4;
  effect: Effect;
  heading: Heading4;
  status: StatusView;
}
