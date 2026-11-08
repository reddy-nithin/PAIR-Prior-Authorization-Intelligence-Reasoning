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
