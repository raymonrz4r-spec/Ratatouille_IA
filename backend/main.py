"""
================================================================================
RATATOUILLE AI - MOTOR BACKEND (backend/main.py)
================================================================================

GUIA DE LECTURA ULTRA SIMPLE ("COMO SI FUERA PARA UN MONO"):
Imagina que este programa es un restaurante automatizado que convierte videos
de TikTok, Instagram o YouTube en recetas escritas paso a paso:

1. LA VENTANILLA (Rutas de la API - Bloque 9):
   El usuario pega un link de TikTok/Instagram/YouTube en la pagina web.

2. EL DESCARGADOR DE SONIDO (yt-dlp + FFmpeg - Bloque 7):
   En vez de bajar el video pesado (que gastaria toda la memoria de Render),
   baja SOLAMENTE el audio en formato MP3 super liviano y el texto de la
   descripcion del post.

3. EL OIDO INTELIGENTE (Transcripcion de Audio - Bloque 8):
   - PRIMERO usa **Groq Whisper** (`whisper-large-v3-turbo` / `whisper-large-v3`),
     porque es rapidisimo, gratuito y tiene limites altos.
   - DE RESPALDO usa **Google Gemini** (`gemini-3.1-flash-lite` / `gemini-3.8-flash`)
     si Groq falla o se queda sin cuota.

4. EL CHEF ESCRITOR (Estructuracion de Receta - Bloque 8):
   Lee lo que dijo el cocinero + la descripcion del video y arma un JSON limpio
   con ingredientes, cantidades y pasos:
   - PRIMERO usa **Groq LLaMA 3.3 70B** (`llama-3.3-70b-versatile`).
   - DE RESPALDO usa **Google Gemini 3.1 Flash Lite** (`gemini-3.1-flash-lite`),
     que es el modelo mas economico y ligero de Google.

5. EL FOTOGRAFO (Imagenes - Bloque 6):
   Genera una foto bonita del plato con Pollinations o rescata la miniatura
   original del video al instante, y la sube a Supabase Storage.

6. EL ARCHIVERO (Base de Datos Supabase PostgreSQL - Bloques 4 y 5):
   Guarda usuarios, recetas, ingredientes tachados y planes de suscripcion.
================================================================================
"""

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import tempfile
import time
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import imageio_ffmpeg
import psycopg2
from psycopg2 import Error as PostgresError
from psycopg2.extras import RealDictCursor
import requests
import yt_dlp
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google import genai
from google.auth.transport import requests as google_requests
from google.genai import types
from google.oauth2 import id_token as google_id_token
from groq import Groq
from pydantic import BaseModel, Field, HttpUrl


# ==============================================================================
# BLOQUE 1: CONFIGURACIÓN E INICIALIZACIÓN DE LA APLICACIÓN
# Aquí leemos las llaves secretas (.env) y abrimos las puertas del servidor.
# ==============================================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")
load_dotenv(BASE_DIR.parent / ".env", encoding="utf-8-sig")

APP_NAME = "Video2Recipe"
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Limite maximo de audio: 25 MB
TEMP_ROOT = Path(os.getenv("TEMP_ROOT", str(BASE_DIR / ".tmp")))
DATABASE_READY = False
DATABASE_ERROR = "PostgreSQL (Supabase) no se ha inicializado todavia."

# Listas ordenadas de modelos de IA (Principal: Groq -> Respaldo: Gemini)
GROQ_WHISPER_MODELS = [
    "whisper-large-v3-turbo",
    "whisper-large-v3",
]

GROQ_CHAT_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.3-70b-specdec",
    "llama-3.1-8b-instant",
]

GEMINI_BACKUP_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.8-flash",
    "gemini-3.1-pro-preview",
]

app = FastAPI(title=APP_NAME, version="2.0.0")

_extra_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
if os.getenv("FRONTEND_URL"):
    _extra_origins.append(os.getenv("FRONTEND_URL", "").strip().rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://localhost:7860",
        "https://tttfsqq3-5173.use2.devtunnels.ms",
        *_extra_origins,
    ],
    allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.hf\.space",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def api_base_url() -> str:
    """Devuelve la direccion web publica de este servidor backend."""
    return os.getenv("VITE_API_URL", "http://localhost:8000").rstrip("/")


def google_client_id() -> str:
    """Devuelve el identificador publico de Google OAuth para verificar inicios de sesion."""
    return os.getenv("GOOGLE_CLIENT_ID") or os.getenv("VITE_GOOGLE_CLIENT_ID") or ""


def groq_api_key() -> str:
    """Obtiene la llave secreta de Groq (nuestro motor principal de IA)."""
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    return "" if key == "tu_api_key_aqui" else key


def gemini_api_key() -> str:
    """Obtiene la llave secreta de Google Gemini (nuestro motor de respaldo de IA)."""
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    return "" if key == "tu_gemini_api_key_aqui" else key


def app_secret() -> str:
    """
    Obtiene la llave secreta con la que firmamos los pases de entrada (tokens)
    de los usuarios para que nadie pueda falsificarlos.
    """
    configured_secret = os.getenv("APP_SECRET") or os.getenv("SESSION_SECRET")
    if configured_secret:
        return configured_secret

    fallback_seed = groq_api_key() or gemini_api_key() or "ratatouille-default-seed"
    return hashlib.sha256(f"ratatouille-session:{fallback_seed}".encode("utf-8")).hexdigest()


def supabase_url() -> str:
    """Devuelve la URL base del proyecto de Supabase."""
    return (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or "").strip().rstrip("/")


def supabase_key() -> str:
    """Devuelve la llave de acceso a Supabase Storage."""
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("VITE_SUPABASE_ANON_KEY")
        or ""
    ).strip()


def supabase_storage_bucket() -> str:
    """Devuelve el nombre de la carpeta (bucket) donde guardamos las fotos de platos."""
    return (os.getenv("SUPABASE_STORAGE_BUCKET") or "recipe-images").strip()


# ==============================================================================
# BLOQUE 2: MODELOS DE DATOS (Moldes de información)
# Estas clases definen qué forma tienen los datos que entran y salen de la API.
# ==============================================================================


class ExtractRequest(BaseModel):
    """Caja que recibe el link del video enviado por el usuario."""
    url: HttpUrl


class GoogleLoginRequest(BaseModel):
    """Caja que recibe la credencial de Google cuando el usuario inicia sesion."""
    idToken: str


class User(BaseModel):
    """Datos basicos de una persona registrada en Ratatouille."""
    id: str
    email: str
    name: str | None = None
    pictureUrl: str | None = None


class AuthResponse(BaseModel):
    """Respuesta al iniciar sesion: incluye el pase de acceso (token) y los datos del usuario."""
    accessToken: str
    user: User


class IngredientProgressUpdate(BaseModel):
    """Recibe si un ingrediente fue marcado (checked=True) o desmarcado (checked=False)."""
    checked: bool


class Subscription(BaseModel):
    """Plan actual del usuario: 'Gratuito', 'Gourmet' o 'Chef'."""
    plan: str = "Gratuito"


class Ingredient(BaseModel):
    """Un ingrediente individual dentro de una receta."""
    id: str
    text: str
    checked: bool = False


class Recipe(BaseModel):
    """Estructura completa de una receta de cocina."""
    id: str
    title: str
    sourceUrl: str
    platform: str
    servings: str | None = None
    prepTime: str | None = None
    cookTime: str | None = None
    ingredients: list[Ingredient] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    transcriptSummary: str | None = None
    imageUrl: str | None = None


class SaveRecipeResponse(BaseModel):
    """Respuesta cuando un usuario guarda una receta del catalogo publico (Explore)."""
    recipe: Recipe
    subscription: Subscription


