import type { Metadata } from "next";
import { Atkinson_Hyperlegible, IBM_Plex_Mono, Source_Serif_4 } from "next/font/google";
import { LiveCaseProvider } from "@/lib/live-store";
import { copy } from "@/lib/copy";
import "./globals.css";

// Atkinson Hyperlegible was designed by the Braille Institute for low-vision readers.
const atkinson = Atkinson_Hyperlegible({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-atkinson" });
const serif = Source_Serif_4({ subsets: ["latin"], variable: "--font-serif" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

export const metadata: Metadata = {
  title: `${copy.common.appName}: ${copy.common.tagline}`,
  description: copy.start.intro,
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${atkinson.variable} ${serif.variable} ${mono.variable}`}>
      <body>
        <a className="skip" href="#main">{copy.common.skipToContent}</a>
        <LiveCaseProvider>{children}</LiveCaseProvider>
      </body>
    </html>
  );
}
