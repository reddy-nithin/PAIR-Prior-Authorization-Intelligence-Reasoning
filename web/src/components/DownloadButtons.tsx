"use client";

import { useState } from "react";
import type { CaseView } from "@/types/caseview";
import { cachedFileUrl, DataError, exportLive } from "@/lib/data";
import { copy } from "@/lib/copy";

const FORMATS = [
  { fmt: "docx", label: copy.download.docx, hint: copy.download.wordBest, ext: ".docx" },
  { fmt: "pdf", label: copy.download.pdf, hint: copy.download.pdfBest, ext: ".pdf" },
] as const;

/** Cached cases link to the pre-rendered files; live cases ask the local API to render them. */
export function DownloadButtons({ view }: { view: CaseView }) {
  const [error, setError] = useState("");
  const live = view.mode === "live";
  const save = async (fmt: "docx" | "pdf") => {
    setError("");
    try {
      const blob = await exportLive(view, fmt);
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement("a"), { href: url, download: `appeal-letter.${fmt}` });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof DataError ? e.message : copy.download.failed);
    }
  };
  return (
    <>
      <div className="files">
        {FORMATS.map(({ fmt, label, hint, ext }, i) => (
          <section className="panel file" key={fmt}>
            <h2>{label.replace(/ \(\.docx\)$/, "")} <span className="ext">{ext}</span></h2>
            <p>{hint}</p>
            {live ? (
              <button type="button" className={`btn${i ? " secondary" : ""}`} onClick={() => save(fmt)}>{label}</button>
            ) : (
              <a className={`btn${i ? " secondary" : ""}`} href={cachedFileUrl(view.case_id, fmt)} download={`appeal-letter-${view.case_id}${ext}`}>{label}</a>
            )}
          </section>
        ))}
      </div>
      {error ? <p role="alert" className="error">{error}</p> : null}
    </>
  );
}
