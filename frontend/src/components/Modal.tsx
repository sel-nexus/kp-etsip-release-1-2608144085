/** Provide modal keyboard containment, scroll lock and focus restoration. */
import { useEffect, useId, useRef } from 'react';
import type { PropsWithChildren } from 'react';
interface ModalProps extends PropsWithChildren { title: string; onClose: () => void }
/** Restore trigger focus and keep Tab, Escape and overlay behavior native-feeling. */
export function Modal({ title, onClose, children }: ModalProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const controls = () => Array.from(panel.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]',
    ) ?? []);
    (controls()[0] ?? panel.current)?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close.current(); }
      if (event.key !== 'Tab') return;
      const items = controls();
      const first = items[0];
      const last = items[items.length - 1];
      if (!first) { event.preventDefault(); panel.current?.focus(); }
      else if (event.shiftKey && (document.activeElement === first || !panel.current?.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !panel.current?.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    const contain = (event: FocusEvent) => {
      if (!panel.current?.contains(event.target as Node)) (controls()[0] ?? panel.current)?.focus();
    };
    document.addEventListener('keydown', keyboard);
    document.addEventListener('focusin', contain);
    return () => {
      document.removeEventListener('keydown', keyboard);
      document.removeEventListener('focusin', contain);
      document.body.style.overflow = overflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return (
    <div className="modal-overlay" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={panel} tabIndex={-1}>
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  );
}
