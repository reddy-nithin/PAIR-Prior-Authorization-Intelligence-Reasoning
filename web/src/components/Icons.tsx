/** Small inline icons. All are decorative (aria-hidden); meaning is always carried by text next to them. */
const base = { "aria-hidden": true, focusable: false } as const;

export function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" {...base}>
      <circle cx="8" cy="8" r="7.5" fill="currentColor" opacity=".18" />
      <path d="M4.5 8.3l2.3 2.2 4.7-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
export function CrossIcon() {
  return (
    <svg viewBox="0 0 16 16" {...base}>
      <circle cx="8" cy="8" r="7.5" fill="currentColor" opacity=".18" />
      <path d="M5.2 5.2l5.6 5.6M10.8 5.2l-5.6 5.6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
export function QuestionIcon() {
  return (
    <svg viewBox="0 0 16 16" {...base}>
      <circle cx="8" cy="8" r="7.5" fill="currentColor" opacity=".18" />
      <path d="M6 6.2a2 2 0 113 1.7c-.7.4-1 .8-1 1.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="8" cy="11.8" r="1" fill="currentColor" />
    </svg>
  );
}
export function ChevronIcon() {
  return (
    <svg className="chev" viewBox="0 0 16 16" {...base}>
      <path d="M6 3.5l4.5 4.5L6 12.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
export function ShieldIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M10 2l6 2.5v4.7c0 4-2.6 7.2-6 8.8-3.4-1.6-6-4.8-6-8.8V4.5z" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M7 10l2.2 2.1L13.3 8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
export function PersonIcon() {
  return (
    <svg viewBox="0 0 32 32" {...base}>
      <circle cx="16" cy="11" r="5" fill="none" stroke="currentColor" strokeWidth="2.2" />
      <path d="M6 27c1.5-5.5 5.5-8 10-8s8.5 2.5 10 8" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}
export function FlagIcon() {
  return (
    <svg viewBox="0 0 16 16" {...base}>
      <path d="M3.5 14V2.5M3.5 3h8l-1.8 3 1.8 3h-8" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}
const line = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export function FileIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M5 2.5h6.5L15.5 6.5V17a.5.5 0 01-.5.5H5a.5.5 0 01-.5-.5V3a.5.5 0 01.5-.5z" {...line} />
      <path d="M11.5 2.5v4h4M7.5 10.5h5M7.5 13.5h5" {...line} />
    </svg>
  );
}
export function ScaleIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M10 3v14M6 17h8M4 6h12M4 6l-2.5 6a2.5 2.5 0 005 0zM16 6l-2.5 6a2.5 2.5 0 005 0z" {...line} />
    </svg>
  );
}
export function UploadIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M4 3.5h12M10 16.5V7M6 10.5l4-4 4 4" {...line} />
    </svg>
  );
}
export function LockIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <rect x="4" y="9" width="12" height="8.5" rx="2" {...line} />
      <path d="M7 9V6.5a3 3 0 016 0V9" {...line} />
    </svg>
  );
}
export function ExternalIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M11 3.5h5.5V9M16.5 3.5L9 11M14 12v3.5a1 1 0 01-1 1H4.5a1 1 0 01-1-1V7a1 1 0 011-1H8" {...line} />
    </svg>
  );
}
export function DownloadIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M10 3v10M6 9.5l4 4 4-4M4 16.5h12" {...line} />
    </svg>
  );
}
export function MessageIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M3.5 4.5h13v9h-8l-3.5 3v-3H3.5z" {...line} />
    </svg>
  );
}
export function RightIcon() {
  return (
    <svg viewBox="0 0 20 20" {...base}>
      <path d="M8 4.5l5.5 5.5L8 15.5" {...line} strokeWidth={2.2} />
    </svg>
  );
}
export function GitHubIcon() {
  return (
    <svg viewBox="0 0 16 16" {...base}>
      <path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8a8 8 0 005.47 7.59c.4.07.55-.17.55-.38v-1.33c-2.23.48-2.7-1.07-2.7-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.06-.49.06-.49.8.06 1.23.83 1.23.83.72 1.22 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.65-.89-3.65-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 014 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
