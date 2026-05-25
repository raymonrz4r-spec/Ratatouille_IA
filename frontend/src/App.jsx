import { useEffect, useMemo, useState } from "react";
import ErrorToast from "./components/ErrorToast.jsx";
import RecipeGrid from "./components/RecipeGrid.jsx";
import SearchBar from "./components/SearchBar.jsx";

const STORAGE_KEY = "video2recipe.recipes";

function loadRecipes() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
}

function App() {
  const [recipes, setRecipes] = useState(loadRecipes);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(recipes));
  }, [recipes]);

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
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/api/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || "No pude extraer la receta.");
      }

      setRecipes((current) => {
        const next = [payload, ...current.filter((recipe) => recipe.sourceUrl !== payload.sourceUrl)];
        return next.slice(0, 50);
      });
    } catch (extractError) {
      setError(extractError.message || "Ocurrio un error inesperado.");
    } finally {
      setIsLoading(false);
    }
  }

  function handleToggleIngredient(recipeId, ingredientId) {
    setRecipes((current) =>
      current.map((recipe) => {
        if (recipe.id !== recipeId) return recipe;
        return {
          ...recipe,
          ingredients: recipe.ingredients.map((ingredient) =>
            ingredient.id === ingredientId ? { ...ingredient, checked: !ingredient.checked } : ingredient,
          ),
        };
      }),
    );
  }

  function handleDelete(recipeId) {
    setRecipes((current) => current.filter((recipe) => recipe.id !== recipeId));
  }

  function handleClearAll() {
    setRecipes([]);
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
          <div className="font-display-lg text-display-lg text-primary dark:text-inverse-primary hidden md:block">Ratatouille</div>
          <div className="font-display-lg-mobile text-display-lg-mobile text-primary dark:text-inverse-primary md:hidden">Ratatouille</div>
          <nav className="hidden md:flex gap-8">
            <a className="text-primary dark:text-inverse-primary font-bold border-b-2 border-primary dark:border-inverse-primary pb-1" href="#">My Kitchen</a>
            <a className="text-on-surface-variant dark:text-surface-variant hover:text-primary transition-colors hover:bg-white/20 dark:hover:bg-white/5 transition-all duration-300" href="#">Favorites</a>
            <a className="text-on-surface-variant dark:text-surface-variant hover:text-primary transition-colors hover:bg-white/20 dark:hover:bg-white/5 transition-all duration-300" href="#">Pantry</a>
            <a className="text-on-surface-variant dark:text-surface-variant hover:text-primary transition-colors hover:bg-white/20 dark:hover:bg-white/5 transition-all duration-300" href="#">Explore</a>
          </nav>
          <div className="flex gap-4">
            <button className="scale-95 active:scale-90 transition-transform hover:bg-white/20 p-2 rounded-full">
              <span className="material-symbols-outlined text-primary">notifications</span>
            </button>
            <button className="scale-95 active:scale-90 transition-transform hover:bg-white/20 p-2 rounded-full">
              <span className="material-symbols-outlined text-primary">account_circle</span>
            </button>
          </div>
        </div>
      </header>

      <main className="flex-grow w-full max-w-container-max mx-auto px-margin-mobile md:px-gutter py-12 flex flex-col gap-12">
        <section className="flex flex-col items-center text-center gap-6">
          <h1 className="font-display-lg text-display-lg text-primary">Links to recipes</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant max-w-2xl">TikTok, Reels y YouTube convertidos en recetas</p>
          <div className="w-full max-w-3xl mt-6">
            <SearchBar onSubmit={handleExtract} isLoading={isLoading} />
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

        <section className="flex flex-col gap-8 mt-8">
          <div className="flex justify-between items-end">
            <h2 className="font-headline-lg text-headline-lg text-primary">Colección</h2>
            {recipes.length > 0 && (
              <button
                className="text-error hover:text-on-error hover:bg-error transition-colors px-4 py-2 rounded-full font-label-md flex items-center gap-2"
                type="button"
                onClick={handleClearAll}
                title="Borrar colección"
              >
                <span className="material-symbols-outlined text-[20px]">delete</span>
                <span className="hidden sm:inline">Borrar todo</span>
              </button>
            )}
          </div>
          <RecipeGrid recipes={recipes} onToggleIngredient={handleToggleIngredient} onDelete={handleDelete} />
        </section>
      </main>

      <footer className="bg-surface-container-low dark:bg-surface-container-lowest w-full mt-auto border-t border-outline-variant/30">
        <div className="flex flex-col items-center gap-4 py-12 px-margin-desktop w-full max-w-container-max mx-auto">
          <div className="font-headline-sm text-headline-sm text-secondary">Ratatouille AI</div>
          <p className="font-label-sm text-label-sm text-secondary dark:text-secondary-fixed opacity-80 hover:opacity-100 transition-opacity">© 2024 Ratatouille AI. Crafted for home chefs.</p>
          <div className="flex gap-6 mt-4">
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">Privacy Policy</a>
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">Terms of Service</a>
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">API Status</a>
            <a className="font-label-sm text-label-sm text-on-surface-variant/70 hover:text-tertiary transition-colors" href="#">Support</a>
          </div>
        </div>
      </footer>

      <ErrorToast message={error} onClose={() => setError("")} />
    </>
  );
}

export default App;
