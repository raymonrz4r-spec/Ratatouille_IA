import { useEffect, useRef, useState } from "react";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

function LoginPage({ error, isLoading, onGoogleCredential }) {
  const buttonRef = useRef(null);
  const [googleReady, setGoogleReady] = useState(false);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;

    const existingScript = document.querySelector('script[src="https://accounts.google.com/gsi/client"]');
    if (existingScript) {
      if (window.google?.accounts?.id) {
        setGoogleReady(true);
      } else {
        existingScript.addEventListener("load", () => setGoogleReady(true), { once: true });
      }
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => setGoogleReady(true);
    script.onerror = () => setGoogleReady(false);
    document.body.appendChild(script);
  }, []);

  useEffect(() => {
    if (!googleReady || !buttonRef.current || !window.google?.accounts?.id || !GOOGLE_CLIENT_ID) return;

    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: (response) => {
        if (response.credential) {
          onGoogleCredential(response.credential);
        }
      },
    });

    buttonRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(buttonRef.current, {
      theme: "outline",
      size: "large",
      type: "standard",
      text: "signin_with",
      shape: "pill",
      logo_alignment: "left",
      width: 320,
    });
  }, [googleReady, onGoogleCredential]);

  return (
    <div className="min-h-screen w-full flex items-center justify-center px-6 py-12">
      <div className="liquid-bg">
        <div className="blob blob-1"></div>
        <div className="blob blob-2"></div>
        <div className="blob blob-3"></div>
      </div>

      <main className="glass-panel w-full max-w-md rounded-xl p-8 border border-white/40 shadow-xl text-center flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <div className="font-display-lg-mobile text-display-lg-mobile text-primary">Ratatouille</div>
          <p className="font-body-md text-on-surface-variant">
            Inicia sesion para guardar tus recetas, progreso y plan en tu cuenta.
          </p>
        </div>

        <div className="flex justify-center min-h-[44px]">
          {GOOGLE_CLIENT_ID ? (
            <div className={isLoading ? "opacity-50 pointer-events-none" : ""} ref={buttonRef} />
          ) : (
            <div className="rounded-xl border border-error/30 bg-error/10 px-4 py-3 text-sm text-error">
              Falta configurar VITE_GOOGLE_CLIENT_ID en el frontend.
            </div>
          )}
        </div>

        {isLoading && (
          <div className="flex items-center justify-center gap-2 text-sm text-on-surface-variant">
            <span className="h-4 w-4 rounded-full border-2 border-primary/30 border-t-primary animate-spin" />
            Verificando cuenta...
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 px-4 py-3 text-sm text-error">
            {error}
          </div>
        )}
      </main>
    </div>
  );
}

export default LoginPage;
