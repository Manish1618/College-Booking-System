/** The guesthouse mark: a lit doorway under an arch. Drawn in the current text colour. */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={className}>
      <path d="M6 28V14a10 10 0 0 1 20 0v14" stroke="currentColor" strokeWidth="1.5" />
      <path d="M12 28V15.5a4 4 0 0 1 8 0V28" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3 28h26" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="16" cy="7.5" r="1" fill="currentColor" />
    </svg>
  );
}
