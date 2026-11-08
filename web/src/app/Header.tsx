import Link from "next/link";
import type { ReactNode } from "react";
import { GitHubIcon } from "@/components/Icons";
import { copy } from "@/lib/copy";
import { REPO_URL } from "@/lib/data";

/** The top bar: the app name on the left; the demo or live tag and the code link on the right. */
export function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="topbar">
      <Link className="brand" href="/" aria-label={`${copy.common.appName}, ${copy.common.home}`}>
        {copy.common.appName}
      </Link>
      <div className="topbar-end">
        {children}
        <a className="ghlink" href={REPO_URL} target="_blank" rel="noopener noreferrer">
          <GitHubIcon />
          {copy.common.codeLink}
        </a>
      </div>
    </header>
  );
}

/** The last line of every page. */
export function Footer() {
  return (
    <footer className="foot">
      <span>{copy.common.notAdvice}</span>
      <a href={REPO_URL} target="_blank" rel="noopener noreferrer">{copy.common.howItWorks}</a>
    </footer>
  );
}
