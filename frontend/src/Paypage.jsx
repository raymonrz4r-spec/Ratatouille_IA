import { useState, useEffect } from "react";

function Paypage({ currentPlan = "Gratuito", onSubscribe, onNavigateToKitchen }) {
  const [billingCycle, setBillingCycle] = useState("monthly"); // "monthly" or "yearly"
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState(null);

  // Form States
  const [cardNumber, setCardNumber] = useState("");
  const [cardExpiry, setCardExpiry] = useState("");
  const [cardCvv, setCardCvv] = useState("");
  const [cardHolder, setCardHolder] = useState("");
  const [errors, setErrors] = useState({});
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStep, setProcessingStep] = useState(0);
  const [isSuccess, setIsSuccess] = useState(false);

  // Micro-interaction coordinates for glass cards
  const handleMouseMove = (e) => {
    const card = e.currentTarget;
    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    card.style.setProperty("--mouse-x", `${x}px`);
    card.style.setProperty("--mouse-y", `${y}px`);
  };

  const plans = [
    {
      name: "Gratuito",
      icon: "egg_alt",
      priceMonthly: 0,
      priceYearly: 0,
      description: "Ideal para dar tus primeros pasos en la cocina digital.",
      features: [
        { text: "5 recetas al mes", included: true },
        { text: "Funciones básicas de conversión", included: true },
        { text: "Acceso comunitario", included: true },
        { text: "Sin guardado en la nube", included: false },
      ],
      buttonText: "Plan Actual",
      accentColor: "text-secondary dark:text-secondary-fixed",
    },
    {
      name: "Gourmet",
      icon: "skillet",
      priceMonthly: 3,
      priceYearly: 2.50, // 20% discount = 10 * 12 = 120 per year
      description: "El plan favorito para los apasionados del buen comer.",
      features: [
        { text: "Recetas ilimitadas", included: true },
        { text: "Extracción de videos 4K", included: true },
        { text: "Guardado ilimitado en la nube", included: true },
        { text: "Soporte prioritario", included: true },
      ],
      buttonText: "Suscribirse",
      accentColor: "text-primary dark:text-inverse-primary",
      featured: true,
    },

  ];

  // Helper to format Card Number (XXXX XXXX XXXX XXXX)
  const handleCardNumberChange = (e) => {
    let value = e.target.value.replace(/\D/g, "");
    value = value.substring(0, 16);
    const sections = value.match(/.{1,4}/g);
    setCardNumber(sections ? sections.join(" ") : "");
  };

  // Helper to format Expiry Date (MM/YY)
  const handleExpiryChange = (e) => {
    let value = e.target.value.replace(/\D/g, "");
    value = value.substring(0, 4);
    if (value.length > 2) {
      value = value.substring(0, 2) + "/" + value.substring(2);
    }
    setCardExpiry(value);
  };

  // Helper for CVV
  const handleCvvChange = (e) => {
    const value = e.target.value.replace(/\D/g, "").substring(0, 4);
    setCardCvv(value);
  };

  const handleOpenCheckout = (plan) => {
    if (plan.name === currentPlan) return;
    if (plan.name === "Gratuito") {
      // Downgrade or switch to free plan doesn't need checkout simulation
      if (window.confirm("¿Seguro que deseas volver al Plan Gratuito?")) {
        onSubscribe("Gratuito");
      }
      return;
    }
    setSelectedPlan(plan);
    setIsModalOpen(true);
    // Reset states
    setCardNumber("");
    setCardExpiry("");
    setCardCvv("");
    setCardHolder("");
    setErrors({});
    setIsProcessing(false);
    setIsSuccess(false);
  };

  const validateForm = () => {
    const newErrors = {};
    if (!cardHolder.trim()) newErrors.cardHolder = "El nombre del titular es requerido";
    if (cardNumber.replace(/\s/g, "").length !== 16) {
      newErrors.cardNumber = "El número de tarjeta debe tener 16 dígitos";
    }
    const expiryRegex = /^(0[1-9]|1[0-2])\/?([0-9]{2})$/;
    if (!expiryRegex.test(cardExpiry)) {
      newErrors.cardExpiry = "Formato MM/YY inválido";
    } else {
      // Check if date is in the future
      const [m, y] = cardExpiry.split("/");
      const expiryDate = new Date(parseInt("20" + y), parseInt(m) - 1, 1);
      const today = new Date();
      if (expiryDate < today) {
        newErrors.cardExpiry = "La tarjeta está expirada";
      }
    }
    if (cardCvv.length < 3) newErrors.cardCvv = "CVV inválido";

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handlePaymentSubmit = (e) => {
    e.preventDefault();
    if (!validateForm()) return;

    setIsProcessing(true);
    setProcessingStep(0);
  };

  // Simulated processing steps
  useEffect(() => {
    if (!isProcessing) return;

    const intervals = [800, 1800, 2800];
    const timers = [];

    timers.push(
      setTimeout(() => {
        setProcessingStep(1); // "Verificando fondos..."
      }, intervals[0])
    );

    timers.push(
      setTimeout(() => {
        setProcessingStep(2); // "Encriptando transacción..."
      }, intervals[1])
    );

    timers.push(
      setTimeout(() => {
        setIsProcessing(false);
        setIsSuccess(true);
        // Call callback to update plan
        onSubscribe(selectedPlan.name);
      }, intervals[2])
    );

    return () => timers.forEach(clearTimeout);
  }, [isProcessing, selectedPlan, onSubscribe]);

  // Determine card icon
  const getCardTypeIcon = (num) => {
    const cleanNum = num.replace(/\s/g, "");
    if (cleanNum.startsWith("4")) return "credit_card"; // Visa representation
    if (cleanNum.startsWith("5")) return "credit_card"; // Mastercard
    return "credit_card";
  };

  return (
    <div className="w-full flex-grow flex flex-col items-center">
      {/* Hero Section */}
      <section className="text-center mb-16 max-w-3xl px-4 animate-fade-in">
        <h1 className="font-display-lg text-display-lg-mobile md:text-display-lg text-primary dark:text-inverse-primary mb-4 leading-tight">
          Elige tu Plan Culinario
        </h1>
        <p className="font-body-lg text-on-surface-variant dark:text-surface-variant max-w-xl mx-auto">
          Accede a un mundo de sabores diseñados para cada tipo de chef. Desde aficionados hasta profesionales del arte culinario.
        </p>

        {/* Billing Cycle Selector */}
        <div className="flex items-center justify-center gap-4 mt-10">
          <span className={`font-label-md transition-colors ${billingCycle === "monthly" ? "text-primary dark:text-inverse-primary font-bold" : "text-on-surface-variant"}`}>
            Mensual
          </span>
          <button
            onClick={() => setBillingCycle(billingCycle === "monthly" ? "yearly" : "monthly")}
            className="relative w-16 h-8 rounded-full bg-surface-container-high dark:bg-inverse-surface border border-outline/20 dark:border-white/10 transition-colors focus:outline-none"
            aria-label="Toggle billing cycle"
          >
            <div
              className={`absolute top-1 left-1 w-6 h-6 rounded-full bg-primary dark:bg-inverse-primary transition-transform duration-300 ${billingCycle === "yearly" ? "translate-x-8" : ""
                }`}
            />
          </button>
          <div className="flex items-center gap-2">
            <span className={`font-label-md transition-colors ${billingCycle === "yearly" ? "text-primary dark:text-inverse-primary font-bold" : "text-on-surface-variant"}`}>
              Anual
            </span>
            <span className="bg-primary-container text-on-primary-container dark:bg-primary-fixed-dim dark:text-on-primary-fixed-variant text-[11px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider animate-pulse">
              Ahorra 20%
            </span>
          </div>
        </div>
      </section>

      {/* Pricing Grid */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-8 w-full max-w-container-max px-4">
        {plans.map((plan) => {
          const isCurrent = currentPlan === plan.name;
          const price = billingCycle === "monthly" ? plan.priceMonthly : plan.priceYearly;
          const yearlyTotal = plan.priceYearly * 12;

          return (
            <div
              key={plan.name}
              onMouseMove={handleMouseMove}
              className={`glass-card rounded-2xl p-card-padding flex flex-col items-center text-center transition-all duration-500 relative ${plan.featured
                ? "border border-primary/30 dark:border-inverse-primary/30 md:-translate-y-4 md:hover:-translate-y-6 shadow-xl ring-1 ring-primary/10 dark:ring-inverse-primary/10 scale-100 md:scale-105 z-10"
                : "border border-white/20 dark:border-white/5"
                }`}
            >
              {plan.featured && (
                <div className="absolute top-1 left-1/2 -translate-x-1/2 -translate-y-1/10 bg-primary dark:bg-surface-tint text-on-primary px-6 py-1.5 rounded-full font-label-sm tracking-widest text-[11px] font-bold shadow-md">
                  MÁS POPULAR
                </div>
              )}

              <span className={`material-symbols-outlined text-5xl mb-6 ${plan.accentColor}`}>
                {plan.icon}
              </span>

              <h3 className="font-headline-md text-headline-md text-on-surface dark:text-inverse-on-surface mb-2">
                Plan {plan.name}
              </h3>

              <p className="text-[13px] text-on-surface-variant dark:text-surface-variant/80 px-2 mb-6 min-h-[40px]">
                {plan.description}
              </p>

              <div className="mb-6 relative">
                <div className="flex items-baseline justify-center">
                  <span className="font-display-lg text-headline-lg md:text-display-lg dark:text-inverse-on-surface transition-all">
                    {price}€
                  </span>
                  <span className="text-on-surface-variant dark:text-surface-variant font-label-md ml-1">
                    /mes
                  </span>
                </div>
                {billingCycle === "yearly" && plan.priceYearly > 0 && (
                  <p className="text-[11px] text-primary dark:text-inverse-primary font-semibold mt-1">
                    Facturado anualmente ({yearlyTotal}€/año)
                  </p>
                )}
              </div>

              <ul className="space-y-4 mb-8 text-left w-full font-body-md text-on-surface-variant dark:text-surface-variant/90 border-t border-outline-variant/20 dark:border-white/10 pt-6 flex-grow">
                {plan.features.map((feature, idx) => (
                  <li key={idx} className="flex items-start gap-3">
                    {feature.included ? (
                      <span className="material-symbols-outlined text-primary dark:text-inverse-primary text-[20px] shrink-0" style={{ fontVariationSettings: "'FILL' 1" }}>
                        check_circle
                      </span>
                    ) : (
                      <span className="material-symbols-outlined text-outline dark:text-outline-variant text-[20px] shrink-0 opacity-60">
                        cancel
                      </span>
                    )}
                    <span className={feature.included ? "" : "line-through opacity-60"}>
                      {feature.text}
                    </span>
                  </li>
                ))}
              </ul>

              {isCurrent ? (
                <button
                  disabled
                  className="mt-auto w-full py-4 rounded-full bg-surface-container-highest dark:bg-inverse-surface text-on-surface-variant dark:text-surface-variant font-label-md border border-outline/30 dark:border-white/15 cursor-default flex items-center justify-center gap-2"
                >
                  <span className="material-symbols-outlined text-sm">verified</span>
                  Plan Activo
                </button>
              ) : plan.featured ? (
                <button
                  onClick={() => handleOpenCheckout(plan)}
                  className="liquid-button mt-auto w-full py-4 rounded-full text-on-primary font-label-md shadow-lg select-none"
                >
                  {plan.buttonText}
                </button>
              ) : (
                <button
                  onClick={() => handleOpenCheckout(plan)}
                  className="mt-auto w-full py-4 rounded-full border-2 border-primary dark:border-inverse-primary text-primary dark:text-inverse-primary font-label-md hover:bg-primary/5 dark:hover:bg-inverse-primary/5 transition-colors select-none"
                >
                  {plan.buttonText}
                </button>
              )}
            </div>
          );
        })}
      </section>

      {/* Aesthetic Imagery Section */}
      <section className="mt-28 grid grid-cols-1 md:grid-cols-2 gap-gutter w-full max-w-container-max px-4 items-center">
        <div className="glass-card p-4 rounded-2xl border border-white/20 dark:border-white/5 shadow-md flex items-center justify-center">
          <img
            alt="Inspiración culinaria"
            className="w-full h-72 object-cover rounded-xl"
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuBWhu2NIEMw096csVjUaID1EvJPl0hiVSe2XQQinTPLsqqL9mOC6V_zFFM182pKua_lctT3v-QB9akc72Id-cKJwvVFBwlq2yUsLYz5X0oZNB83vhmw5CJomuc_RurMBP8XdkX6a4aGI8AnGj_KGw-7jBleLzTH6l-aStCiLoTI0VBxbuut-p5CsCkoXPhfDIgX-nb07biAIkQ1yGI98JJSLbdn_xAQ1lMgWHQZVEuj3HbdQH1SQ5IAl51WBiDo5ju7NzgeNXNFmbT7"
          />
        </div>
        <div className="flex flex-col gap-6 pl-0 md:pl-8 mt-8 md:mt-0">
          <h2 className="font-headline-lg text-headline-lg text-primary dark:text-inverse-primary leading-tight">
            La Experiencia Ratatouille
          </h2>
          <p className="text-on-surface-variant dark:text-surface-variant font-body-lg leading-relaxed">
            Nuestra plataforma utiliza tecnología de vanguardia para que cocinar sea una experiencia fluida como el cristal. Suscríbete hoy y transforma tu cocina en un taller de arte.
          </p>
          <div className="flex flex-wrap gap-4 mt-2">
            <div className="px-5 py-3 rounded-full bg-secondary-container dark:bg-secondary text-on-secondary-container dark:text-white flex items-center gap-2 shadow-sm font-label-md">
              <span className="material-symbols-outlined text-[20px]">auto_awesome</span>
              <span>IA Culinaria</span>
            </div>
            <div className="px-5 py-3 rounded-full bg-tertiary-container/20 dark:bg-tertiary-container/30 text-tertiary dark:text-tertiary-fixed flex items-center gap-2 shadow-sm font-label-md border border-tertiary-container/10">
              <span className="material-symbols-outlined text-[20px]">video_library</span>
              <span>Clases 4K</span>
            </div>
          </div>
        </div>
      </section>

      {/* Checkout Modal Dialog */}
      {isModalOpen && selectedPlan && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          {/* Backdrop blur */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-md"
            onClick={() => !isProcessing && setIsModalOpen(false)}
          />

          {/* Modal Container */}
          <div className="glass-panel w-full max-w-md rounded-3xl border border-white/40 dark:border-white/10 shadow-2xl relative overflow-hidden z-10 p-8 text-on-surface dark:text-inverse-on-surface bg-surface/90 dark:bg-inverse-surface/90 animate-scale-up">
            {!isSuccess ? (
              <>
                {/* Header */}
                <div className="flex justify-between items-start mb-6">
                  <div>
                    <span className="font-label-sm text-[11px] uppercase tracking-wider text-primary dark:text-inverse-primary font-bold">
                      Completar suscripción
                    </span>
                    <h3 className="font-headline-md text-headline-md text-on-surface dark:text-inverse-on-surface mt-1">
                      Plan {selectedPlan.name}
                    </h3>
                  </div>
                  <button
                    disabled={isProcessing}
                    onClick={() => setIsModalOpen(false)}
                    className="p-1 rounded-full hover:bg-black/5 dark:hover:bg-white/10 text-on-surface-variant transition-colors disabled:opacity-50"
                  >
                    <span className="material-symbols-outlined">close</span>
                  </button>
                </div>

                {/* Plan Summary */}
                <div className="bg-surface-container-low dark:bg-surface-container-lowest rounded-2xl p-4 mb-6 flex justify-between items-center border border-outline-variant/20 dark:border-white/5">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-primary dark:text-inverse-primary text-3xl">
                      {selectedPlan.icon}
                    </span>
                    <div>
                      <p className="font-bold text-sm">Facturación {billingCycle === "monthly" ? "Mensual" : "Anual"}</p>
                      <p className="text-xs text-on-surface-variant dark:text-surface-variant">Cancela cuando quieras</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="font-headline-md text-primary dark:text-inverse-primary">
                      {billingCycle === "monthly" ? selectedPlan.priceMonthly : selectedPlan.priceYearly}€
                    </span>
                    <span className="text-xs text-on-surface-variant dark:text-surface-variant">/mes</span>
                  </div>
                </div>

                {/* Processing State */}
                {isProcessing ? (
                  <div className="flex flex-col items-center justify-center py-12 gap-4">
                    <div className="w-12 h-12 rounded-full border-4 border-primary/20 border-t-primary animate-spin" />
                    <div className="text-center">
                      <p className="font-bold text-base">Procesando pago seguro...</p>
                      <p className="text-sm text-on-surface-variant dark:text-surface-variant/80 mt-1">
                        {processingStep === 0 && "Verificando credenciales bancarias..."}
                        {processingStep === 1 && "Verificando disponibilidad de fondos..."}
                        {processingStep === 2 && "Cifrando y confirmando suscripción..."}
                      </p>
                    </div>
                  </div>
                ) : (
                  /* Payment Form */
                  <form onSubmit={handlePaymentSubmit} className="space-y-4">
                    {/* Card Holder */}
                    <div>
                      <label className="block text-xs font-bold text-on-surface-variant dark:text-surface-variant uppercase tracking-wider mb-2">
                        Titular de la tarjeta
                      </label>
                      <input
                        type="text"
                        required
                        value={cardHolder}
                        onChange={(e) => setCardHolder(e.target.value)}
                        placeholder="Juan Pérez"
                        className="w-full bg-white/50 dark:bg-black/20 border border-outline/30 dark:border-white/10 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-primary dark:focus:border-inverse-primary focus:ring-1 focus:ring-primary dark:focus:ring-inverse-primary transition-all text-on-surface dark:text-inverse-on-surface"
                      />
                      {errors.cardHolder && (
                        <p className="text-error text-xs mt-1">{errors.cardHolder}</p>
                      )}
                    </div>

                    {/* Card Number */}
                    <div>
                      <label className="block text-xs font-bold text-on-surface-variant dark:text-surface-variant uppercase tracking-wider mb-2">
                        Número de Tarjeta
                      </label>
                      <div className="relative">
                        <input
                          type="text"
                          required
                          value={cardNumber}
                          onChange={handleCardNumberChange}
                          placeholder="4000 1234 5678 9010"
                          className="w-full bg-white/50 dark:bg-black/20 border border-outline/30 dark:border-white/10 rounded-xl pl-4 pr-10 py-3 text-sm focus:outline-none focus:border-primary dark:focus:border-inverse-primary focus:ring-1 focus:ring-primary dark:focus:ring-inverse-primary transition-all text-on-surface dark:text-inverse-on-surface"
                        />
                        <span className="material-symbols-outlined absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant dark:text-surface-variant">
                          {getCardTypeIcon(cardNumber)}
                        </span>
                      </div>
                      {errors.cardNumber && (
                        <p className="text-error text-xs mt-1">{errors.cardNumber}</p>
                      )}
                    </div>

                    {/* Expiry & CVV */}
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-bold text-on-surface-variant dark:text-surface-variant uppercase tracking-wider mb-2">
                          Vencimiento
                        </label>
                        <input
                          type="text"
                          required
                          value={cardExpiry}
                          onChange={handleExpiryChange}
                          placeholder="MM/YY"
                          className="w-full bg-white/50 dark:bg-black/20 border border-outline/30 dark:border-white/10 rounded-xl px-4 py-3 text-sm text-center focus:outline-none focus:border-primary dark:focus:border-inverse-primary focus:ring-1 focus:ring-primary dark:focus:ring-inverse-primary transition-all text-on-surface dark:text-inverse-on-surface"
                        />
                        {errors.cardExpiry && (
                          <p className="text-error text-xs mt-1">{errors.cardExpiry}</p>
                        )}
                      </div>
                      <div>
                        <label className="block text-xs font-bold text-on-surface-variant dark:text-surface-variant uppercase tracking-wider mb-2">
                          CVV
                        </label>
                        <input
                          type="password"
                          required
                          value={cardCvv}
                          onChange={handleCvvChange}
                          placeholder="123"
                          className="w-full bg-white/50 dark:bg-black/20 border border-outline/30 dark:border-white/10 rounded-xl px-4 py-3 text-sm text-center focus:outline-none focus:border-primary dark:focus:border-inverse-primary focus:ring-1 focus:ring-primary dark:focus:ring-inverse-primary transition-all text-on-surface dark:text-inverse-on-surface"
                        />
                        {errors.cardCvv && (
                          <p className="text-error text-xs mt-1">{errors.cardCvv}</p>
                        )}
                      </div>
                    </div>

                    {/* Security Badge */}
                    <div className="flex items-center gap-2 justify-center text-on-surface-variant dark:text-surface-variant/80 py-2">
                      <span className="material-symbols-outlined text-sm text-secondary">lock</span>
                      <span className="text-[11px] font-medium">Encriptado SSL de 256 bits y pagos seguros</span>
                    </div>

                    {/* Action Button */}
                    <button
                      type="submit"
                      className="liquid-button w-full py-4 rounded-full text-on-primary font-label-md shadow-lg mt-2 flex items-center justify-center gap-2"
                    >
                      <span className="material-symbols-outlined text-base">check_circle</span>
                      Autorizar Pago Seguro
                    </button>
                  </form>
                )}
              </>
            ) : (
              /* Success Screen */
              <div className="flex flex-col items-center text-center py-6 animate-scale-up">
                {/* Simulated Confetti / Particle Effects */}
                <div className="absolute inset-0 pointer-events-none overflow-hidden">
                  <div className="absolute w-2.5 h-2.5 bg-primary rounded-full animate-ping top-10 left-12" style={{ animationDelay: "0.2s" }} />
                  <div className="absolute w-2 h-2 bg-tertiary rounded-full animate-ping top-20 right-16" style={{ animationDelay: "0.5s" }} />
                  <div className="absolute w-3 h-3 bg-secondary rounded-full animate-ping bottom-16 left-20" style={{ animationDelay: "0.7s" }} />
                  <div className="absolute w-2 h-2 bg-primary rounded-full animate-ping bottom-28 right-24" style={{ animationDelay: "1s" }} />
                </div>

                <div className="w-20 h-20 rounded-full bg-secondary-container dark:bg-secondary flex items-center justify-center mb-6 animate-bounce">
                  <span className="material-symbols-outlined text-5xl text-on-secondary-container dark:text-white">
                    check
                  </span>
                </div>

                <h3 className="font-headline-lg text-headline-lg text-primary dark:text-inverse-primary mb-2">
                  ¡Suscripción Exitosa!
                </h3>

                <p className="font-body-md text-on-surface-variant dark:text-surface-variant mb-6 px-4">
                  Te has suscrito correctamente al <strong className="text-on-surface dark:text-inverse-on-surface">Plan {selectedPlan.name}</strong>. ¡Ya puedes disfrutar de todos los beneficios y funcionalidades exclusivas!
                </p>

                <div className="w-full space-y-3">
                  <button
                    onClick={() => {
                      setIsModalOpen(false);
                      onNavigateToKitchen();
                    }}
                    className="liquid-button w-full py-4 rounded-full text-on-primary font-label-md shadow-lg"
                  >
                    Ir a Mi Cocina
                  </button>
                  <button
                    onClick={() => setIsModalOpen(false)}
                    className="w-full py-3 rounded-full hover:bg-black/5 dark:hover:bg-white/5 text-on-surface-variant dark:text-surface-variant font-label-md transition-colors"
                  >
                    Cerrar Detalle
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default Paypage;
