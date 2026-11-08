"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CaseView, SentenceView } from "@/types/caseview";
import { copy, fill } from "@/lib/copy";
import { CheckIcon } from "@/components/Icons";

/** Letter text cut into plain runs and clickable sentences, by the sentences' character offsets. */
export function letterParts(text: string, sentences: SentenceView[]): ({ kind: "text"; text: string } | { kind: "sentence"; text: string; index: number; sentence: SentenceView })[] {
  const placed = sentences
    .filter((s) => s.letter_start != null && s.letter_end != null)
    .sort((a, b) => (a.letter_start as number) - (b.letter_start as number));
  const parts: ReturnType<typeof letterParts> = [];
  let at = 0;
  placed.forEach((s, index) => {
    const start = s.letter_start as number;
    const end = s.letter_end as number;
    if (start < at) return; // overlapping offsets: keep the first
    if (start > at) parts.push({ kind: "text", text: text.slice(at, start) });
    parts.push({ kind: "sentence", text: text.slice(start, end), index, sentence: s });
    at = end;
  });
  if (at < text.length) parts.push({ kind: "text", text: text.slice(at) });
  return parts;
}

/** One letter sentence as a button: Tab to it, Enter or Space shows its source. */
export function LetterSentence({ text, index, selected, onSelect }: { text: string; index: number; selected: boolean; onSelect: (i: number) => void }) {
  return (
    <button type="button" className="sent" aria-pressed={selected} onClick={() => onSelect(index)}>
      {text}
      <span className="src" aria-hidden="true">{index + 1}</span>
      <span className="sr">{`, ${fill(copy.letter.showSource, { n: index + 1 })}`}</span>
    </button>
  );
}

/** The record text with the quoted span marked, and the rule the sentence answers. */
export function SourcePanel({ sentence, index, documents }: { sentence: SentenceView | null; index: number; documents: CaseView["documents"] }) {
  const markRef = useRef<HTMLElement>(null);
  useEffect(() => {
    markRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [sentence]);
  if (!sentence) {
    return (
      <aside className="panel source" aria-label={copy.letter.sourcePanel}>
        <p className="eyebrow">{copy.letter.sourcePanel}</p>
        <p className="note">{copy.letter.pick}</p>
      </aside>
    );
  }
  const doc = documents.find((d) => d.doc_id === sentence.record.doc_id);
  const { char_start: a, char_end: b } = sentence.record;
  return (
    <aside className="panel source" aria-label={copy.letter.sourcePanel} id="source">
      <p className="eyebrow">{fill(copy.letter.sourceFor, { n: index + 1 })}</p>
      <b>{doc?.title ?? sentence.record.doc_id}</b>
      <div className="doc" tabIndex={0} aria-label={doc?.title ?? sentence.record.doc_id}>
        {doc ? (
          <>
            {doc.text.slice(0, a)}
            <mark className="hl" ref={markRef} data-testid="source-mark">{doc.text.slice(a, b)}</mark>
            {doc.text.slice(b)}
          </>
        ) : (
          <mark className="hl" data-testid="source-mark">{sentence.record.quote}</mark>
        )}
      </div>
      <div>
        <p className="eyebrow">{`${copy.letter.ruleAnswers} (${sentence.policy.source.label})`}</p>
        <p className="clause">“{sentence.policy.clause}”</p>
      </div>
      <span className="tag met"><CheckIcon />{sentence.decision_label}</span>
    </aside>
  );
}

/** The letter on paper beside its source browser; announces each selection to screen readers. */
export function LetterView({ view }: { view: CaseView }) {
  const letter = view.letter;
  const parts = useMemo(() => (letter ? letterParts(letter.text, letter.sentences) : []), [letter]);
  const sentences = parts.flatMap((p) => (p.kind === "sentence" ? [p.sentence] : []));
  const [selected, setSelected] = useState<number | null>(null);
  const [announce, setAnnounce] = useState("");
  if (!letter) return <p className="lede">{copy.why.notSupported}</p>;
  const select = (i: number) => {
    setSelected(i);
    const s = sentences[i];
    const title = view.documents.find((d) => d.doc_id === s.record.doc_id)?.title ?? s.record.doc_id;
    setAnnounce(`${fill(copy.letter.sourceFor, { n: i + 1 })}: ${title}. ${s.record.quote}`);
    if (window.matchMedia?.("(max-width: 1000px)").matches) document.getElementById("source")?.scrollIntoView({ block: "start" });
  };
  return (
    <>
      <div className="split">
        <article className="paper" aria-label={copy.letter.title}>
          {parts.map((p, k) =>
            p.kind === "text" ? (
              <span key={k}>{p.text}</span>
            ) : (
              <LetterSentence key={k} text={p.text} index={p.index} selected={selected === p.index} onSelect={select} />
            ),
          )}
        </article>
        <SourcePanel sentence={selected == null ? null : sentences[selected]} index={selected ?? 0} documents={view.documents} />
      </div>
      <div className="sr" aria-live="polite">{announce}</div>
    </>
  );
}
