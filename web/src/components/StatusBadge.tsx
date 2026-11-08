import type { StatusView } from "@/types/caseview";
import { CheckIcon, CrossIcon, QuestionIcon } from "@/components/Icons";

const ICONS: Record<string, () => React.JSX.Element> = { check: CheckIcon, cross: CrossIcon, question: QuestionIcon };

/** A status as icon + words, so it never depends on colour alone. */
export function StatusBadge({ status }: { status: StatusView }) {
  const Icon = ICONS[status.icon];
  return (
    <span className={`tag ${status.status}`}>
      {Icon ? <Icon /> : null}
      {status.label}
    </span>
  );
}