# ==============================================================================
# BLOQUE 3: SEGURIDAD, TOKENS Y LOGIN CON GOOGLE (El guardia de la puerta)
# Funciones para crear pulseras de acceso (tokens) y verificar que no sean falsas.
# ==============================================================================


def b64url_encode(payload: bytes) -> str:
    """Convierte bytes en texto seguro para URLs (sin signos raros)."""
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def b64url_decode(payload: str) -> bytes:
    """Convierte texto seguro de URL de vuelta a sus bytes originales."""
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(f"{payload}{padding}")


def create_access_token(user_id: str) -> str:
    """
    Crea un pase VIP (token firmado) para el usuario que dura 14 dias.
    Asi el navegador recuerda quien es sin pedirle login a cada segundo.
    """
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + 60 * 60 * 24 * 14,
    }
    encoded_payload = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        app_secret().encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{b64url_encode(signature)}"


def verify_access_token(token: str) -> str:
    """
    Revisa que el pase VIP (token) sea autentico y no haya vencido.
    Devuelve el ID del usuario si todo esta bien, o lanza error 401 si es invalido.
    """
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected_signature = hmac.new(
            app_secret().encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        provided_signature = b64url_decode(encoded_signature)
        if not hmac.compare_digest(expected_signature, provided_signature):
            raise ValueError("Firma invalida")

        payload = json.loads(b64url_decode(encoded_payload))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("Token expirado")

        user_id = str(payload.get("sub") or "")
        if not user_id:
            raise ValueError("Sin usuario")
        return user_id
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Sesion invalida o expirada.") from exc


# ==============================================================================
# BLOQUE 4: CONEXIÓN Y CREACIÓN DE BASE DE DATOS (Supabase PostgreSQL)
# Funciones para hablar con PostgreSQL sin dejar conexiones abiertas por error.
# ==============================================================================


def get_database_url() -> str:
    """
    Busca la direccion de conexion a PostgreSQL (Supabase) en las variables de entorno.
    Si no existe, avisa claramente que falta configurar DATABASE_URL.
    """
    dsn = (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("POSTGRES_URL")
        or ""
    ).strip()
    if dsn:
        if dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://") :]
        return dsn

    host = os.getenv("PGHOST") or os.getenv("DB_HOST") or ""
    if host:
        port = os.getenv("PGPORT") or os.getenv("DB_PORT") or "5432"
        user = os.getenv("PGUSER") or os.getenv("DB_USER") or "postgres"
        password = urllib.parse.quote_plus(os.getenv("PGPASSWORD") or os.getenv("DB_PASSWORD") or "")
        database = os.getenv("PGDATABASE") or os.getenv("DB_NAME") or "postgres"
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    raise HTTPException(
        status_code=503,
        detail="Falta DATABASE_URL en .env o en las variables de entorno del servidor.",
    )


def open_db_connection() -> Any:
    """Abre una linea telefonica directa con la base de datos PostgreSQL."""
    dsn = get_database_url()
    try:
        return psycopg2.connect(dsn, connect_timeout=10)
    except (PostgresError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No se pudo conectar a PostgreSQL (Supabase): {exc}",
        ) from exc


def dict_cursor(connection: Any) -> Any:
    """Crea un lector de base de datos que devuelve filas como diccionarios faciles de leer."""
    return connection.cursor(cursor_factory=RealDictCursor)


@contextmanager
def db_connection() -> Iterator[Any]:
    """
    Prestamo seguro de conexion a la base de datos:
    - Si todo sale bien, guarda los cambios (commit).
    - Si algo falla, deshace el desastre (rollback).
    - Siempre cierra la puerta al terminar (close).
    """
    connection = open_db_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_schema_tables(cursor: Any) -> None:
    """
    Ejecuta las instrucciones SQL para crear las tablas de usuarios, recetas,
    ingredientes, pasos, notas, imagenes y suscripciones si aun no existen.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(80) PRIMARY KEY,
            google_sub VARCHAR(255) NOT NULL UNIQUE,
            email VARCHAR(255) NOT NULL,
            name VARCHAR(255) NULL,
            picture_url TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
        INSERT INTO users (id, google_sub, email, name)
        VALUES
            ('legacy-user', 'legacy-default-user', 'legacy@ratatouille.local', 'Legacy User'),
            ('public-user', 'public-recipes', 'public@ratatouille.local', 'Public Recipes')
        ON CONFLICT (id) DO NOTHING;

        CREATE TABLE IF NOT EXISTS recipes (
            id VARCHAR(80) PRIMARY KEY,
            user_id VARCHAR(80) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
        CREATE INDEX IF NOT EXISTS idx_recipes_user_updated ON recipes (user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_recipes_visibility_updated ON recipes (visibility, updated_at DESC);

        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            recipe_id VARCHAR(80) NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            ingredient_id VARCHAR(80) NOT NULL,
            position INT NOT NULL,
            text TEXT NOT NULL,
            checked BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (recipe_id, ingredient_id)
        );

        CREATE TABLE IF NOT EXISTS recipe_steps (
            id BIGSERIAL PRIMARY KEY,
            recipe_id VARCHAR(80) NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            position INT NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recipe_steps_recipe ON recipe_steps (recipe_id, position ASC);

        CREATE TABLE IF NOT EXISTS recipe_notes (
            id BIGSERIAL PRIMARY KEY,
            recipe_id VARCHAR(80) NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            position INT NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recipe_notes_recipe ON recipe_notes (recipe_id, position ASC);

        CREATE TABLE IF NOT EXISTS recipe_images (
            recipe_id VARCHAR(80) PRIMARY KEY REFERENCES recipes(id) ON DELETE CASCADE,
            mime_type VARCHAR(100) NOT NULL DEFAULT 'image/jpeg',
            image_data BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id VARCHAR(80) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            plan VARCHAR(50) NOT NULL DEFAULT 'Gratuito',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        INSERT INTO subscriptions (user_id, plan)
        VALUES ('legacy-user', 'Gratuito')
        ON CONFLICT (user_id) DO NOTHING;
        """
    )


def init_database() -> None:
    """
    Prepara la base de datos al encender el servidor.
    Si el usuario de base de datos no tiene permisos para crear tablas pero las tablas
    ya existen en Supabase, verifica que se puedan leer sin bloquear el arranque.
    """
    try:
        with db_connection() as connection:
            cursor = connection.cursor()
            create_schema_tables(cursor)
    except Exception as exc:
        print(f"Aviso al inicializar esquema DDL (verificando tablas existentes): {exc}")
        with db_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1 FROM recipes LIMIT 1")


@app.on_event("startup")
def startup() -> None:
    """Se ejecuta automaticamente cuando el servidor prende por primera vez."""
    global DATABASE_READY, DATABASE_ERROR
    try:
        init_database()
        DATABASE_READY = True
        DATABASE_ERROR = ""
    except HTTPException as exc:
        DATABASE_READY = False
        DATABASE_ERROR = str(exc.detail)
        print(f"PostgreSQL (Supabase) no esta listo: {DATABASE_ERROR}")


def ensure_database_ready() -> None:
    """Revisa que la base de datos este lista antes de atender cualquier peticion."""
    global DATABASE_READY, DATABASE_ERROR
    if DATABASE_READY:
        return

    try:
        init_database()
        DATABASE_READY = True
        DATABASE_ERROR = ""
    except HTTPException as exc:
        DATABASE_ERROR = str(exc.detail)
        raise HTTPException(status_code=503, detail=DATABASE_ERROR) from exc


