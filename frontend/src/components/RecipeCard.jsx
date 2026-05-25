import { useMemo, useState } from "react";

function RecipeCard({ recipe, onToggleIngredient, onDelete }) {
  const [isOpen, setIsOpen] = useState(false);
  const checkedCount = useMemo(
    () => recipe.ingredients.filter((ingredient) => ingredient.checked).length,
    [recipe.ingredients],
  );

  const progress = recipe.ingredients.length ? Math.round((checkedCount / recipe.ingredients.length) * 100) : 0;

  return (
    <article className="glass-panel rounded-xl overflow-hidden flex flex-col liquid-easing hover:-translate-y-1 group">
      <div className="h-48 w-full bg-secondary-container relative overflow-hidden flex items-center justify-center cursor-pointer" onClick={() => setIsOpen(!isOpen)}>
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
      <div className="p-6 flex flex-col gap-4 flex-grow cursor-pointer" onClick={() => setIsOpen(!isOpen)}>
        <div className="flex justify-between items-start">
          <div>
            <h3 className="font-headline-md text-headline-md text-on-surface leading-tight line-clamp-2">{recipe.title}</h3>
            {recipe.transcriptSummary && (
               <p className="mt-2 line-clamp-2 font-body-md text-sm text-on-surface-variant">{recipe.transcriptSummary}</p>
            )}
          </div>
          <button 
             className="text-outline hover:text-primary transition-colors"
             onClick={(e) => { e.stopPropagation(); setIsOpen(!isOpen); }}
          >
            <span className="material-symbols-outlined">{isOpen ? "expand_less" : "expand_more"}</span>
          </button>
        </div>
        
        <div className="flex flex-wrap gap-2 mt-2">
          {recipe.servings && (
            <span className="bg-surface/50 text-secondary font-label-sm px-3 py-1 rounded-full border border-white/40 flex items-center gap-1">
              <span className="material-symbols-outlined text-[16px]">group</span>
              {recipe.servings}
            </span>
          )}
          {recipe.prepTime && (
            <span className="bg-surface/50 text-secondary font-label-sm px-3 py-1 rounded-full border border-white/40 flex items-center gap-1">
               <span className="material-symbols-outlined text-[16px]">schedule</span>
               Prep: {recipe.prepTime}
            </span>
          )}
          {recipe.cookTime && (
            <span className="bg-surface/50 text-secondary font-label-sm px-3 py-1 rounded-full border border-white/40 flex items-center gap-1">
               <span className="material-symbols-outlined text-[16px]">local_fire_department</span>
               Cocción: {recipe.cookTime}
            </span>
          )}
        </div>

        <div className="mt-auto pt-4 flex items-center gap-3">
          <div className="flex-grow bg-surface-variant h-2 rounded-full overflow-hidden">
            <div className="bg-secondary h-full rounded-full transition-all" style={{ width: `${progress}%` }}></div>
          </div>
          <span className="font-label-sm text-label-sm text-on-surface-variant">{progress}%</span>
        </div>
      </div>

      {isOpen && (
        <div className="border-t border-outline-variant/30 px-6 pb-6 pt-4 bg-surface/30">
          <div className="space-y-6">
            <section>
              <h4 className="mb-3 font-label-md text-secondary uppercase tracking-wider">Ingredientes</h4>
              <ul className="space-y-2">
                {recipe.ingredients.map((ingredient) => (
                  <li key={ingredient.id}>
                    <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-outline-variant/50 px-4 py-3 transition hover:border-primary hover:bg-primary-container/10">
                      <input
                        className="mt-1 h-4 w-4 rounded border-outline accent-primary"
                        type="checkbox"
                        checked={ingredient.checked}
                        onChange={() => onToggleIngredient(recipe.id, ingredient.id)}
                      />
                      <span className={ingredient.checked ? "font-body-md text-on-surface-variant/60 line-through" : "font-body-md text-on-surface"}>
                        {ingredient.text}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h4 className="mb-3 font-label-md text-secondary uppercase tracking-wider">Pasos</h4>
              <ol className="space-y-3">
                {recipe.steps.map((step, index) => (
                  <li className="flex gap-4 rounded-xl bg-surface-container px-4 py-3 font-body-md text-on-surface" key={`${recipe.id}-step-${index}`}>
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary text-sm font-bold text-on-primary">
                      {index + 1}
                    </span>
                    <span className="pt-0.5">{step}</span>
                  </li>
                ))}
              </ol>
            </section>

            {recipe.notes?.length ? (
              <section>
                <h4 className="mb-3 font-label-md text-secondary uppercase tracking-wider">Notas</h4>
                <ul className="space-y-2 font-body-md text-on-surface-variant">
                  {recipe.notes.map((note, index) => (
                    <li key={`${recipe.id}-note-${index}`} className="flex gap-2">
                      <span className="material-symbols-outlined text-[20px] text-tertiary">info</span>
                      {note}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>

          <div className="mt-6 flex items-center justify-between gap-3 border-t border-outline-variant/30 pt-4">
            <a
              className="inline-flex h-10 items-center gap-2 rounded-full border border-outline px-4 font-label-md text-on-surface transition hover:border-primary hover:text-primary"
              href={recipe.sourceUrl}
              target="_blank"
              rel="noreferrer"
            >
              <span className="material-symbols-outlined text-[18px]">open_in_new</span>
              Ver Video
            </a>
            <button
              className="inline-flex h-10 items-center gap-2 rounded-full border border-error/50 px-4 font-label-md text-error transition hover:bg-error hover:text-on-error"
              type="button"
              onClick={() => onDelete(recipe.id)}
              title="Eliminar receta"
            >
              <span className="material-symbols-outlined text-[18px]">delete</span>
              Eliminar
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

export default RecipeCard;
