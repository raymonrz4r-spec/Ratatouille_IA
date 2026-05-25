import { useState } from "react";

function SearchBar({ onSubmit, isLoading }) {
  const [url, setUrl] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    let cleanUrl = url.trim();
    if (!cleanUrl || isLoading) return;

    // Si el usuario no puso el protocolo, lo agregamos automáticamente
    if (!/^https?:\/\//i.test(cleanUrl)) {
      cleanUrl = "https://" + cleanUrl;
    }

    onSubmit(cleanUrl);
  }

  return (
    <form className="glass-panel rounded-full p-2 flex flex-col sm:flex-row items-center w-full gap-2 sm:gap-0" onSubmit={handleSubmit}>
      <input
        className="glass-input flex-grow bg-transparent border-none focus:outline-none focus:ring-0 text-on-surface placeholder:text-outline px-6 py-4 rounded-full font-body-md w-full"
        type="text"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="Pega un enlace aquí..."
        disabled={isLoading}
        required
      />
      <button
        className="liquid-button text-on-primary font-label-md px-8 py-4 rounded-full flex items-center justify-center gap-2 h-full w-full sm:w-auto"
        type="submit"
        disabled={isLoading}
      >
        {isLoading ? (
          <span className="material-symbols-outlined animate-spin">sync</span>
        ) : (
          <span className="material-symbols-outlined">auto_awesome</span>
        )}
        {isLoading ? "Procesando" : "Extraer"}
      </button>
    </form>
  );
}

export default SearchBar;
