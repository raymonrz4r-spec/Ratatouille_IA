-- ============================================================================
-- RATATOUILLE AI - SUPABASE POSTGRESQL & STORAGE SCHEMA (CLEAN INIT)
-- ============================================================================
-- Instrucciones:
-- 1. Abre tu proyecto en https://supabase.com/dashboard
-- 2. Ve a "SQL Editor" en el menú lateral izquierdo.
-- 3. Haz clic en "New query", pega todo este script y presiona "Run".
-- ============================================================================

BEGIN;

-- 1. Tabla de Usuarios (Google OAuth & Perfiles del Sistema)
CREATE TABLE IF NOT EXISTS public.users (
    id VARCHAR(80) PRIMARY KEY,
    google_sub VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255) NULL,
    picture_url TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users (email);

-- Usuarios base del sistema (para recetas públicas y compatibilidad)
INSERT INTO public.users (id, google_sub, email, name)
VALUES
    ('legacy-user', 'legacy-default-user', 'legacy@ratatouille.local', 'Legacy User'),
    ('public-user', 'public-recipes', 'public@ratatouille.local', 'Public Recipes')
ON CONFLICT (id) DO NOTHING;

-- 2. Tabla Principal de Recetas
CREATE TABLE IF NOT EXISTS public.recipes (
    id VARCHAR(80) PRIMARY KEY,
    user_id VARCHAR(80) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    visibility VARCHAR(20) NOT NULL DEFAULT 'private',
    title VARCHAR(255) NOT NULL,
    source_url TEXT NOT NULL,
    source_url_hash CHAR(64) NOT NULL,
    platform VARCHAR(50) NOT NULL,
    servings VARCHAR(100) NULL,
    prep_time VARCHAR(100) NULL,
    cook_time VARCHAR(100) NULL,
    transcript_summary TEXT NULL,
    image_url TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uniq_recipes_user_source UNIQUE (user_id, source_url_hash)
);

CREATE INDEX IF NOT EXISTS idx_recipes_user_updated ON public.recipes (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_recipes_visibility_updated ON public.recipes (visibility, updated_at DESC);

-- 3. Tabla de Ingredientes de cada Receta
CREATE TABLE IF NOT EXISTS public.recipe_ingredients (
    recipe_id VARCHAR(80) NOT NULL REFERENCES public.recipes(id) ON DELETE CASCADE,
    ingredient_id VARCHAR(80) NOT NULL,
    position INT NOT NULL,
    text TEXT NOT NULL,
    checked BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (recipe_id, ingredient_id)
);

-- 4. Tabla de Pasos de Preparación
CREATE TABLE IF NOT EXISTS public.recipe_steps (
    id BIGSERIAL PRIMARY KEY,
    recipe_id VARCHAR(80) NOT NULL REFERENCES public.recipes(id) ON DELETE CASCADE,
    position INT NOT NULL,
    text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipe_steps_recipe ON public.recipe_steps (recipe_id, position ASC);

-- 5. Tabla de Notas Adicionales
CREATE TABLE IF NOT EXISTS public.recipe_notes (
    id BIGSERIAL PRIMARY KEY,
    recipe_id VARCHAR(80) NOT NULL REFERENCES public.recipes(id) ON DELETE CASCADE,
    position INT NOT NULL,
    text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipe_notes_recipe ON public.recipe_notes (recipe_id, position ASC);

-- 6. Tabla de Suscripciones / Planes de Usuario
CREATE TABLE IF NOT EXISTS public.subscriptions (
    user_id VARCHAR(80) PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    plan VARCHAR(50) NOT NULL DEFAULT 'Gratuito',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.subscriptions (user_id, plan)
VALUES ('legacy-user', 'Gratuito')
ON CONFLICT (user_id) DO NOTHING;

-- 7. Tabla de Respaldo para Imágenes (solo en caso de no usar Supabase Storage)
CREATE TABLE IF NOT EXISTS public.recipe_images (
    recipe_id VARCHAR(80) PRIMARY KEY REFERENCES public.recipes(id) ON DELETE CASCADE,
    mime_type VARCHAR(100) NOT NULL DEFAULT 'image/jpeg',
    image_data BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- CONFIGURACIÓN DE SUPABASE STORAGE (BUCKET S3 PÚBLICO PARA MINIATURAS)
-- ============================================================================
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'recipe-images',
    'recipe-images',
     true,
    5242880, -- 5MB límite por imagen
    ARRAY['image/jpeg', 'image/png', 'image/webp']
)
ON CONFLICT (id) DO UPDATE
SET public = true;

-- Política para permitir lectura pública de todas las miniaturas del bucket
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage'
          AND tablename = 'objects'
          AND policyname = 'Public Access Recipe Images'
    ) THEN
        CREATE POLICY "Public Access Recipe Images"
        ON storage.objects FOR SELECT
        USING (bucket_id = 'recipe-images');
    END IF;
END
$$;

COMMIT;
