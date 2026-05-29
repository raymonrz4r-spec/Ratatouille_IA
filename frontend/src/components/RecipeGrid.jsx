import RecipeCard from "./RecipeCard.jsx";

function RecipeGrid({ recipes, onSelectRecipe, actionLabel, onAction }) {
  if (recipes.length === 0) {
    return (
      <div className="glass-panel grid min-h-[360px] place-items-center rounded-xl border border-dashed border-outline-variant px-6 py-12 text-center w-full">
        <div className="max-w-md">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-secondary-container text-secondary">
            <span className="material-symbols-outlined text-3xl">list_alt</span>
          </span>
          <h3 className="mt-4 font-headline-md text-headline-md text-on-surface">Aún no hay recetas</h3>
          <p className="mt-2 font-body-md text-body-md text-on-surface-variant">
            Pega un video con una receta narrada para crear tu primera tarjeta.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
      {recipes.map((recipe) => (
        <RecipeCard
          key={recipe.id}
          recipe={recipe}
          onSelectRecipe={onSelectRecipe}
          actionLabel={actionLabel}
          onAction={onAction}
        />
      ))}
    </div>
  );
}

export default RecipeGrid;
