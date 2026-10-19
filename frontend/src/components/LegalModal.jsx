import { useEffect } from "react";

function LegalModal({ isOpen, initialTab = "terms", onClose }) {
  useEffect(() => {
    if (!isOpen) return;

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="legal-modal-title"
    >
      {/* Fondo difuminado accesible */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Contenedor del Modal */}
      <div className="glass-panel relative z-10 w-full max-w-3xl max-h-[85vh] rounded-3xl border border-white/40 dark:border-white/10 shadow-2xl bg-surface/95 dark:bg-inverse-surface/95 p-6 sm:p-8 flex flex-col text-on-surface dark:text-inverse-on-surface animate-scale-up">
        {/* Cabecera */}
        <div className="flex items-center justify-between border-b border-outline-variant/30 pb-4">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-2xl" aria-hidden="true">
              gavel
            </span>
            <h2 id="legal-modal-title" className="font-headline-md text-headline-md text-primary dark:text-inverse-primary">
              {initialTab === "privacy" ? "Política de Privacidad" : "Términos y Condiciones de Uso"}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-full hover:bg-black/5 dark:hover:bg-white/10 text-on-surface-variant transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
            aria-label="Cerrar documento legal"
            type="button"
          >
            <span className="material-symbols-outlined text-[22px]">close</span>
          </button>
        </div>

        {/* Contenido scrolleable */}
        <div className="overflow-y-auto py-6 space-y-6 text-sm text-on-surface-variant dark:text-surface-variant font-body-md pr-2 leading-relaxed">
          {initialTab === "privacy" ? (
            <>
              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  1. Compromiso con tu Privacidad y Datos de Google
                </h3>
                <p>
                  En <strong>Ratatouille AI</strong> nos tomamos la privacidad muy en serio. Al utilizar el inicio de sesión con Google (Google Sign-In), únicamente solicitamos y almacenamos los datos básicos de tu perfil público: tu identificador único de Google (sub), tu nombre completo, tu dirección de correo electrónico y tu fotografía de perfil.
                </p>
                <p>
                  <strong>No solicitamos permisos para acceder a tus correos de Gmail, tus archivos de Google Drive ni ningún otro dato personal.</strong> Cumplimos estrictamente con la Política de Datos de Usuario de los Servicios de API de Google.
                </p>
              </section>

              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  2. ¿Cómo procesamos los videos de cocina?
                </h3>
                <p>
                  Cuando pegas un enlace de TikTok, Instagram Reels o YouTube:
                </p>
                <ul className="list-disc pl-5 space-y-1">
                  <li>El servidor descarga temporalmente y de forma efímera la pista de audio para transcribir los ingredientes y pasos con Inteligencia Artificial.</li>
                  <li>Una vez generada la receta en texto, el archivo de audio temporal se elimina inmediatamente del servidor.</li>
                  <li>Las recetas resultantes se guardan de forma privada en tu cuenta mediante bases de datos seguras con cifrado en reposo y en tránsito (Supabase PostgreSQL).</li>
                </ul>
              </section>

              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  3. Almacenamiento y Protección de Datos
                </h3>
                <p>
                  Tus datos de recetas e imágenes asociadas se alojan en centros de datos seguros en la nube. Jamás vendemos, alquilamos ni transferimos tus datos personales a corredores de datos ni a empresas de publicidad de terceros.
                </p>
              </section>

              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  4. Control total y derecho de supresión
                </h3>
                <p>
                  Tienes derecho en cualquier momento a eliminar recetas individuales o vaciar tu colección completa haciendo clic en el botón de borrar en la aplicación. Si deseas eliminar tu cuenta por completo de nuestros registros, puedes hacerlo contactándonos a través del soporte técnico.
                </p>
              </section>

              <p className="text-xs text-outline pt-4 border-t border-outline-variant/20">
                Última actualización: 19 de octubre de 2026.
              </p>
            </>
          ) : (
            <>
              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  1. Aceptación de los Términos
                </h3>
                <p>
                  Al acceder y utilizar <strong>Ratatouille AI</strong>, aceptas cumplir con estos Términos y Condiciones de Uso. Si no estás de acuerdo con alguna parte, te sugerimos no utilizar la plataforma.
                </p>
              </section>

              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  2. Naturaleza del Servicio
                </h3>
                <p>
                  Ratatouille AI es una herramienta de asistencia culinaria que ayuda a los usuarios a estructurar información pública de videos culinarios de redes sociales en formatos de texto organizados (ingredientes, pasos y notas).
                </p>
                <p>
                  El usuario es responsable de contar con los derechos o permisos para consultar el contenido público compartido en las plataformas de origen (TikTok, Instagram, YouTube). Ratatouille AI no reclama propiedad sobre las recetas originales de los creadores y siempre preserva el enlace a la fuente original.
                </p>
              </section>

              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  3. Uso Responsable y Seguridad Alimentaria
                </h3>
                <p>
                  Aunque nuestros modelos de Inteligencia Artificial están optimizados para alta precisión culinaria, las recetas, tiempos de cocción y temperaturas generadas son de carácter orientativo. Siempre debes verificar que los alimentos estén cocidos adecuadamente y prestar atención a posibles alérgenos o sensibilidades alimentarias.
                </p>
              </section>

              <section className="space-y-2">
                <h3 className="font-bold text-base text-on-surface dark:text-inverse-on-surface">
                  4. Planes y Suscripciones
                </h3>
                <p>
                  Ratatouille AI ofrece un plan Gratuito y planes avanzados (Gourmet y Chef). Las funcionalidades de cada plan están sujetas a las condiciones descritas en la sección de Planes y pueden cancelarse en cualquier momento sin penalizaciones.
                </p>
              </section>

              <p className="text-xs text-outline pt-4 border-t border-outline-variant/20">
                Última actualización: 19 de octubre de 2026.
              </p>
            </>
          )}
        </div>

        {/* Pie del modal */}
        <div className="border-t border-outline-variant/30 pt-4 flex justify-end">
          <button
            onClick={onClose}
            className="liquid-button rounded-full px-6 py-2.5 text-on-primary font-label-md min-h-[44px] min-w-[100px] flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            type="button"
          >
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
}

export default LegalModal;
