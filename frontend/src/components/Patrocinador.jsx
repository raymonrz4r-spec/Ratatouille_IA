import { useState, useEffect } from "react";

const SPONSORS = [
    {
        id: 1,
        name: "FrescCo Orgánicos",
        description: "Ingredientes frescos y de temporada directamente de productores locales a tu cocina. ¡Prepara tus recetas con lo mejor!",
        promo: "20% DESC: RATATOUILLE20",
        link: "https://example.com/frescco",
        icon: "spa",
        themeColor: "text-secondary",
        bgColor: "bg-secondary/10",
    },
    {
        id: 2,
        name: "Cuchillos MasterChef",
        description: "Cuchillos de acero damasco de alta calidad para cortes perfectos y precisos. El compañero ideal para todo cocinero.",
        promo: "Envío gratis esta semana",
        link: "https://example.com/cuchillos",
        icon: "restaurant",
        themeColor: "text-primary",
        bgColor: "bg-primary/10",
    },
    {
        id: 3,
        name: "Cursos Gourmet",
        description: "Domina técnicas avanzadas de cocina con nuestros cursos en línea liderados por chefs internacionales galardonados.",
        promo: "Prueba gratis de 7 días",
        link: "https://example.com/cursos",
        icon: "workspace_premium",
        themeColor: "text-tertiary",
        bgColor: "bg-tertiary/10",
    }
];

function Patrocinador() {
    const [currentIndex, setCurrentIndex] = useState(0);
    const [isVisible, setIsVisible] = useState(true);
    const [fade, setFade] = useState(true);

    useEffect(() => {
        if (!isVisible) return;
        const interval = setInterval(() => {
            setFade(false);
            setTimeout(() => {
                setCurrentIndex((prevIndex) => (prevIndex + 1) % SPONSORS.length);
                setFade(true);
            }, 300); // Coincide con la animación de desvanecimiento
        }, 7000);

        return () => clearInterval(interval);
    }, [isVisible]);

    if (!isVisible) return null;

    const sponsor = SPONSORS[currentIndex];

    return (
        <div className={`glass-panel rounded-2xl p-5 flex flex-col sm:flex-row items-center justify-between gap-4 w-full text-left relative overflow-hidden transition-all duration-300 ease-in-out border border-white/30 dark:border-white/10 hover:shadow-lg ${fade ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-1'}`}>
            {/* Etiqueta de Patrocinado */}
            <div className="absolute top-2 right-10 sm:right-12">
                <span className="bg-surface/50 dark:bg-inverse-surface/20 text-on-surface-variant font-label-xs px-2 py-0.5 rounded-full border border-white/20 text-[10px] uppercase tracking-widest font-semibold opacity-70">
                    Patrocinado
                </span>
            </div>

            {/* Botón de cerrar */}
            <button
                onClick={() => setIsVisible(false)}
                className="absolute top-2 right-2 text-on-surface-variant/40 hover:text-on-surface-variant/90 transition-colors p-1 rounded-full hover:bg-white/15 dark:hover:bg-white/5 flex items-center justify-center"
                aria-label="Cerrar anuncio"
            >
                <span className="material-symbols-outlined text-[16px]">close</span>
            </button>

            {/* Contenido Izquierdo (Icono + Textos) */}
            <div className="flex flex-col sm:flex-row items-center sm:items-start gap-4 flex-grow w-full">
                <div className={`h-12 w-12 rounded-full shrink-0 flex items-center justify-center ${sponsor.bgColor}`}>
                    <span className={`material-symbols-outlined text-2xl ${sponsor.themeColor}`}>
                        {sponsor.icon}
                    </span>
                </div>
                <div className="flex flex-col text-center sm:text-left gap-1 max-w-xl">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                        <h4 className="font-headline-sm text-headline-sm text-on-surface font-bold">
                            {sponsor.name}
                        </h4>
                        {sponsor.promo && (
                            <span className={`inline-block font-label-sm text-[11px] px-2.5 py-0.5 rounded-full font-semibold self-center sm:self-auto border border-current bg-white/40 dark:bg-black/10 ${sponsor.themeColor}`}>
                                {sponsor.promo}
                            </span>
                        )}
                    </div>
                    <p className="font-body-md text-sm text-on-surface-variant leading-relaxed">
                        {sponsor.description}
                    </p>
                </div>
            </div>

            {/* Botón de Acción */}
            <div className="shrink-0 w-full sm:w-auto flex justify-center sm:justify-end">
                <a
                    href={sponsor.link}
                    target="_blank"
                    rel="noreferrer"
                    className="liquid-button text-on-primary font-label-md px-6 py-3 rounded-full flex items-center justify-center gap-2 w-full sm:w-auto text-center"
                >
                    <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                    Saber más
                </a>
            </div>
        </div>
    );
}

export default Patrocinador;