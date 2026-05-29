import { useMemo } from "react";

function RecipeCard({ recipe, onSelectRecipe }) {
  const checkedCount = useMemo(
    () => recipe.ingredients.filter((ingredient) => ingredient.checked).length,
    [recipe.ingredients],
  );

  const progress = recipe.ingredients.length ? Math.round((checkedCount / recipe.ingredients.length) * 100) : 0;

  return (
    <article 
      onClick={() => onSelectRecipe(recipe.id)}
      className="glass-panel rounded-xl overflow-hidden flex flex-col liquid-easing hover:-translate-y-1 group cursor-pointer"
    >
      <div className="h-48 w-full bg-secondary-container relative overflow-hidden flex items-center justify-center">
         {recipe.imageUrl ? (
            <img src={recipe.imageUrl} alt={recipe.title} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity duration-500" />
         ) : (
            <span className="material-symbols-outlined text-6xl text-secondary opacity-50 group-hover:opacity-80 transition-opacity">restaurant</span>
         )}
         <div className="absolute top-4 left-4">
            <span className="bg-surface/80 backdrop-blur-sm text-secondary font-label-sm px-3 py-1 rounded-full border border-white/40 shadow-sm">
              {recipe.platform}
            </span>
         </div>
      </div>
      <div className="p-6 flex flex-col gap-4 flex-grow">
        <div className="flex justify-between items-start gap-3">
          <div>
            <h3 className="font-headline-md text-headline-md text-on-surface dark:text-inverse-on-surface leading-tight line-clamp-2">{recipe.title}</h3>
            {recipe.transcriptSummary && (
               <p className="mt-2 line-clamp-2 font-body-md text-sm text-on-surface-variant dark:text-surface-variant/80">{recipe.transcriptSummary}</p>
            )}
          </div>
          <button 
             className="text-outline hover:text-primary transition-colors flex items-center p-1.5 rounded-full hover:bg-black/5 dark:hover:bg-white/5 shrink-0"
             onClick={(e) => { e.stopPropagation(); onSelectRecipe(recipe.id); }}
             title="Ver receta completa"
          >
            <span className="material-symbols-outlined text-[20px]">open_in_full</span>
          </button>
        </div>
        
        <div className="flex flex-wrap gap-2 mt-2">
          {recipe.servings && (
            <span className="bg-surface/50 dark:bg-inverse-surface/40 text-secondary dark:text-secondary-fixed-dim font-label-sm px-3 py-1 rounded-full border border-white/40 dark:border-white/5 flex items-center gap-1">
              <span className="material-symbols-outlined text-[16px]">group</span>
              {recipe.servings}
            </span>
          )}
          {recipe.prepTime && (
            <span className="bg-surface/50 dark:bg-inverse-surface/40 text-secondary dark:text-secondary-fixed-dim font-label-sm px-3 py-1 rounded-full border border-white/40 dark:border-white/5 flex items-center gap-1">
               <span className="material-symbols-outlined text-[16px]">schedule</span>
               Prep: {recipe.prepTime}
            </span>
          )}
          {recipe.cookTime && (
            <span className="bg-surface/50 dark:bg-inverse-surface/40 text-secondary dark:text-secondary-fixed-dim font-label-sm px-3 py-1 rounded-full border border-white/40 dark:border-white/5 flex items-center gap-1">
               <span className="material-symbols-outlined text-[16px]">local_fire_department</span>
               Cocción: {recipe.cookTime}
            </span>
          )}
        </div>

        <div className="mt-auto pt-4 flex items-center gap-3">
          <div className="flex-grow bg-surface-variant dark:bg-inverse-surface/60 h-2 rounded-full overflow-hidden">
            <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${progress}%` }}></div>
          </div>
          <span className="font-label-sm text-label-sm text-on-surface-variant dark:text-surface-variant/80">{progress}%</span>
        </div>
      </div>
    </article>
  );
}

export default RecipeCard;

