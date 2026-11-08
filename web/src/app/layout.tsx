import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible_Next, Figtree, IBM_Plex_Mono, Literata } from "next/font/google";
import { LiveCaseProvider } from "@/lib/live-store";
import { copy } from "@/lib/copy";
import "./globals.css";

// Direction C type (ADR-0026): Figtree for headings, Atkinson Hyperlegible Next for reading
// (designed by the Braille Institute for low-vision readers), Literata for the letter, Plex Mono for record quotes.
const atkinson = Atkinson_Hyperlegible_Next({ subsets: ["latin"], variable: "--font-atkinson" });
const figtree = Figtree({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-figtree" });
const literata = Literata({ subsets: ["latin"], variable: "--font-literata" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

export const metadata: Metadata = {
  title: `${copy.common.appName}: ${copy.common.tagline}`,
  description: copy.start.intro,
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f3ee" },
    { media: "(prefers-color-scheme: dark)", color: "#1b1916" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${atkinson.variable} ${figtree.variable} ${literata.variable} ${mono.variable}`}>
      <body>
        <a className="skip" href="#main">{copy.common.skipToContent}</a>
        <LiveCaseProvider>{children}</LiveCaseProvider>
      </body>
    </html>
  );
}
