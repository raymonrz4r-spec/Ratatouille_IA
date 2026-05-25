function ErrorToast({ message, onClose }) {
  if (!message) return null;

  return (
    <div className="fixed bottom-4 left-4 right-4 z-50 mx-auto max-w-xl rounded-xl border border-error/20 bg-error-container p-4 shadow-soft">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-error text-on-error">
          <span className="material-symbols-outlined text-[20px]">warning</span>
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-label-md text-on-error-container">No se pudo procesar</p>
          <p className="mt-1 break-words font-body-sm text-on-error-container/80">{message}</p>
        </div>
        <button
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-on-error-container/60 transition hover:bg-error/10 hover:text-on-error-container"
          type="button"
          onClick={onClose}
          title="Cerrar"
        >
          <span className="material-symbols-outlined text-[20px]">close</span>
        </button>
      </div>
    </div>
  );
}

export default ErrorToast;
