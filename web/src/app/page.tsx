"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Footer, Header } from "@/app/Header";
import { LockIcon, RightIcon, UploadIcon } from "@/components/Icons";
import { StatusBadge } from "@/components/StatusBadge";
import type { StatusView } from "@/types/caseview";
import { apiHealth, DataError, LIVE_AVAILABLE, loadIndex, REPO_URL, runLive, type CaseRow, type Health } from "@/lib/data";
import { useLiveStore } from "@/lib/live-store";
import { copy } from "@/lib/copy";
import { stepHref } from "@/lib/steps";

/** Overall verdict words from the demo index, mapped to tag colours. */
const OVERALL: Record<string, Pick<StatusView, "status" | "icon">> = {
  Met: { status: "met", icon: "check" },
  "Not met": { status: "unmet", icon: "cross" },
  "Not enough information": { status: "insufficient", icon: "question" },
};

/** Step 1: upload your own papers (live, when the local checker is on) or open a demo case. */
export default function StartPage() {
  const router = useRouter();
  const store = useLiveStore();
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  const [cases, setCases] = useState<CaseRow[] | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const denialRef = useRef<HTMLInputElement>(null);
  const recordsRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiHealth().then(setHealth);
    loadIndex().then(setCases, () => setCases([]));
  }, []);

  const liveOn = !!health?.live.enabled && health.live.reachable;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const denial = denialRef.current?.files?.[0];
    if (!denial) {
      setError(copy.start.needDenial);
      return;
    }
    setError("");
    setBusy(true);
    setStatus(copy.start.running);
    try {
      const { view } = await runLive(denial, Array.from(recordsRef.current?.files ?? []));
      store.put(view);
      router.push(stepHref(view.case_id, "why"));
    } catch (e) {
      setError(e instanceof DataError ? e.message : copy.start.backendDown);
      setStatus("");
    } finally {
      setBusy(false);
    }
  };

  const accept = ".pdf,.txt,.md,.png,.jpg,.jpeg,.heic,.docx,text/plain,application/pdf,image/*";

  const ownPapers = (
    <section className="card" aria-labelledby="own-h">
      <h2 id="own-h">{copy.start.ownFiles}</h2>
      {health === undefined ? (
        <p className="note">{copy.start.checking}</p>
      ) : liveOn ? (
        <form className="stack" onSubmit={submit} aria-busy={busy}>
          <div className="drop">
            <div className="field">
              <span className="icon-dot"><UploadIcon /></span>
              <label htmlFor="denial">{copy.start.uploadDenial}<span>{copy.start.uploadHint}</span></label>
              <input id="denial" ref={denialRef} type="file" accept={accept} />
            </div>
            <div className="field">
              <span className="icon-dot"><UploadIcon /></span>
              <label htmlFor="records">{copy.start.uploadRecords}<span>{copy.start.uploadHint}</span></label>
              <input id="records" ref={recordsRef} type="file" multiple accept={accept} />
            </div>
          </div>
          <p><button className="btn" type="submit" disabled={busy}>{copy.start.run}</button></p>
        </form>
      ) : (
        <div className="banner">
          <LockIcon />
          <p>
            {LIVE_AVAILABLE ? copy.start.backendDown : copy.start.hostedOnly}
            {LIVE_AVAILABLE ? null : <> <a href={REPO_URL} target="_blank" rel="noopener noreferrer">{copy.start.hostedLink}</a></>}
          </p>
        </div>
      )}
      <p className="sr" aria-live="polite">{status}</p>
      {status ? <p className="note" aria-hidden="true">{status}</p> : null}
      {error ? <p role="alert" className="error">{error}</p> : null}
      <p className="note">{copy.start.promise}</p>
    </section>
  );

  const demos = (
    <section className="stack" aria-labelledby="demo-h">
      <h2 id="demo-h">{copy.start.orDemo}</h2>
      {cases === null ? (
        <p className="note">{copy.common.loading}</p>
      ) : cases.length ? (
        <ul className="cases">
          {cases.map((row) => (
            <li key={row.case_id}>
              <Link className="case" href={stepHref(row.case_id, "why")}>
                <span className="t">
                  <b>{row.service ?? row.case_id}</b>
                  <span className="s">{row.policy_title}</span>
                  {row.overall ? <StatusBadge status={{ ...(OVERALL[row.overall] ?? OVERALL["Not enough information"]), label: row.overall } as StatusView} /> : null}
                </span>
                <RightIcon />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="note">{copy.start.noDemo}</p>
      )}
      <p className="note">{copy.start.demoNote}</p>
    </section>
  );

  return (
    <>
      <Header />
      <div className="col">
        <main id="main" tabIndex={-1}>
          <div className="stack">
            <p className="eyebrow">{copy.common.tagline}</p>
            <h1>{copy.start.headline}</h1>
            <p className="lede">{copy.start.intro}</p>
          </div>
          {LIVE_AVAILABLE ? <>{ownPapers}{demos}</> : <>{demos}{ownPapers}</>}
          <Footer />
        </main>
      </div>
    </>
  );
}
