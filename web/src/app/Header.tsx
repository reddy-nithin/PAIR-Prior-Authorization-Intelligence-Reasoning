import Link from "next/link";
import type { ReactNode } from "react";
import { copy } from "@/lib/copy";

/** The top band: the app name, plus the claim strip on case pages. */
export function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="strip">
      <div className="wrap">
        <Link className="brand" href="/">
          {copy.common.appName} <small>{copy.common.tagline}</small>
        </Link>
        {children}
      </div>
    </header>
  );
}