def source_url_hash(source_url: str) -> str:
    """Crea una huella digital unica (SHA-256) para el link de un video."""
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def recipe_from_row(row: dict[str, Any]) -> Recipe:
    """Convierte una fila cruda de la tabla 'recipes' en un objeto Recipe de Python."""
    return Recipe(
        id=row["id"],
        title=row["title"],
        sourceUrl=row["source_url"],
        platform=row["platform"],
        servings=row.get("servings"),
        prepTime=row.get("prep_time"),
        cookTime=row.get("cook_time"),
        ingredients=[],
        steps=[],
        notes=[],
        transcriptSummary=row.get("transcript_summary"),
        imageUrl=row.get("image_url"),
    )


def user_from_row(row: dict[str, Any]) -> User:
    """Convierte una fila cruda de la tabla 'users' en un objeto User de Python."""
    return User(
        id=row["id"],
        email=row["email"],
        name=row.get("name"),
        pictureUrl=row.get("picture_url"),
    )


# ==============================================================================
# BLOQUE 5: GUARDADO Y LECTURA DE USUARIOS, RECETAS Y SUSCRIPCIONES
# Funciones para consultar y guardar la información de cada usuario en Supabase.
# ==============================================================================


def get_user_by_id(user_id: str, connection: Any | None = None) -> User | None:
    """Busca un usuario en la base de datos por su ID."""
    close_connection = connection is None
    if connection is None:
        connection = open_db_connection()

    try:
        cursor = dict_cursor(connection)
        cursor.execute("SELECT id, email, name, picture_url FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return user_from_row(row) if row else None
    finally:
        if close_connection:
            connection.close()


def get_or_create_google_user(profile: dict[str, Any]) -> User:
    """
    Si el usuario que entra con Google es nuevo, le crea su cuenta y su plan Gratuito.
    Si ya existia, actualiza su nombre, foto y fecha de ultimo acceso.
    """
    ensure_database_ready()
    google_sub = str(profile.get("sub") or "").strip()
    email = str(profile.get("email") or "").strip().lower()
    if not google_sub or not email:
        raise HTTPException(status_code=401, detail="Google no devolvio una identidad valida.")

    name = str(profile.get("name") or "").strip() or None
    picture_url = str(profile.get("picture") or "").strip() or None
    user_id = f"user-{hashlib.sha256(f'google:{google_sub}'.encode('utf-8')).hexdigest()[:24]}"

    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO users (id, google_sub, email, name, picture_url, last_login_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                picture_url = EXCLUDED.picture_url,
                last_login_at = NOW()
            """,
            (user_id, google_sub, email, name, picture_url),
        )
        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, plan)
            VALUES (%s, 'Gratuito')
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )
        user = get_user_by_id(user_id, connection)
        if user is None:
            raise HTTPException(status_code=500, detail="No se pudo crear el usuario.")
        return user


def verify_google_login(id_token: str) -> User:
    """Comprueba con los servidores de Google que el boton de inicio de sesion sea legitimo."""
    client_id = google_client_id()
    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Falta GOOGLE_CLIENT_ID/VITE_GOOGLE_CLIENT_ID en .env para iniciar sesion con Google.",
        )

    try:
        profile = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            client_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="No se pudo verificar la sesion de Google.") from exc

    return get_or_create_google_user(profile)


def user_from_access_token(token: str) -> User:
    """Obtiene el usuario dueno de un token de sesion."""
    user_id = verify_access_token(token)
    with db_connection() as connection:
        user = get_user_by_id(user_id, connection)
        if user is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado.")
        return user


def current_user(authorization: str | None = Header(default=None)) -> User:
    """Exige que el usuario haya iniciado sesion para usar una ruta privada."""
    ensure_database_ready()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Debes iniciar sesion.")

    return user_from_access_token(authorization.removeprefix("Bearer ").strip())


def optional_current_user(authorization: str | None = Header(default=None)) -> User | None:
    """Devuelve el usuario si inicio sesion, o None si es un visitante anonimo."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return user_from_access_token(authorization.removeprefix("Bearer ").strip())


def resolve_recipe_image_url(cursor: Any, row: dict[str, Any]) -> str | None:
    """
    Determina cual es el link de la foto de la receta:
    - Si ya tiene una URL publica (ej. Supabase Storage), la usa directo.
    - Si la foto esta guardada como bytes en la tabla 'recipe_images', devuelve el endpoint de imagen.
    """
    stored_url = row.get("image_url")
    if is_external_image_url(stored_url):
        return stored_url

    recipe_id = row["id"]
    cursor.execute("SELECT 1 FROM recipe_images WHERE recipe_id = %s", (recipe_id,))
    if cursor.fetchone() is not None:
        return recipe_image_url(recipe_id, row.get("visibility") == "public")
    return None


def populate_recipe_lists(cursor: Any, recipe: Recipe) -> None:
    """Rellena los ingredientes, pasos y notas de una receta leyendo sus tablas secundarias."""
    cursor.execute(
        """
        SELECT ingredient_id, text, checked
        FROM recipe_ingredients
        WHERE recipe_id = %s
        ORDER BY position ASC
        """,
        (recipe.id,),
    )
    recipe.ingredients = [
        Ingredient(id=item["ingredient_id"], text=item["text"], checked=bool(item["checked"]))
        for item in cursor.fetchall()
    ]

    cursor.execute(
        "SELECT text FROM recipe_steps WHERE recipe_id = %s ORDER BY position ASC",
        (recipe.id,),
    )
    recipe.steps = [item["text"] for item in cursor.fetchall()]

    cursor.execute(
        "SELECT text FROM recipe_notes WHERE recipe_id = %s ORDER BY position ASC",
        (recipe.id,),
    )
    recipe.notes = [item["text"] for item in cursor.fetchall()]


def load_recipe(recipe_id: str, user_id: str, connection: Any | None = None) -> Recipe | None:
    """Carga una receta completa (con sus ingredientes, pasos, notas y foto) desde PostgreSQL."""
    close_connection = connection is None
    if connection is None:
        connection = open_db_connection()

    try:
        cursor = dict_cursor(connection)
        cursor.execute("SELECT * FROM recipes WHERE id = %s AND user_id = %s", (recipe_id, user_id))
        row = cursor.fetchone()
        if not row:
            return None

        recipe = recipe_from_row(row)
        recipe.imageUrl = resolve_recipe_image_url(cursor, row)
        populate_recipe_lists(cursor, recipe)
        return recipe
    finally:
        if close_connection:
            connection.close()


def load_recipes(user_id: str) -> list[Recipe]:
    """Devuelve las ultimas 50 recetas privadas guardadas por un usuario."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = dict_cursor(connection)
        cursor.execute(
            "SELECT id FROM recipes WHERE user_id = %s ORDER BY updated_at DESC LIMIT 50",
            (user_id,),
        )
        return [
            recipe
            for row in cursor.fetchall()
            if (recipe := load_recipe(row["id"], user_id, connection)) is not None
        ]


def load_public_recipes() -> list[Recipe]:
    """Devuelve las ultimas 50 recetas publicas para la seccion Explore."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = dict_cursor(connection)
        cursor.execute(
            """
            SELECT id
            FROM recipes
            WHERE visibility = 'public'
            ORDER BY updated_at DESC
            LIMIT 50
            """
        )
        return [
            recipe
            for row in cursor.fetchall()
            if (recipe := load_recipe(row["id"], "public-user", connection)) is not None
        ]


def find_existing_recipe_by_url(source_url: str, owner_id: str) -> Recipe | None:
    """
    Revisa si este usuario (o el catalogo publico) ya extrajo este mismo video antes.
    Asi evitamos gastar IA dos veces por el mismo link.
    """
    url_hash = source_url_hash(source_url)
    try:
        with db_connection() as connection:
            cursor = dict_cursor(connection)
            cursor.execute(
                "SELECT id FROM recipes WHERE user_id = %s AND source_url_hash = %s",
                (owner_id, url_hash),
            )
            row = cursor.fetchone()
            if row:
                return load_recipe(row["id"], owner_id, connection)
    except Exception:
        pass
    return None


def save_recipe(recipe: Recipe, user_id: str, visibility: str = "private") -> Recipe:
    """Guarda o actualiza una receta completa (datos, ingredientes, pasos y notas) en la base de datos."""
    ensure_database_ready()
    if visibility not in {"public", "private"}:
        raise HTTPException(status_code=422, detail="Visibilidad de receta invalida.")

    with db_connection() as connection:
        cursor = connection.cursor()
        recipe_source_hash = source_url_hash(recipe.sourceUrl)

        # Si el mismo usuario ya tenia otra receta con este link, limpiamos la vieja
        cursor.execute(
            "SELECT id FROM recipes WHERE user_id = %s AND source_url_hash = %s",
            (user_id, recipe_source_hash),
        )
        existing_recipe = cursor.fetchone()
        if existing_recipe and existing_recipe[0] != recipe.id:
            cursor.execute("DELETE FROM recipes WHERE id = %s", (existing_recipe[0],))

        cursor.execute(
            """
            INSERT INTO recipes (
                id, user_id, visibility, title, source_url, source_url_hash, platform, servings,
                prep_time, cook_time, transcript_summary, image_url, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                visibility = EXCLUDED.visibility,
                title = EXCLUDED.title,
                source_url = EXCLUDED.source_url,
                source_url_hash = EXCLUDED.source_url_hash,
                platform = EXCLUDED.platform,
                servings = EXCLUDED.servings,
                prep_time = EXCLUDED.prep_time,
                cook_time = EXCLUDED.cook_time,
                transcript_summary = EXCLUDED.transcript_summary,
                image_url = COALESCE(EXCLUDED.image_url, recipes.image_url),
                updated_at = NOW()
            """,
            (
                recipe.id,
                user_id,
                visibility,
                recipe.title,
                recipe.sourceUrl,
                recipe_source_hash,
                recipe.platform,
                recipe.servings,
                recipe.prepTime,
                recipe.cookTime,
                recipe.transcriptSummary,
                recipe.imageUrl,
            ),
        )

        # Reemplazar listas de ingredientes, pasos y notas
        cursor.execute("DELETE FROM recipe_ingredients WHERE recipe_id = %s", (recipe.id,))
        cursor.execute("DELETE FROM recipe_steps WHERE recipe_id = %s", (recipe.id,))
        cursor.execute("DELETE FROM recipe_notes WHERE recipe_id = %s", (recipe.id,))

        if recipe.ingredients:
            cursor.executemany(
                """
                INSERT INTO recipe_ingredients (recipe_id, ingredient_id, position, text, checked)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (recipe.id, ing.id, idx, ing.text, ing.checked)
                    for idx, ing in enumerate(recipe.ingredients)
                ],
            )
        if recipe.steps:
            cursor.executemany(
                "INSERT INTO recipe_steps (recipe_id, position, text) VALUES (%s, %s, %s)",
                [(recipe.id, idx, step) for idx, step in enumerate(recipe.steps)],
            )
        if recipe.notes:
            cursor.executemany(
                "INSERT INTO recipe_notes (recipe_id, position, text) VALUES (%s, %s, %s)",
                [(recipe.id, idx, note) for idx, note in enumerate(recipe.notes)],
            )
        return recipe


def update_ingredient_progress(user_id: str, recipe_id: str, ingredient_id: str, checked: bool) -> Recipe:
    """Marca o desmarca una casilla de ingrediente cuando el usuario va comprando o cocinando."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE recipe_ingredients
            SET checked = %s
            FROM recipes
            WHERE recipes.id = recipe_ingredients.recipe_id
              AND recipe_ingredients.recipe_id = %s
              AND recipe_ingredients.ingredient_id = %s
              AND recipes.user_id = %s
            """,
            (checked, recipe_id, ingredient_id, user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Ingrediente no encontrado.")
        recipe = load_recipe(recipe_id, user_id, connection)
        if recipe is None:
            raise HTTPException(status_code=404, detail="Receta no encontrada.")
        return recipe


def get_subscription(user_id: str) -> Subscription:
    """Devuelve el plan de suscripcion actual del usuario ('Gratuito', 'Gourmet' o 'Chef')."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = dict_cursor(connection)
        cursor.execute("SELECT plan FROM subscriptions WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        return Subscription(plan=row["plan"] if row else "Gratuito")


def is_paid_plan(user_id: str) -> bool:
    """Indica si el usuario tiene un plan de pago activo ('Gourmet' o 'Chef')."""
    return get_subscription(user_id).plan in {"Gourmet", "Chef"}


def save_subscription(user_id: str, plan: str) -> Subscription:
    """Cambia el plan de suscripcion de un usuario."""
    plan = plan.strip() or "Gratuito"
    if plan not in {"Gratuito", "Gourmet", "Chef"}:
        raise HTTPException(status_code=422, detail="Plan de suscripcion invalido.")

    ensure_database_ready()
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, plan, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                plan = EXCLUDED.plan,
                updated_at = NOW()
            """,
            (user_id, plan),
        )
    return Subscription(plan=plan)


def save_public_recipe_to_user(public_recipe_id: str, user_id: str) -> Recipe:
    """Copia una receta publica de la seccion Explore a la coleccion privada del usuario."""
    if not is_paid_plan(user_id):
        raise HTTPException(
            status_code=403,
            detail="Necesitas un plan Gourmet o Chef para guardar recetas de Explore.",
        )

    with db_connection() as connection:
        public_recipe = load_recipe(public_recipe_id, "public-user", connection)
        if public_recipe is None:
            raise HTTPException(status_code=404, detail="Receta publica no encontrada.")

        private_hash = hashlib.sha256(
            f"{user_id}:{public_recipe.sourceUrl}:{public_recipe.title}".encode("utf-8")
        ).hexdigest()[:16]
        private_id = f"recipe-{private_hash}"

        private_recipe = public_recipe.model_copy(deep=True)
        private_recipe.id = private_id
        if is_external_image_url(public_recipe.imageUrl):
            private_recipe.imageUrl = public_recipe.imageUrl
        else:
            private_recipe.imageUrl = recipe_image_url(private_id)
        private_recipe.ingredients = [
            Ingredient(id=ing.id, text=ing.text, checked=False)
            for ing in private_recipe.ingredients
        ]

    saved_recipe = save_recipe(private_recipe, user_id, "private")

    # Si la imagen no estaba en un link externo, copiamos los bytes en recipe_images
    if not is_external_image_url(private_recipe.imageUrl):
        with db_connection() as connection:
            cursor = dict_cursor(connection)
            cursor.execute(
                "SELECT mime_type, image_data FROM recipe_images WHERE recipe_id = %s",
                (public_recipe_id,),
            )
            image_row = cursor.fetchone()
            if image_row:
                cursor_write = connection.cursor()
                cursor_write.execute(
                    """
                    INSERT INTO recipe_images (recipe_id, mime_type, image_data, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (recipe_id) DO UPDATE SET
                        mime_type = EXCLUDED.mime_type,
                        image_data = EXCLUDED.image_data,
                        updated_at = NOW()
                    """,
                    (private_id, image_row["mime_type"], psycopg2.Binary(bytes(image_row["image_data"]))),
                )

    return load_recipe(saved_recipe.id, user_id) or saved_recipe


# ==============================================================================
# BLOQUE 6: GESTIÓN Y GENERACIÓN DE IMÁGENES (Las fotos de los platos)
# Sube fotos a Supabase Storage o rescata la miniatura original del video.
# ==============================================================================


def recipe_image_url(recipe_id: str, is_public: bool = False) -> str:
    """Construye el link interno para ver la foto de una receta."""
    path = "explore/recipes" if is_public else "recipes"
    return f"{api_base_url()}/api/{path}/{recipe_id}/image"


def is_external_image_url(url: str | None) -> bool:
    """Revisa si la foto ya vive en un servidor externo (como Supabase Storage)."""
    if not url:
        return False
    return (
        "/storage/v1/object/public/" in url
        or (url.startswith("http") and "/api/recipes/" not in url and "/api/explore/recipes/" not in url)
    )


def upload_to_supabase_storage(recipe_id: str, image_data: bytes, content_type: str) -> str | None:
    """
    Sube los bytes de una foto al bucket publico de Supabase Storage.
    Si el bucket no existe, intenta crearlo automaticamente.
    Devuelve la URL publica de la foto o None si no se pudo subir.
    """
    base_url = supabase_url()
    key = supabase_key()
    if not base_url or not key:
        return None

    bucket = supabase_storage_bucket()
    clean_type = content_type.split(";", 1)[0].strip().lower()
    suffix = ".png" if clean_type == "image/png" else ".webp" if clean_type == "image/webp" else ".jpg"
    filename = f"{recipe_id}{suffix}"
    object_url = f"{base_url}/storage/v1/object/{bucket}/{filename}"
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": clean_type or "image/jpeg",
        "x-upsert": "true",
    }

    try:
        resp = requests.post(object_url, data=image_data, headers=headers, timeout=20)
        if resp.status_code in (400, 404) and "Bucket not found" in resp.text:
            requests.post(
                f"{base_url}/storage/v1/bucket",
                json={"id": bucket, "name": bucket, "public": True},
                headers={
                    "Authorization": f"Bearer {key}",
                    "apikey": key,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            resp = requests.post(object_url, data=image_data, headers=headers, timeout=20)

        if resp.ok:
            return f"{base_url}/storage/v1/object/public/{bucket}/{filename}"
        print(f"Aviso Supabase Storage ({resp.status_code}): {resp.text[:250]}")
    except Exception as exc:
        print(f"No se pudo subir imagen a Supabase Storage: {exc}")

    return None


def save_recipe_image_bytes(
    recipe_id: str,
    image_data: bytes,
    content_type: str,
    connection: Any | None = None,
) -> str:
    """
    Guarda la foto de una receta:
    1. Primero intenta subirla a Supabase Storage (mas rapido y liviano).
    2. Si Storage no esta activo, la guarda en la tabla 'recipe_images' de PostgreSQL.
    """
    mime_type = content_type.split(";", 1)[0].strip().lower() or "image/jpeg"
    storage_public_url = upload_to_supabase_storage(recipe_id, image_data, mime_type)

    close_connection = connection is None
    if connection is None:
        connection = open_db_connection()

    try:
        cursor = connection.cursor()
        if storage_public_url:
            cursor.execute(
                "UPDATE recipes SET image_url = %s, updated_at = NOW() WHERE id = %s",
                (storage_public_url, recipe_id),
            )
            if close_connection:
                connection.commit()
            return storage_public_url

        cursor.execute(
            """
            INSERT INTO recipe_images (recipe_id, mime_type, image_data, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (recipe_id) DO UPDATE SET
                mime_type = EXCLUDED.mime_type,
                image_data = EXCLUDED.image_data,
                updated_at = NOW()
            """,
            (recipe_id, mime_type, psycopg2.Binary(image_data)),
        )
        cursor.execute("SELECT visibility FROM recipes WHERE id = %s", (recipe_id,))
        recipe_row = cursor.fetchone()
        visibility = "private"
        if recipe_row:
            visibility = recipe_row[0] if isinstance(recipe_row, tuple) else recipe_row["visibility"]
        fallback_url = recipe_image_url(recipe_id, visibility == "public")
        cursor.execute(
            "UPDATE recipes SET image_url = %s, updated_at = NOW() WHERE id = %s",
            (fallback_url, recipe_id),
        )
        if close_connection:
            connection.commit()
        return fallback_url
    finally:
        if close_connection:
            connection.close()


def load_recipe_image(user_id: str, recipe_id: str) -> tuple[bytes | None, str, str | None]:
    """Busca la foto de una receta privada. Devuelve (bytes, tipo_mime, url_redireccion)."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = dict_cursor(connection)
        cursor.execute(
            "SELECT image_url FROM recipes WHERE id = %s AND user_id = %s",
            (recipe_id, user_id),
        )
        recipe_row = cursor.fetchone()
        if recipe_row and is_external_image_url(recipe_row.get("image_url")):
            return None, "", recipe_row["image_url"]

        cursor.execute(
            """
            SELECT recipe_images.mime_type, recipe_images.image_data
            FROM recipe_images
            INNER JOIN recipes ON recipes.id = recipe_images.recipe_id
            WHERE recipe_images.recipe_id = %s AND recipes.user_id = %s
            """,
            (recipe_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Imagen no encontrada.")

        return bytes(row["image_data"]), row["mime_type"], None


def load_public_recipe_image(recipe_id: str) -> tuple[bytes | None, str, str | None]:
    """Busca la foto de una receta publica (Explore). Devuelve (bytes, tipo_mime, url_redireccion)."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = dict_cursor(connection)
        cursor.execute(
            """
            SELECT image_url
            FROM recipes
            WHERE id = %s AND user_id = 'public-user' AND visibility = 'public'
            """,
            (recipe_id,),
        )
        recipe_row = cursor.fetchone()
        if recipe_row and is_external_image_url(recipe_row.get("image_url")):
            return None, "", recipe_row["image_url"]

        cursor.execute(
            """
            SELECT recipe_images.mime_type, recipe_images.image_data
            FROM recipe_images
            INNER JOIN recipes ON recipes.id = recipe_images.recipe_id
            WHERE recipe_images.recipe_id = %s
              AND recipes.user_id = 'public-user'
              AND recipes.visibility = 'public'
            """,
            (recipe_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Imagen no encontrada.")

        return bytes(row["image_data"]), row["mime_type"], None


def fetch_image_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> tuple[bytes, str]:
    """Descarga una imagen desde una URL y verifica que realmente sea una foto valida."""
    response = requests.get(
        url,
        headers={
            "User-Agent": "RatatouilleAI/2.0",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
            **(headers or {}),
        },
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code}")

    content_type = response.headers.get("Content-Type", "").lower()
    image_data = response.content
    if not image_data or not content_type.startswith("image/"):
        raise ValueError(f"Respuesta no es imagen valida: {content_type}")
    return image_data, content_type


def generate_pollinations_image(prompt: str) -> tuple[bytes, str]:
    """Pide a Pollinations AI una foto artistica del plato con un limite de espera corto (15s)."""
    api_key = os.getenv("POLLINATIONS_API_KEY", "").strip()
    encoded_prompt = urllib.parse.quote(prompt)
    auth_headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    urls = [
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=800&height=800&nologo=true",
        f"https://gen.pollinations.ai/image/{encoded_prompt}?width=800&height=800&model=flux",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            return fetch_image_bytes(url, headers=auth_headers, timeout=15)
        except Exception as exc:
            errors.append(str(exc))

    raise RuntimeError("; ".join(errors))


def generate_recipe_image_bytes(
    title: str,
    recipe_id: str,
    fallback_thumbnail_url: str | None = None,
) -> tuple[bytes, str] | None:
    """
    Obtiene la foto para la receta sin bloquear el servidor de Render:
    1. Si el video original tiene miniatura (thumbnail), o si Pollinations responde rapido, la usa.
    2. Si Pollinations falla, usa de inmediato la miniatura original del video.
    """
    prompt = f"Professional food photography of {title}, high quality, cinematic lighting, appetizing"
    try:
        image_data, content_type = generate_pollinations_image(prompt)
        print(f"Imagen generada con Pollinations: {recipe_id}")
        return image_data, content_type
    except Exception as exc:
        print(f"Aviso Pollinations ({recipe_id}): {exc}")

    if fallback_thumbnail_url:
        try:
            image_data, content_type = fetch_image_bytes(fallback_thumbnail_url, timeout=15)
            print(f"Usando miniatura original del video para {recipe_id}")
            return image_data, content_type
        except Exception as exc:
            print(f"No se pudo descargar miniatura original ({recipe_id}): {exc}")

    return None


# ==============================================================================
# BLOQUE 7: DESCARGA DE AUDIO DESDE REDES SOCIALES (yt-dlp + FFmpeg)
# Extrae únicamente la pista de voz en MP3 ligero y los textos del post.
# ==============================================================================


def detect_platform(url: str) -> str:
    """Detecta de que red social viene el enlace (TikTok, Instagram, YouTube o Video)."""
    host = url.lower()
    if "tiktok.com" in host:
        return "TikTok"
    if "instagram.com" in host:
        return "Instagram"
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    return "Video"


def get_ffmpeg_location() -> str:
    """Busca el programa FFmpeg en el sistema para poder recortar y comprimir el audio."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="ffmpeg no esta disponible en el sistema.",
        ) from exc


def download_audio_with_metadata(url: str, work_dir: Path) -> tuple[Path, dict[str, Any]]:
    """
    Descarga SOLO el audio del video (en MP3 mono a 16kHz super liviano)
    junto con el titulo, la descripcion escrita del post y la miniatura.
    """
    ffmpeg_location = get_ffmpeg_location()
    output_template = str(work_dir / "source.%(ext)s")
    options: dict[str, Any] = {
        "format": "ba[ext=m4a]/ba/bestaudio/best",
        "outtmpl": output_template,
        "ffmpeg_location": ffmpeg_location,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Referer": "https://www.tiktok.com/",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        },
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlist_items": "1",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
    }

    cookies_content = os.getenv("YTDLP_COOKIES", "").strip()
    if cookies_content:
        cookie_file = work_dir / "cookies.txt"
        cookie_file.write_text(cookies_content, encoding="utf-8")
        options["cookiefile"] = str(cookie_file)

    metadata: dict[str, Any] = {}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if isinstance(info, dict):
                metadata = {
                    "title": str(info.get("title") or "").strip(),
                    "description": str(info.get("description") or "").strip(),
                    "thumbnail": str(info.get("thumbnail") or "").strip(),
                    "duration": info.get("duration"),
                }
    except yt_dlp.utils.DownloadError as exc:
        error_text = str(exc)
        if "HTTP Error 429" in error_text or "Too Many Requests" in error_text:
            raise HTTPException(
                status_code=429,
                detail=(
                    "La plataforma esta limitando temporalmente la descarga de este video. "
                    "Espera unos minutos o prueba con el enlace completo desde Compartir > Copiar enlace."
                ),
            ) from exc
        raise HTTPException(
            status_code=400,
            detail="No pude descargar el audio. Verifica que el video sea publico y que el enlace sea valido.",
        ) from exc

    audio_files = sorted(work_dir.glob("source*.mp3"))
    if not audio_files:
        raise HTTPException(status_code=500, detail="No se genero el archivo de audio.")

    audio_path = audio_files[0]
    if audio_path.stat().st_size > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="El audio supera 25MB. Usa videos mas cortos, idealmente de menos de 10 minutos.",
        )
    return audio_path, metadata


# ==============================================================================
# BLOQUE 8: INTELIGENCIA ARTIFICIAL (Groq Principal + Gemini 3.1 Flash Lite Respaldo)
#
# ¿Por qué este orden?
# 1. GROQ ES EL MOTOR PRINCIPAL:
#    - Usa `whisper-large-v3-turbo` / `whisper-large-v3` para escuchar el audio.
#    - Usa `llama-3.3-70b-versatile` para redactar la receta en JSON.
#    - Tiene límites gratuitos mucho más amplios y responde en 1 segundo.
# 2. GEMINI 3.1 FLASH LITE ES EL MOTOR DE RESPALDO:
#    - Si Groq falla o llega a su límite, entra `gemini-3.1-flash-lite` (el más barato)
#      seguido de `gemini-3.8-flash` para que el usuario NUNCA vea un error.
# ==============================================================================


def get_groq_client() -> Groq | None:
    """
    Crea el cliente de Groq si GROQ_API_KEY esta configurada.
    Si no hay llave de Groq, devuelve None para que el sistema use el respaldo de Gemini.
    """
    key = groq_api_key()
    if not key:
        return None
    return Groq(api_key=key)


def transcribe_with_groq(client: Groq, audio_path: Path) -> str | None:
    """
    MOTOR PRINCIPAL DE AUDIO:
    Usa Whisper en Groq para convertir la voz del cocinero en texto escrito.
    """
    audio_bytes = audio_path.read_bytes()
    for whisper_model in GROQ_WHISPER_MODELS:
        try:
            transcription = client.audio.transcriptions.create(
                file=(audio_path.name, audio_bytes),
                model=whisper_model,
                response_format="text",
                temperature=0,
                language="es",
            )
            text = str(transcription or "").strip()
            if text:
                print(f"Audio transcrito exitosamente con Groq ({whisper_model})")
                return text
        except Exception as exc:
            print(f"Aviso Groq Whisper ({whisper_model}): {exc}")
    return None


def transcribe_with_gemini(audio_path: Path) -> str | None:
    """
    MOTOR DE RESPALDO DE AUDIO:
    Si Groq Whisper falla, envia el archivo MP3 a Gemini 3.1 Flash Lite para que lo transcriba.
    """
    key = gemini_api_key()
    if not key:
        return None

    try:
        gemini_client = genai.Client(api_key=key)
        audio_bytes = audio_path.read_bytes()
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3")
        prompt = (
            "Transcribe palabra por palabra todo lo que se dice en este audio de cocina en espanol. "
            "Devuelve unicamente el texto transcrito, sin comentarios adicionales."
        )
        for model_name in GEMINI_BACKUP_MODELS:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=[audio_part, prompt],
                )
                text = str(response.text or "").strip()
                if text:
                    print(f"Audio transcrito con respaldo Gemini ({model_name})")
                    return text
            except Exception as exc:
                print(f"Aviso Gemini Audio ({model_name}): {exc}")
    except Exception as init_exc:
        print(f"Error al iniciar Gemini para audio: {init_exc}")

    return None


def transcribe_audio(client: Groq | None, audio_path: Path, allow_short: bool = False) -> str:
    """
    Coordina la transcripcion del audio:
    1. Primero intenta con Groq Whisper (Principal).
    2. Si Groq falla, intenta con Gemini 3.1 Flash Lite (Respaldo).
    """
    text: str | None = None

    if client is not None:
        text = transcribe_with_groq(client, audio_path)

    if not text:
        text = transcribe_with_gemini(audio_path)

    cleaned_text = (text or "").strip()
    if not cleaned_text and not allow_short:
        raise HTTPException(
            status_code=502,
            detail="No se pudo transcribir el audio con Groq ni con Gemini. Revisa tus API keys.",
        )

    if len(cleaned_text) < 20 and not allow_short:
        raise HTTPException(
            status_code=422,
            detail="La transcripcion fue demasiado corta. El video debe tener narracion clara o descripcion con la receta.",
        )
    return cleaned_text


def extract_json(text: str) -> dict[str, Any]:
    """Limpia la respuesta de la IA y extrae exclusivamente el bloque JSON `{ ... }`."""
    cleaned = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced_match:
        cleaned = fenced_match.group(1)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def normalize_ingredients(items: list[Any]) -> list[Ingredient]:
    """Convierte una lista de textos de ingredientes en objetos Ingredient numerados."""
    ingredients: list[Ingredient] = []
    for index, item in enumerate(items):
        text = str(item).strip()
        if text:
            ingredients.append(Ingredient(id=f"ing-{index + 1}", text=text))
    return ingredients


def build_recipe_prompt(video_title: str, video_description: str, transcript: str) -> str:
    """Arma las instrucciones claras para que la IA estructure la receta en formato JSON."""
    context_sections = []
    if video_title:
        context_sections.append(f"Titulo del video:\n{video_title}")
    if video_description:
        context_sections.append(f"Descripcion del post / video:\n{video_description[:3000]}")
    if transcript.strip():
        context_sections.append(f"Transcripcion de audio:\n{transcript}")

    combined_source = "\n\n".join(context_sections)

    return f"""
Extrae una receta culinaria completa a partir de la informacion del siguiente video de cocina (transcripcion de audio y/o descripcion del post).

Devuelve SOLO JSON valido con esta forma exacta:
{{
  "title": "Nombre corto de la receta",
  "servings": "2 porciones o null",
  "prepTime": "10 min o null",
  "cookTime": "20 min o null",
  "ingredients": ["cantidad + ingrediente", "..."],
  "steps": ["paso claro en imperativo", "..."],
  "notes": ["nota util opcional"],
  "transcriptSummary": "resumen breve de lo que se preparo"
}}

Reglas:
- Combina lo que se dice en el audio con los detalles o cantidades exactas que aparezcan en la descripcion del post.
- Si no hay una receta reconocible, usa title "No se encontro receta" y deja ingredients/steps vacios.
- No inventes cantidades especificas si no se mencionan; usa frases como "cantidad al gusto".
- Escribe todo en espanol natural.

Informacion del video:
{combined_source}
""".strip()


def resolve_groq_chat_models(client: Groq) -> list[str]:
    """
    Devuelve la lista de modelos de texto en Groq encabezada siempre por
    `llama-3.3-70b-versatile`, agregando cualquier modelo activo en la cuenta como respaldo.
    """
    models = list(GROQ_CHAT_MODELS)
    try:
        available = client.models.list()
        skip_words = ("whisper", "guard", "tts", "vision", "orpheus", "playai", "allam")
        for model_info in available.data:
            model_id = str(getattr(model_info, "id", "")).strip()
            if model_id and model_id not in models and not any(w in model_id.lower() for w in skip_words):
                models.append(model_id)
    except Exception as exc:
        print(f"Aviso al listar modelos de Groq: {exc}")
    return models


def structure_recipe_with_groq(client: Groq, prompt: str, errors: list[str]) -> dict[str, Any] | None:
    """
    MOTOR PRINCIPAL DE ESTRUCTURACIÓN:
    Pide a Groq (empezando por `llama-3.3-70b-versatile`) que convierta el texto en receta JSON.
    """
    for model_name in resolve_groq_chat_models(client):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un chef editor que convierte transcripciones y descripciones "
                            "de videos en recetas estructuradas y devuelve exclusivamente JSON valido."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content or "{}"
            data = extract_json(content)
            if data and (data.get("ingredients") or data.get("steps")):
                print(f"Receta estructurada exitosamente con Groq ({model_name})")
                return data
        except Exception as exc:
            print(f"Aviso Groq ({model_name}): {exc}")
            errors.append(f"Groq({model_name}): {exc}")
    return None


def structure_recipe_with_gemini(prompt: str, errors: list[str]) -> dict[str, Any] | None:
    """
    MOTOR DE RESPALDO DE ESTRUCTURACIÓN:
    Si Groq falla o alcanza su limite, usa Gemini empezando por `gemini-3.1-flash-lite`
    (el modelo mas economico y ligero) seguido de `gemini-3.8-flash`.
    """
    key = gemini_api_key()
    if not key:
        return None

    try:
        gemini_client = genai.Client(api_key=key)
        for model_name in GEMINI_BACKUP_MODELS:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                data = extract_json(response.text or "{}")
                if data and (data.get("ingredients") or data.get("steps")):
                    print(f"Receta estructurada con respaldo Gemini ({model_name})")
                    return data
            except Exception as exc:
                print(f"Aviso Gemini ({model_name}): {exc}")
                errors.append(f"Gemini({model_name}): {exc}")
    except Exception as init_exc:
        print(f"Error al inicializar Gemini: {init_exc}")
        errors.append(f"GeminiInit: {init_exc}")

    return None


def extract_recipe(
    client: Groq | None,
    transcript: str,
    source_url: str,
    video_metadata: dict[str, Any] | None = None,
) -> Recipe:
    """
    Toma la transcripcion de voz y la descripcion del video y devuelve un objeto Recipe:
    1. Primero intenta estructurar la receta con Groq LLaMA 3.3 70B (Principal).
    2. Si Groq falla, usa Gemini 3.1 Flash Lite (Respaldo).
    """
    platform = detect_platform(source_url)
    meta = video_metadata or {}
    video_title = str(meta.get("title") or "").strip()
    video_description = str(meta.get("description") or "").strip()

    if len(transcript.strip()) < 15 and len(video_description) < 15:
        raise HTTPException(
            status_code=422,
            detail="El video no tiene narracion hablada ni descripcion con ingredientes suficientes para extraer la receta.",
        )

    prompt = build_recipe_prompt(video_title, video_description, transcript)
    errors: list[str] = []
    data: dict[str, Any] | None = None

    # 1. Motor Principal: Groq (LLaMA 3.3 70B)
    if client is not None:
        data = structure_recipe_with_groq(client, prompt, errors)

    # 2. Motor de Respaldo: Google Gemini (3.1 Flash Lite -> 3.8 Flash)
    if data is None:
        data = structure_recipe_with_gemini(prompt, errors)

    if data is None:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo estructurar la receta. Detalles: {'; '.join(errors[:3]) or 'Sin motores de IA configurados'}",
        )

    raw_ingredients = data.get("ingredients") or []
    raw_steps = data.get("steps") or []
    ingredients = normalize_ingredients(raw_ingredients if isinstance(raw_ingredients, list) else [])
    steps = [str(step).strip() for step in raw_steps if str(step).strip()] if isinstance(raw_steps, list) else []

    if not ingredients or not steps:
        raise HTTPException(
            status_code=422,
            detail="No se encontro una receta clara. Prueba con un video que tenga ingredientes y pasos narrados o en la descripcion.",
        )

    title = str(data.get("title") or "Receta extraida").strip()
    recipe_id = hashlib.sha256(f"{source_url}:{title}".encode("utf-8")).hexdigest()[:16]

    return Recipe(
        id=f"recipe-{recipe_id}",
        title=title,
        sourceUrl=source_url,
        platform=platform,
        servings=data.get("servings"),
        prepTime=data.get("prepTime"),
        cookTime=data.get("cookTime"),
        ingredients=ingredients,
        steps=steps,
        notes=[str(note).strip() for note in data.get("notes", []) if str(note).strip()]
        if isinstance(data.get("notes"), list)
        else [],
        transcriptSummary=data.get("transcriptSummary"),
    )


# ==============================================================================
# BLOQUE 9: RUTAS DE LA API (Las ventanillas de atención para el Frontend)
# Aquí están todas las direcciones web que la aplicación en Vercel llama.
# ==============================================================================


@app.get("/")
@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str | bool]:
    """Ventanilla de salud: le dice a Render y al usuario que el servidor esta vivo."""
    return {
        "status": "ok",
        "app": APP_NAME,
        "databaseReady": DATABASE_READY,
        "databaseError": DATABASE_ERROR,
        "storageConfigured": bool(supabase_url() and supabase_key()),
        "groqConfigured": bool(groq_api_key()),
        "geminiBackupConfigured": bool(gemini_api_key()),
    }


@app.post("/api/auth/google", response_model=AuthResponse)
def login_with_google(payload: GoogleLoginRequest) -> AuthResponse:
    """Inicia sesion con una cuenta de Google y devuelve el token de acceso."""
    user = verify_google_login(payload.idToken)
    return AuthResponse(accessToken=create_access_token(user.id), user=user)


@app.get("/api/me", response_model=User)
def get_me(user: User = Depends(current_user)) -> User:
    """Devuelve los datos del perfil del usuario que tiene la sesion abierta."""
    return user


@app.get("/api/recipes", response_model=list[Recipe])
def get_saved_recipes(user: User = Depends(current_user)) -> list[Recipe]:
    """Devuelve la lista de recetas privadas guardadas por el usuario."""
    return load_recipes(user.id)


@app.get("/api/explore/recipes", response_model=list[Recipe])
def get_explore_recipes(user: User = Depends(current_user)) -> list[Recipe]:
    """Devuelve el catalogo publico de recetas (seccion Explore)."""
    return load_public_recipes()


@app.delete("/api/recipes")
def delete_all_recipes(user: User = Depends(current_user)) -> Response:
    """Borra todas las recetas privadas de la cuenta del usuario."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM recipes WHERE user_id = %s", (user.id,))
    return Response(status_code=204)


@app.delete("/api/recipes/{recipe_id}")
def delete_saved_recipe(recipe_id: str, user: User = Depends(current_user)) -> Response:
    """Borra una sola receta privada seleccionada por el usuario."""
    ensure_database_ready()
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM recipes WHERE id = %s AND user_id = %s", (recipe_id, user.id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Receta no encontrada.")
    return Response(status_code=204)


@app.post("/api/recipes/{recipe_id}/save", response_model=SaveRecipeResponse)
def save_explore_recipe(recipe_id: str, user: User = Depends(current_user)) -> SaveRecipeResponse:
    """Guarda una receta publica de Explore en la cuenta privada del usuario."""
    saved_recipe = save_public_recipe_to_user(recipe_id, user.id)
    return SaveRecipeResponse(recipe=saved_recipe, subscription=get_subscription(user.id))


@app.get("/api/recipes/{recipe_id}/image")
def get_saved_recipe_image(
    recipe_id: str,
    access_token: str | None = None,
    authorization: str | None = Header(default=None),
) -> Response:
    """Entrega la foto de una receta privada (o redirige a Supabase Storage)."""
    token = access_token or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    if not token:
        raise HTTPException(status_code=401, detail="Debes iniciar sesion.")
    user = user_from_access_token(token)
    image_data, mime_type, redirect_url = load_recipe_image(user.id, recipe_id)
    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=302)
    return Response(content=image_data, media_type=mime_type)


@app.get("/api/explore/recipes/{recipe_id}/image")
def get_public_recipe_image(recipe_id: str) -> Response:
    """Entrega la foto de una receta publica de Explore (o redirige a Supabase Storage)."""
    image_data, mime_type, redirect_url = load_public_recipe_image(recipe_id)
    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=302)
    return Response(content=image_data, media_type=mime_type)


@app.patch("/api/recipes/{recipe_id}/ingredients/{ingredient_id}", response_model=Recipe)
def update_saved_ingredient(
    recipe_id: str,
    ingredient_id: str,
    payload: IngredientProgressUpdate,
    user: User = Depends(current_user),
) -> Recipe:
    """Actualiza el check de un ingrediente (comprado / pendiente)."""
    return update_ingredient_progress(user.id, recipe_id, ingredient_id, payload.checked)


@app.get("/api/subscription", response_model=Subscription)
def get_saved_subscription(user: User = Depends(current_user)) -> Subscription:
    """Consulta el plan de suscripcion actual del usuario."""
    return get_subscription(user.id)


@app.put("/api/subscription", response_model=Subscription)
def update_saved_subscription(payload: Subscription, user: User = Depends(current_user)) -> Subscription:
    """Actualiza el plan de suscripcion del usuario."""
    return save_subscription(user.id, payload.plan)


@app.post("/api/extract", response_model=Recipe)
def extract_from_video(
    payload: ExtractRequest,
    user: User | None = Depends(optional_current_user),
) -> Recipe:
    """
    RUTA PRINCIPAL DE EXTRACCION DE RECETA:
    1. Revisa si el video ya fue procesado antes (para responder al instante sin gastar IA).
    2. Si es nuevo, descarga solo el audio en una carpeta temporal.
    3. Transcribe la voz con Groq Whisper (o Gemini de respaldo).
    4. Estructura la receta con Groq LLaMA 3.3 70B (o Gemini 3.1 Flash Lite de respaldo).
    5. Guarda la receta y su imagen en Supabase y borra los archivos temporales.
    """
    ensure_database_ready()
    source_url = str(payload.url)
    should_save_private = user is not None
    owner_id = user.id if should_save_private else "public-user"

    # Paso 1: Si ya existe en la base de datos, devolverla de inmediato
    existing_recipe = find_existing_recipe_by_url(source_url, owner_id)
    if existing_recipe is not None:
        if not existing_recipe.imageUrl:
            generated = generate_recipe_image_bytes(existing_recipe.title, existing_recipe.id)
            if generated:
                image_data, content_type = generated
                save_recipe_image_bytes(existing_recipe.id, image_data, content_type)
                return load_recipe(existing_recipe.id, owner_id) or existing_recipe
        return existing_recipe

    # Paso 2: Verificar que tenemos FFmpeg y al menos un motor de IA configurado
    get_ffmpeg_location()
    groq_client = get_groq_client()
    if groq_client is None and not gemini_api_key():
        raise HTTPException(
            status_code=500,
            detail="Falta configurar GROQ_API_KEY o GEMINI_API_KEY en las variables de entorno.",
        )

    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="video2recipe-", dir=TEMP_ROOT))
    try:
        # Paso 3: Descargar audio ligero + metadatos del post
        audio_path, video_metadata = download_audio_with_metadata(source_url, temp_dir)
        has_description = len(str(video_metadata.get("description") or "").strip()) >= 20

        # Paso 4: Transcribir voz a texto (Groq Whisper -> Respaldo Gemini)
        transcript = transcribe_audio(groq_client, audio_path, allow_short=has_description)

        # Paso 5: Estructurar receta en JSON (Groq LLaMA 3.3 70B -> Respaldo Gemini 3.1 Flash Lite)
        recipe = extract_recipe(groq_client, transcript, source_url, video_metadata=video_metadata)

        # Paso 6: Guardar en Supabase PostgreSQL y subir foto a Supabase Storage
        visibility = "private" if should_save_private else "public"
        recipe_hash = hashlib.sha256(f"{owner_id}:{source_url}:{recipe.title}".encode("utf-8")).hexdigest()[:16]
        recipe.id = f"recipe-{recipe_hash}"

        saved_recipe = save_recipe(recipe, owner_id, visibility)

        generated = generate_recipe_image_bytes(
            recipe.title,
            saved_recipe.id,
            fallback_thumbnail_url=video_metadata.get("thumbnail"),
        )
        if generated:
            image_data, content_type = generated
            save_recipe_image_bytes(saved_recipe.id, image_data, content_type)

        return load_recipe(saved_recipe.id, owner_id) or saved_recipe
    finally:
        # Limpiar siempre la carpeta temporal para no llenar el disco de Render
        shutil.rmtree(temp_dir, ignore_errors=True)
