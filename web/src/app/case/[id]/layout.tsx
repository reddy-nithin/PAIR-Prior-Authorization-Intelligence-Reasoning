import { Suspense, type ReactNode } from "react";
import { Header } from "@/app/Header";
import { CaseShell } from "@/app/case/[id]/CaseShell";
import { copy } from "@/lib/copy";

/** The case id comes from the URL at request time, so the shell streams in behind this static fallback. */
export default function CaseLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <>
          <Header />
          <div className="col">
            <main id="main" tabIndex={-1}>
              <p className="lede" role="status">{copy.common.loading}</p>
            </main>
          </div>
        </>
      }
    >
      <CaseShell>{children}</CaseShell>
    </Suspense>
  );
}
