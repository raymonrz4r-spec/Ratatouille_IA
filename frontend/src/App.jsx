import { useCallback, useEffect, useMemo, useState } from "react";
import ErrorToast from "./components/ErrorToast.jsx";
import RecipeGrid from "./components/RecipeGrid.jsx";
import SearchBar from "./components/SearchBar.jsx";
import Patrocinador from "./components/Patrocinador.jsx";
import LoginPage from "./components/LoginPage.jsx";
import Paypage from "./Paypage.jsx";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const SESSION_KEY = "video2recipe.session";

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiRequest(path, options = {}) {
  const { token, ...fetchOptions } = options;
  const response = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(fetchOptions.headers || {}),
    },
  });

  if (response.status === 204) return null;

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(payload.detail || "No se pudo completar la solicitud.", response.status);
  }

  return payload;
}

function loadSession() {
  try {
    const saved = localStorage.getItem(SESSION_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}

function loadSavedPlan() {
  try {
    return localStorage.getItem("video2recipe.userPlan") || "Gratuito";
  } catch {
    return "Gratuito";
  }
}

function App() {
  const [session, setSession] = useState(loadSession);
  const [recipes, setRecipes] = useState([]);
  const [exploreRecipes, setExploreRecipes] = useState([]);
  const [guestRecipe, setGuestRecipe] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExploreLoading, setIsExploreLoading] = useState(false);
  const [error, setError] = useState("");
  const [userPlan, setUserPlan] = useState(loadSavedPlan);
  const [currentView, setCurrentView] = useState("kitchen"); // "kitchen" or "subscriptions"
  const [selectedRecipeId, setSelectedRecipeId] = useState(null);

  const selectedRecipe = useMemo(() => {
    return [...recipes, ...exploreRecipes, guestRecipe].filter(Boolean).find((r) => r.id === selectedRecipeId);
  }, [exploreRecipes, guestRecipe, recipes, selectedRecipeId]);

  const selectedRecipeProgress = useMemo(() => {
    if (!selectedRecipe) return 0;
    const checked = selectedRecipe.ingredients.filter((i) => i.checked).length;
    return selectedRecipe.ingredients.length
      ? Math.round((checked / selectedRecipe.ingredients.length) * 100)
      : 0;
  }, [selectedRecipe]);

  useEffect(() => {
    try {
      localStorage.setItem("video2recipe.userPlan", userPlan);
    } catch (e) {
      console.error("No se pudo guardar el plan de usuario", e);
    }
  }, [userPlan]);

  useEffect(() => {
    try {
      if (session) {
        localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      } else {
        localStorage.removeItem(SESSION_KEY);
      }
    } catch (e) {
      console.error("No se pudo guardar la sesion", e);
    }
  }, [session]);

  const withRecipeScope = useCallback((items, scope, token = session?.accessToken) => {
    return items.map((recipe) => ({
      ...recipe,
      _scope: scope,
      imageUrl: recipe.imageUrl && scope === "private" && token
        ? `${API_URL}/api/recipes/${recipe.id}/image?access_token=${encodeURIComponent(token)}`
        : recipe.imageUrl,
    }));
  }, [session?.accessToken]);

  useEffect(() => {
    let isMounted = true;

    async function loadInitialData() {
      if (!session?.accessToken) {
        setRecipes([]);
        setUserPlan("Gratuito");
        return;
      }

      try {
        const [savedRecipes, savedSubscription] = await Promise.all([
          apiRequest("/api/recipes", { token: session.accessToken }),
          apiRequest("/api/subscription", { token: session.accessToken }),
        ]);

        if (!isMounted) return;
        setRecipes(Array.isArray(savedRecipes) ? withRecipeScope(savedRecipes, "private", session.accessToken) : []);
        setUserPlan(savedSubscription?.plan || "Gratuito");
      } catch (loadError) {
        if (isMounted) {
          if (handleAuthError(loadError)) return;
          setError(loadError.message || "No pude cargar los datos guardados.");
        }
      }
    }

    loadInitialData();
    return () => {
      isMounted = false;
    };
  }, [session?.accessToken, withRecipeScope]);

  const stats = useMemo(() => {
    const ingredients = recipes.reduce((total, recipe) => total + recipe.ingredients.length, 0);
    const cooked = recipes.reduce(
      (total, recipe) => total + recipe.ingredients.filter((ingredient) => ingredient.checked).length,
      0,
    );

    return {
      recipes: recipes.length,
      ingredients,
      checked: cooked,
    };
  }, [recipes]);

  async function handleExtract(url) {
    setError("");
    setIsLoading(true);

    try {
      const payload = await apiRequest("/api/extract", {
        method: "POST",
        ...(session?.accessToken ? { token: session.accessToken } : {}),
        body: JSON.stringify({ url }),
      });
      const scope = session?.accessToken ? "private" : "public";
      const nextRecipe = withRecipeScope([payload], scope, session?.accessToken)[0];

      if (scope === "private") {
        setRecipes((current) => {
          const next = [nextRecipe, ...current.filter((recipe) => recipe.sourceUrl !== payload.sourceUrl)];
          return next.slice(0, 50);
        });
        setGuestRecipe(null);
      } else {
        setGuestRecipe(nextRecipe);
        setError("Receta creada. Inicia sesion para guardarla en tu coleccion.");
      }
    } catch (extractError) {
      if (handleAuthError(extractError)) return;
      setError(extractError.message || "Ocurrio un error inesperado.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleToggleIngredient(recipeId, ingredientId) {
    const recipe = recipes.find((item) => item.id === recipeId);
    const ingredient = recipe?.ingredients.find((item) => item.id === ingredientId);
    if (!recipe || !ingredient) return;

    const previousRecipes = recipes;
    const nextChecked = !ingredient.checked;

    setRecipes((current) =>
      current.map((recipe) => {
        if (recipe.id !== recipeId) return recipe;
        return {
          ...recipe,
          ingredients: recipe.ingredients.map((ingredient) =>
            ingredient.id === ingredientId ? { ...ingredient, checked: nextChecked } : ingredient,
          ),
        };
      }),
    );

    try {
      const updatedRecipe = await apiRequest(`/api/recipes/${recipeId}/ingredients/${ingredientId}`, {
        method: "PATCH",
        token: session.accessToken,
        body: JSON.stringify({ checked: nextChecked }),
      });
      const authenticatedRecipe = withRecipeScope([updatedRecipe], "private", session.accessToken)[0];
      setRecipes((current) =>
        current.map((recipe) => (recipe.id === authenticatedRecipe.id ? authenticatedRecipe : recipe)),
      );
    } catch (toggleError) {
      setRecipes(previousRecipes);
      if (handleAuthError(toggleError)) return;
      setError(toggleError.message || "No pude actualizar el ingrediente.");
    }
  }

  async function handleDelete(recipeId) {
    const previousRecipes = recipes;
    setRecipes((current) => current.filter((recipe) => recipe.id !== recipeId));

    try {
      await apiRequest(`/api/recipes/${recipeId}`, { method: "DELETE", token: session.accessToken });
    } catch (deleteError) {
      setRecipes(previousRecipes);
      if (handleAuthError(deleteError)) return;
      setError(deleteError.message || "No pude eliminar la receta.");
    }
  }

  async function handleClearAll() {
    const previousRecipes = recipes;
    setRecipes([]);

    try {
      await apiRequest("/api/recipes", { method: "DELETE", token: session.accessToken });
    } catch (deleteError) {
      setRecipes(previousRecipes);
      if (handleAuthError(deleteError)) return;
      setError(deleteError.message || "No pude borrar la coleccion.");
    }
  }

  const handleSubscribe = useCallback(
    async (plan) => {
      const previousPlan = userPlan;
      setUserPlan(plan);

      try {
        const savedSubscription = await apiRequest("/api/subscription", {
          method: "PUT",
          token: session.accessToken,
          body: JSON.stringify({ plan }),
        });
        setUserPlan(savedSubscription.plan);
      } catch (subscriptionError) {
        setUserPlan(previousPlan);
        if (handleAuthError(subscriptionError)) return;
        setError(subscriptionError.message || "No pude guardar la suscripcion.");
      }
    },
    [session?.accessToken, userPlan],
  );

  const loadExploreRecipes = useCallback(async () => {
    if (!session?.accessToken) {
      setError("Inicia sesion para explorar recetas.");
      setCurrentView("login");
      return;
    }

    setIsExploreLoading(true);
    setError("");
    try {
      const payload = await apiRequest("/api/explore/recipes", { token: session.accessToken });
      setExploreRecipes(Array.isArray(payload) ? withRecipeScope(payload, "public", session.accessToken) : []);
    } catch (exploreError) {
      if (handleAuthError(exploreError)) return;
      setError(exploreError.message || "No pude cargar Explore.");
    } finally {
      setIsExploreLoading(false);
    }
  }, [session?.accessToken, withRecipeScope]);

  useEffect(() => {
    if (currentView === "explore") {
      loadExploreRecipes();
    }
  }, [currentView, loadExploreRecipes]);

  async function handleSaveExploreRecipe(recipeId) {
    if (!session?.accessToken) {
      setCurrentView("login");
      return;
    }

    if (userPlan !== "Gourmet" && userPlan !== "Chef") {
      setError("Guardar recetas de Explore requiere un plan Gourmet o Chef.");
      setCurrentView("subscriptions");
      return;
    }

    try {
      const payload = await apiRequest(`/api/recipes/${recipeId}/save`, {
        method: "POST",
        token: session.accessToken,
      });
      const savedRecipe = withRecipeScope([payload.recipe], "private", session.accessToken)[0];
      setRecipes((current) => {
        const next = [savedRecipe, ...current.filter((recipe) => recipe.sourceUrl !== savedRecipe.sourceUrl)];
        return next.slice(0, 50);
      });
      setCurrentView("kitchen");
      setError("");
    } catch (saveError) {
      if (saveError.status === 403) {
        setError(saveError.message);
        setCurrentView("subscriptions");
        return;
      }
      if (handleAuthError(saveError)) return;
      setError(saveError.message || "No pude guardar la receta.");
    }
  }

  const handleGoogleCredential = useCallback(async (idToken) => {
    setError("");
    setIsLoading(true);

    try {
      const auth = await apiRequest("/api/auth/google", {
        method: "POST",
        body: JSON.stringify({ idToken }),
      });
      setSession(auth);
      setUserPlan("Gratuito");
      setCurrentView("kitchen");
    } catch (loginError) {
      setError(loginError.message || "No pude iniciar sesion con Google.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  function handleLogout() {
    setSession(null);
    setRecipes([]);
    setExploreRecipes([]);
    setUserPlan("Gratuito");
    setSelectedRecipeId(null);
    setCurrentView("kitchen");
  }

  function handleAuthError(errorToHandle) {
    if (errorToHandle?.status === 401) {
      handleLogout();
      setError("Tu sesion expiro. Inicia sesion otra vez.");
      return true;
    }
    return false;
  }

  return (
    <>
      <div className="liquid-bg">
        <div className="blob blob-1"></div>
        <div className="blob blob-2"></div>
        <div className="blob blob-3"></div>
      </div>

      <header className="bg-surface/60 dark:bg-inverse-surface/60 backdrop-blur-xl docked full-width top-0 sticky border-b border-white/40 dark:border-white/10 shadow-sm z-50">
        <div className="flex justify-between items-center w-full px-gutter max-w-container-max mx-auto h-20">
          <button onClick={() => setCurrentView("kitchen")} className="text-left focus:outline-none">
            <div className="font-display-lg text-display-lg text-primary dark:text-inverse-primary hidden md:block select-none">Ratatouille</div>
            <div className="font-display-lg-mobile text-display-lg-mobile text-primary dark:text-inverse-primary md:hidden select-none">Ratatouille</div>
          </button>
          <nav className="hidden md:flex gap-8">
            <button
              onClick={() => setCurrentView("kitchen")}
              className={`font-label-md transition-all duration-300 pb-1 focus:outline-none ${currentView === "kitchen"
                ? "text-primary dark:text-inverse-primary font-bold border-b-2 border-primary dark:border-inverse-primary"
                : "text-on-surface-variant dark:text-surface-variant hover:text-primary"
                }`}
            >
              My Kitchen
            </button>
            <button
              onClick={() => setCurrentView("subscriptions")}
              className={`font-label-md transition-all duration-300 pb-1 focus:outline-none ${currentView === "subscriptions"
                ? "text-primary dark:text-inverse-primary font-bold border-b-2 border-primary dark:border-inverse-primary"
                : "text-on-surface-variant dark:text-surface-variant hover:text-primary"
                }`}
            >
              Planes
            </button>
            <button
              onClick={() => setError("La sección de Favoritos estará disponible próximamente.")}
              className="text-on-surface-variant dark:text-surface-variant hover:text-primary font-label-md transition-all duration-300 pb-1 focus:outline-none"
            >
              Favorites
            </button>

            <button
              onClick={() => setCurrentView(session?.accessToken ? "explore" : "login")}
              className={`font-label-md transition-all duration-300 pb-1 focus:outline-none ${currentView === "explore" ? "text-primary dark:text-inverse-primary font-bold border-b-2 border-primary dark:border-inverse-primary" : "text-on-surface-variant dark:text-surface-variant hover:text-primary"}`}
            >
              Explore
            </button>
          </nav>
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex">
              <span className={`text-[11px] font-bold px-3 py-1 rounded-full uppercase tracking-wider flex items-center gap-1 shadow-sm border border-outline/10 ${userPlan === "Chef"
                ? "bg-tertiary-container/30 text-tertiary dark:text-tertiary-fixed-dim"
                : userPlan === "Gourmet"
                  ? "bg-primary-container/20 text-primary dark:text-inverse-primary"
                  : "bg-surface-container-high dark:bg-inverse-surface text-on-surface-variant dark:text-surface-variant"
                }`}>
                <span className="material-symbols-outlined text-[14px]">
                  {userPlan === "Chef" ? "restaurant" : userPlan === "Gourmet" ? "skillet" : "egg_alt"}
                </span>
                {userPlan}
              </span>
            </div>

            <button
              onClick={() => (session?.accessToken ? handleLogout() : setCurrentView("login"))}
              className="scale-95 active:scale-90 transition-transform hover:bg-white/20 dark:hover:bg-white/5 p-2 rounded-full flex items-center focus:outline-none"
              title="Ver plan de suscripción"
            >
              {session?.user?.pictureUrl ? (
                <img
                  src={session.user.pictureUrl}
                  alt={session.user.name || session.user.email}
                  className="h-8 w-8 rounded-full object-cover border border-white/40"
                />
              ) : (
                <span className="material-symbols-outlined text-primary">account_circle</span>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="flex-grow w-full max-w-container-max mx-auto px-margin-mobile md:px-gutter py-12 flex flex-col gap-12">
        {currentView === "kitchen" ? (
          <>
            <section className="flex flex-col items-center text-center gap-6 animate-fade-in">
              <h1 className="font-display-lg text-display-lg text-primary">Links to recipes</h1>
              <p className="font-body-lg text-body-lg text-on-surface-variant max-w-2xl">TikTok, Reels y YouTube convertidos en recetas</p>
              <div className="w-full max-w-3xl mt-6 flex flex-col gap-6">
                <SearchBar onSubmit={handleExtract} isLoading={isLoading} />
                <Patrocinador />
              </div>
            </section>

            <section className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full">
              <div className="glass-panel rounded-xl p-card-padding flex flex-col gap-4 items-center justify-center liquid-easing hover:-translate-y-1">
                <span className="material-symbols-outlined text-4xl text-primary">menu_book</span>
                <h3 className="font-headline-lg text-headline-lg text-on-surface">{stats.recipes}</h3>
                <p className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">Recetas</p>
              </div>
              <div className="glass-panel rounded-xl p-card-padding flex flex-col gap-4 items-center justify-center liquid-easing hover:-translate-y-1">
                <span className="material-symbols-outlined text-4xl text-secondary">shopping_basket</span>
                <h3 className="font-headline-lg text-headline-lg text-on-surface">{stats.ingredients}</h3>
                <p className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">Ingredientes</p>
              </div>
              <div className="glass-panel rounded-xl p-card-padding flex flex-col gap-4 items-center justify-center liquid-easing hover:-translate-y-1">
                <span className="material-symbols-outlined text-4xl text-tertiary">check_circle</span>
                <h3 className="font-headline-lg text-headline-lg text-on-surface">{stats.checked}</h3>
                <p className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">Marcados</p>
              </div>
            </section>

            {guestRecipe && (
              <section className="flex flex-col gap-5 mt-4">
                <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
                  <div>
                    <h2 className="font-headline-lg text-headline-lg text-primary">Resultado reciente</h2>
                    <p className="font-body-md text-on-surface-variant">
                      Esta receta queda en Explore. Para guardarla en tu coleccion necesitas iniciar sesion.
                    </p>
                  </div>
                  <button className="liquid-button rounded-full px-5 py-3 text-on-primary font-label-md" type="button" onClick={() => setCurrentView("login")}>
                    Iniciar sesion
                  </button>
                </div>
                <RecipeGrid recipes={[guestRecipe]} onSelectRecipe={setSelectedRecipeId} />
              </section>
            )}

            <section className="flex flex-col gap-8 mt-8">
              <div className="flex justify-between items-end">
                <h2 className="font-headline-lg text-headline-lg text-primary">Coleccion</h2>
                {session?.accessToken && recipes.length > 0 && (
                  <button className="text-error hover:text-on-error hover:bg-error transition-colors px-4 py-2 rounded-full font-label-md flex items-center gap-2" type="button" onClick={handleClearAll} title="Borrar coleccion">
                    <span className="material-symbols-outlined text-[20px]">delete</span>
                    <span className="hidden sm:inline">Borrar todo</span>
                  </button>
                )}
              </div>
              {session?.accessToken ? (
                <RecipeGrid recipes={recipes} onSelectRecipe={setSelectedRecipeId} />
              ) : (
                <div className="glass-panel rounded-xl p-8 text-center border border-dashed border-outline-variant">
                  <span className="material-symbols-outlined text-4xl text-primary">lock</span>
                  <h3 className="mt-3 font-headline-md text-headline-md text-on-surface">Tu coleccion vive en tu cuenta</h3>
                  <p className="mt-2 font-body-md text-on-surface-variant">Busca recetas como invitado. Inicia sesion para guardarlas en tu coleccion privada.</p>
                  <button className="liquid-button mt-5 rounded-full px-6 py-3 text-on-primary font-label-md" type="button" onClick={() => setCurrentView("login")}>
                    Iniciar sesion
                  </button>
                </div>
              )}
            </section>
          </>
        ) : currentView === "explore" ? (
          <section className="flex flex-col gap-8">
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
              <div>
                <h1 className="font-display-lg text-display-lg text-primary">Explore</h1>
                <p className="font-body-lg text-on-surface-variant">Las ultimas 50 recetas creadas por la comunidad.</p>
              </div>
              {isExploreLoading && <span className="font-label-md text-on-surface-variant">Cargando...</span>}
            </div>
            <RecipeGrid recipes={exploreRecipes} onSelectRecipe={setSelectedRecipeId} actionLabel={userPlan === "Gourmet" || userPlan === "Chef" ? "Guardar" : "Gourmet"} onAction={handleSaveExploreRecipe} />
          </section>
        ) : currentView === "login" ? (
          <LoginPage error={error} isLoading={isLoading} onGoogleCredential={handleGoogleCredential} />
        ) : (
          <Paypage
            currentPlan={userPlan}
            onSubscribe={handleSubscribe}
            onNavigateToKitchen={() => setCurrentView("kitchen")}
          />
        )}
      </main>

      <footer className="bg-surface-container-low dark:bg-surface-container-lowest w-full mt-auto border-t border-outline-variant/30">
        <div className="flex flex-col items-center gap-4 py-12 px-margin-desktop w-full max-w-container-max mx-auto">
          <div className="font-headline-sm text-headline-sm text-secondary">Ratatouille AI</div>
          <p className="font-label-sm text-label-sm text-secondary dark:text-secondary-fixed opacity-80 hover:opacity-100 transition-opacity">© 2026 Ratatouille AI. Crafted for home chefs.</p>
          <div className="flex gap-6 mt-4">
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">Privacy Policy</a>
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">Terms of Service</a>
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">API Status</a>
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">Support</a>
          </div>
        </div>
      </footer>

      {/* Recipe Detail Pop-up Modal */}
      {selectedRecipe && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          {/* Backdrop blur */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-md"
            onClick={() => setSelectedRecipeId(null)}
          />

          {/* Modal Container */}
          <div className="glass-panel w-full max-w-2xl rounded-3xl border border-white/40 dark:border-white/10 shadow-2xl relative overflow-y-auto max-h-[90vh] z-10 p-8 text-on-surface dark:text-inverse-on-surface bg-surface/95 dark:bg-inverse-surface/95 animate-scale-up flex flex-col gap-6">

            {/* Header */}
            <div className="flex justify-between items-start">
              <div className="flex flex-col gap-2">
                <span className="bg-primary-container/20 dark:bg-primary-container/30 text-primary dark:text-inverse-primary font-label-sm px-3 py-1 rounded-full border border-white/40 dark:border-white/5 w-fit">
                  {selectedRecipe.platform}
                </span>
                <h3 className="font-headline-lg text-headline-lg text-primary dark:text-inverse-primary leading-tight pr-8">
                  {selectedRecipe.title}
                </h3>
              </div>
              <button
                onClick={() => setSelectedRecipeId(null)}
                className="absolute top-6 right-6 p-1.5 rounded-full hover:bg-black/5 dark:hover:bg-white/10 text-on-surface-variant dark:text-surface-variant transition-colors"
                title="Cerrar detalles"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            {/* Recipe Image if available */}
            {selectedRecipe.imageUrl && (
              <div className="w-full h-64 bg-secondary-container dark:bg-inverse-surface/30 rounded-2xl overflow-hidden border border-white/20 dark:border-white/5">
                <img
                  src={selectedRecipe.imageUrl}
                  alt={selectedRecipe.title}
                  className="w-full h-full object-cover"
                />
              </div>
            )}

            {/* Recipe Metadata badges */}
            <div className="flex flex-wrap gap-3">
              {selectedRecipe.servings && (
                <span className="bg-surface-container-low dark:bg-inverse-surface/40 text-secondary dark:text-secondary-fixed-dim font-label-sm px-4 py-2 rounded-full border border-outline-variant/10 flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px]">group</span>
                  Porciones: {selectedRecipe.servings}
                </span>
              )}
              {selectedRecipe.prepTime && (
                <span className="bg-surface-container-low dark:bg-inverse-surface/40 text-secondary dark:text-secondary-fixed-dim font-label-sm px-4 py-2 rounded-full border border-outline-variant/10 flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px]">schedule</span>
                  Preparación: {selectedRecipe.prepTime}
                </span>
              )}
              {selectedRecipe.cookTime && (
                <span className="bg-surface-container-low dark:bg-inverse-surface/40 text-secondary dark:text-secondary-fixed-dim font-label-sm px-4 py-2 rounded-full border border-outline-variant/10 flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px]">local_fire_department</span>
                  Cocción: {selectedRecipe.cookTime}
                </span>
              )}
            </div>

            {/* Transcript Summary */}
            {selectedRecipe.transcriptSummary && (
              <div className="bg-surface-container-low dark:bg-inverse-surface/20 rounded-2xl p-5 border border-outline-variant/10">
                <p className="font-body-md text-on-surface-variant dark:text-surface-variant/90 italic">
                  "{selectedRecipe.transcriptSummary}"
                </p>
              </div>
            )}

            {/* Progress bar */}
            <div className="flex items-center gap-4 py-2 border-y border-outline-variant/20 dark:border-white/5">
              <span className="font-label-md text-secondary dark:text-secondary-fixed-dim shrink-0">Progreso:</span>
              <div className="flex-grow bg-surface-variant dark:bg-inverse-surface/60 h-3 rounded-full overflow-hidden">
                <div className="bg-secondary h-full rounded-full transition-all duration-300" style={{ width: `${selectedRecipeProgress}%` }}></div>
              </div>
              <span className="font-label-sm text-label-sm font-bold text-on-surface-variant dark:text-surface-variant/80 shrink-0">{selectedRecipeProgress}%</span>
            </div>

            {/* Details Content (Ingredients, Steps, Notes) */}
            <div className="space-y-6 overflow-y-visible">

              {/* Ingredients checklist */}
              <section>
                <h4 className="mb-3 font-label-md text-secondary dark:text-secondary-fixed-dim uppercase tracking-wider">
                  Ingredientes
                </h4>
                <ul className="space-y-2">
                  {selectedRecipe.ingredients.map((ingredient) => (
                    <li key={ingredient.id}>
                      <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-outline-variant/20 dark:border-white/5 px-4 py-3 transition hover:border-primary hover:bg-primary-container/10 bg-white/20 dark:bg-black/10">
                        <input
                          className="mt-1 h-4 w-4 rounded border-outline accent-primary"
                          type="checkbox"
                          checked={ingredient.checked}
                          disabled={selectedRecipe._scope !== "private"}
                          onChange={() => handleToggleIngredient(selectedRecipe.id, ingredient.id)}
                        />
                        <span className={ingredient.checked ? "font-body-md text-on-surface-variant/60 dark:text-surface-variant/50 line-through" : "font-body-md text-on-surface dark:text-inverse-on-surface"}>
                          {ingredient.text}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </section>

              {/* Steps */}
              <section>
                <h4 className="mb-3 font-label-md text-secondary dark:text-secondary-fixed-dim uppercase tracking-wider">
                  Pasos
                </h4>
                <ol className="space-y-3">
                  {selectedRecipe.steps.map((step, index) => (
                    <li className="flex gap-4 rounded-xl bg-surface-container dark:bg-inverse-surface/30 px-4 py-3 font-body-md text-on-surface dark:text-inverse-on-surface border border-outline-variant/10" key={`${selectedRecipe.id}-step-${index}`}>
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary dark:bg-surface-tint text-sm font-bold text-on-primary">
                        {index + 1}
                      </span>
                      <span className="pt-0.5">{step}</span>
                    </li>
                  ))}
                </ol>
              </section>

              {/* Notes */}
              {selectedRecipe.notes?.length ? (
                <section>
                  <h4 className="mb-3 font-label-md text-secondary dark:text-secondary-fixed-dim uppercase tracking-wider">
                    Notas
                  </h4>
                  <ul className="space-y-2 font-body-md text-on-surface-variant dark:text-surface-variant/90 bg-tertiary-container/10 dark:bg-tertiary-container/5 p-4 rounded-2xl border border-tertiary-container/10">
                    {selectedRecipe.notes.map((note, index) => (
                      <li key={`${selectedRecipe.id}-note-${index}`} className="flex gap-2 items-start">
                        <span className="material-symbols-outlined text-[20px] text-tertiary mt-0.5">info</span>
                        <span>{note}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>

            {/* Footer Buttons */}
            <div className="mt-4 flex items-center justify-between gap-3 border-t border-outline-variant/30 dark:border-white/10 pt-6">
              <a
                className="inline-flex h-12 items-center gap-2 rounded-full border border-outline/50 dark:border-white/20 px-6 font-label-md text-on-surface dark:text-inverse-on-surface hover:border-primary dark:hover:border-inverse-primary hover:text-primary dark:hover:text-inverse-primary transition"
                href={selectedRecipe.sourceUrl}
                target="_blank"
                rel="noreferrer"
              >
                <span className="material-symbols-outlined text-[20px]">open_in_new</span>
                Ver Video
              </a>
              <button
                className="inline-flex h-12 items-center gap-2 rounded-full border border-error/50 px-6 font-label-md text-error hover:bg-error hover:text-on-error transition"
                type="button"
                onClick={() => {
                  if (window.confirm("¿Seguro que deseas eliminar esta receta?")) {
                    handleDelete(selectedRecipe.id);
                    setSelectedRecipeId(null);
                  }
                }}
                title="Eliminar receta"
              >
                <span className="material-symbols-outlined text-[20px]">delete</span>
                Eliminar
              </button>
            </div>

          </div>
        </div>
      )}

      <ErrorToast message={error} onClose={() => setError("")} />
    </>
  );
}

export default App;
