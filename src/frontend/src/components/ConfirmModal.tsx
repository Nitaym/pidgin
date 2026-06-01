import { useEffect } from "react";

type ConfirmModalProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  confirmClassName?: string;
  busy?: boolean;
  error?: string | null;
  children: React.ReactNode;
};

export function ConfirmModal({
  open,
  title,
  onClose,
  onConfirm,
  confirmLabel,
  confirmClassName = "danger",
  busy = false,
  error = null,
  children,
}: ConfirmModalProps) {
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onClose]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div className="modal panel stack" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <h4 id="modal-title" style={{ margin: 0 }}>
          {title}
        </h4>
        <div className="modal-body">{children}</div>
        {error ? <div className="error">{error}</div> : null}
        <div className="row modal-actions">
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={confirmClassName}
            disabled={busy}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
