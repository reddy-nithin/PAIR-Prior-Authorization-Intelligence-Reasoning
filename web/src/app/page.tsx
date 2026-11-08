"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Header } from "@/app/Header";
import { ShieldIcon } from "@/components/Icons";
import { apiHealth, DataError, LIVE_AVAILABLE, loadIndex, runLive, type CaseRow, type Health } from "@/lib/data";
import { useLiveStore } from "@/lib/live-store";
import { copy } from "@/lib/copy";
import { stepHref } from "@/lib/steps";

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

  return (
    <>
      <Header />
      <div className="wrap shell single">
        <main id="main" tabIndex={-1}>
          <div className="stack">
            <p className="eyebrow">{copy.start.eyebrow}</p>
            <h1>{copy.start.headline}</h1>
            <p className="lede">{copy.start.intro}</p>
          </div>
          <div className="paths">
            <section className="panel" aria-labelledby="own-h">
              <h2 id="own-h">{copy.start.ownFiles}</h2>
              {health === undefined ? (
                <p className="note">{copy.start.checking}</p>
              ) : liveOn ? (
                <form className="stack" onSubmit={submit} aria-busy={busy}>
                  <div className="field">
                    <label htmlFor="denial"><b>{copy.start.uploadDenial}</b></label>
                    <input id="denial" ref={denialRef} type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.heic,.docx,text/plain,application/pdf,image/*" />
                  </div>
                  <div className="field">
                    <label htmlFor="records"><b>{copy.start.uploadRecords}</b></label>
                    <input id="records" ref={recordsRef} type="file" multiple accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.heic,.docx,text/plain,application/pdf,image/*" />
                  </div>
                  <p className="note">{copy.start.uploadHint}</p>
                  <button className="btn" type="submit" disabled={busy}>{copy.start.run}</button>
                </form>
              ) : (
                <p>{LIVE_AVAILABLE ? copy.start.backendDown : copy.start.hostedOnly}</p>
              )}
              <p className="sr" aria-live="polite">{status}</p>
              {status ? <p className="note" aria-hidden="true">{status}</p> : null}
              {error ? <p role="alert" className="error">{error}</p> : null}
            </section>
            <section className="panel" aria-labelledby="demo-h">
              <h2 id="demo-h">{copy.start.orDemo}</h2>
              {cases === null ? (
                <p className="note">{copy.common.loading}</p>
              ) : cases.length ? (
                <ul className="cases">
                  {cases.map((row) => (
                    <li key={row.case_id}>
                      <Link className="case" href={stepHref(row.case_id, "why")}>
                        <span>
                          <b>{row.service ?? row.case_id}</b>
                          <br />
                          <span className="note">{row.policy_title}</span>
                        </span>
                        {row.overall ? <span className="chip">{row.overall}</span> : null}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="note">{copy.start.noDemo}</p>
              )}
              <p className="note">{copy.start.demoNote}</p>
            </section>
          </div>
          <div className="promise"><ShieldIcon /><p>{copy.start.promise}</p></div>
        </main>
      </div>
    </>
  );
}
