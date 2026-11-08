"use client";

import { DownloadButtons } from "@/components/DownloadButtons";
import { FlagIcon } from "@/components/Icons";
import { StepNav } from "@/components/Stepper";
import { useCase } from "@/lib/case-context";
import { copy } from "@/lib/copy";

export default function DownloadPage() {
  const view = useCase();
  return (
    <>
      <div className="stack">
        <h1>{copy.download.title}</h1>
        <p className="lede">{copy.download.beforeSend}</p>
      </div>
      {view.letter ? <DownloadButtons view={view} /> : <p>{copy.why.notSupported}</p>}
      <section className="card">
        <h2>{copy.download.beforeTitle}</h2>
        <ol className="check">{copy.download.steps.map((step) => <li key={step}>{step}</li>)}</ol>
      </section>
      <p className="banner"><FlagIcon />{view.safety_notice}</p>
      <StepNav caseId={view.case_id} current="download" />
    </>
  );
}
