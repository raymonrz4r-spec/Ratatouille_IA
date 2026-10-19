"""
MOTOR EXTRACTOR DE RECETAS CON INTELIGENCIA ARTIFICIAL (backend/main.py)

EXPLICACION PARA PERSONAS NO TECNICAS:
Este archivo es el motor inteligente de Ratatouille. Resuelve un problema
muy comun: cuando vemos un video rapido de cocina en TikTok, Instagram o
YouTube, es dificil pausar cada segundo para anotar los ingredientes y pasos.

Como trabaja este archivo paso a paso:
1. Recepcion del Enlace: El usuario pega el enlace del video en la web.
2. Descarga y Separacion: El programa descarga el video y le extrae solo
   el audio para que sea liviano y no consuma memoria innecesaria.
3. El Oido Inteligente (Groq Whisper): Escucha todo lo que dice el cocinero
   y lo transcribe exactamente a texto en cuestion de segundos.
4. El Cerebro Culinario (Google Gemini): Lee la transcripcion, comprende
   el contexto culinario y separa magicamente:
   - Nombre de la receta.
   - Lista exacta de ingredientes y cantidades (gramos, tazas, cucharadas).
   - Pasos ordenados cronologicamente (Paso 1, Paso 2, etc.).
   - Tiempos de preparacion y porciones estimadas.
5. Archivero Seguro (MySQL): Guarda la receta en la cuenta del usuario para
   que pueda consultarla, marcar ingredientes comprados y cocinar cuando quiera.
6. Puertas de Seguridad: Usa inicio de sesion oficial de Google para que
   cada persona solo vea sus recetas privadas.
"""

import json
import base64
import hashlib
import hmac
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yt_dlp
import imageio_ffmpeg
import psycopg2
from psycopg2 import Error as PostgresError
from psycopg2.extras import RealDictCursor
import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel, Field, HttpUrl
from google import genai
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")
load_dotenv(BASE_DIR.parent / ".env", encoding="utf-8-sig")

APP_NAME = "Video2Recipe"
MAX_AUDIO_BYTES = 25 * 1024 * 1024
TEMP_ROOT = Path(os.getenv("TEMP_ROOT", str(BASE_DIR / ".tmp")))
IMAGES_DIR = BASE_DIR / "static" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_READY = False
DATABASE_ERROR = "PostgreSQL (Supabase) no se ha inicializado todavia."

app = FastAPI(title=APP_NAME, version="1.0.0")

app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")

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


class ExtractRequest(BaseModel):
    url: HttpUrl


class GoogleLoginRequest(BaseModel):
    idToken: str


class User(BaseModel):
    id: str
    email: str
    name: str | None = None
    pictureUrl: str | None = None


class AuthResponse(BaseModel):
    accessToken: str
    user: User


class IngredientProgressUpdate(BaseModel):
    checked: bool


class Subscription(BaseModel):
    plan: str = "Gratuito"


class Ingredient(BaseModel):
    id: str
    text: str
    checked: bool = False


class Recipe(BaseModel):
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
    recipe: Recipe
    subscription: Subscription


def api_base_url() -> str:
    return os.getenv("VITE_API_URL", "http://localhost:8000").rstrip("/")


def google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID") or os.getenv("VITE_GOOGLE_CLIENT_ID") or ""


def app_secret() -> str:
    configured_secret = os.getenv("APP_SECRET") or os.getenv("SESSION_SECRET")
    if configured_secret:
        return configured_secret

    groq_key = os.getenv("GROQ_API_KEY") or ""
    return hashlib.sha256(f"ratatouille-session:{groq_key}".encode("utf-8")).hexdigest()


def b64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def b64url_decode(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(f"{payload}{padding}")


def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + 60 * 60 * 24 * 14,
    }
    encoded_payload = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(app_secret().encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{b64url_encode(signature)}"


def verify_access_token(token: str) -> str:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected_signature = hmac.new(
            app_secret().encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        provided_signature = b64url_decode(encoded_signature)
        if not hmac.compare_digest(expected_signature, provided_signature):
            raise ValueError("invalid signature")

        payload = json.loads(b64url_decode(encoded_payload))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired token")

        user_id = str(payload.get("sub") or "")
        if not user_id:
            raise ValueError("missing subject")
        return user_id
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Sesion invalida o expirada.") from exc


def get_database_url() -> str:
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
        detail="Falta DATABASE_URL en .env o secretos del servidor (copia el Connection String URI desde Supabase > Settings > Database).",
    )


def open_db_connection() -> Any:
    dsn = get_database_url()
    try:
        return psycopg2.connect(dsn, connect_timeout=10)
    except (PostgresError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No se pudo conectar a PostgreSQL (Supabase): {exc}",
        ) from exc


def dict_cursor(connection: Any) -> Any:
    return connection.cursor(cursor_factory=RealDictCursor)


@contextmanager
def db_connection() -> Iterator[Any]:
    connection = open_db_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# Alias para compatibilidad interna
mysql_connection = db_connection


def source_url_hash(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def supabase_url() -> str:
    return (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or "").strip().rstrip("/")


def supabase_key() -> str:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("VITE_SUPABASE_ANON_KEY")
        or ""
    ).strip()


def supabase_storage_bucket() -> str:
    return (os.getenv("SUPABASE_STORAGE_BUCKET") or "recipe-images").strip()


def is_external_image_url(url: str | None) -> bool:
    if not url:
        return False
    return (
        "/storage/v1/object/public/" in url
        or (url.startswith("http") and "/api/recipes/" not in url and "/api/explore/recipes/" not in url)
    )


def upload_to_supabase_storage(recipe_id: str, image_data: bytes, content_type: str) -> str | None:
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
        resp = requests.post(object_url, data=image_data, headers=headers, timeout=30)
        if resp.status_code in (400, 404) and "Bucket not found" in resp.text:
            # Intentar crear el bucket publico automaticamente si la key tiene permisos
            requests.post(
                f"{base_url}/storage/v1/bucket",
                json={"id": bucket, "name": bucket, "public": True},
                headers={
                    "Authorization": f"Bearer {key}",
                    "apikey": key,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            resp = requests.post(object_url, data=image_data, headers=headers, timeout=30)

        if resp.ok:
            return f"{base_url}/storage/v1/object/public/{bucket}/{filename}"
        print(f"Advertencia Supabase Storage ({resp.status_code}): {resp.text[:300]}")
    except Exception as exc:
        print(f"No se pudo subir imagen a Supabase Storage: {exc}")

    return None


def init_database() -> None:
    try:
        with db_connection() as connection:
            cursor = connection.cursor()
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
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)")
        cursor.execute(
            """
            INSERT INTO users (id, google_sub, email, name)
            VALUES
                ('legacy-user', 'legacy-default-user', 'legacy@ratatouille.local', 'Legacy User'),
                ('public-user', 'public-recipes', 'public@ratatouille.local', 'Public Recipes')
            ON CONFLICT (id) DO NOTHING
            """
        )
        cursor.execute(
            """
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
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recipes_user_updated ON recipes (user_id, updated_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recipes_visibility_updated ON recipes (visibility, updated_at DESC)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                recipe_id VARCHAR(80) NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                ingredient_id VARCHAR(80) NOT NULL,
                position INT NOT NULL,
                text TEXT NOT NULL,
                checked BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (recipe_id, ingredient_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_steps (
                id BIGSERIAL PRIMARY KEY,
                recipe_id VARCHAR(80) NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                position INT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recipe_steps_recipe ON recipe_steps (recipe_id, position ASC)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_notes (
                id BIGSERIAL PRIMARY KEY,
                recipe_id VARCHAR(80) NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                position INT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recipe_notes_recipe ON recipe_notes (recipe_id, position ASC)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_images (
                recipe_id VARCHAR(80) PRIMARY KEY REFERENCES recipes(id) ON DELETE CASCADE,
                mime_type VARCHAR(100) NOT NULL DEFAULT 'image/jpeg',
                image_data BYTEA NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id VARCHAR(80) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                plan VARCHAR(50) NOT NULL DEFAULT 'Gratuito',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, plan)
            VALUES ('legacy-user', 'Gratuito')
            ON CONFLICT (user_id) DO NOTHING
            """
        )
    except Exception as exc:
        print(f"Advertencia al inicializar esquema DDL (tablas ya existen): {exc}")
        # Verificar que la conexion y las tablas existen
        with db_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1 FROM recipes LIMIT 1")


@app.on_event("startup")
def startup() -> None:
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


def recipe_from_row(row: dict[str, Any]) -> Recipe:
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
    return User(
        id=row["id"],
        email=row["email"],
        name=row.get("name"),
        pictureUrl=row.get("picture_url"),
    )


def get_user_by_id(user_id: str, connection: Any | None = None) -> User | None:
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


def current_user(authorization: str | None = Header(default=None)) -> User:
    ensure_database_ready()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Debes iniciar sesion.")

    return user_from_access_token(authorization.removeprefix("Bearer ").strip())


def optional_current_user(authorization: str | None = Header(default=None)) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return user_from_access_token(authorization.removeprefix("Bearer ").strip())


def user_from_access_token(token: str) -> User:
    user_id = verify_access_token(token)
    with db_connection() as connection:
        user = get_user_by_id(user_id, connection)
        if user is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado.")
        return user


def recipe_image_url(recipe_id: str, is_public: bool = False) -> str:
    path = "explore/recipes" if is_public else "recipes"
    return f"{api_base_url()}/api/{path}/{recipe_id}/image"


def image_file_for_recipe(recipe_id: str) -> Path | None:
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        image_path = IMAGES_DIR / f"{recipe_id}{suffix}"
        if image_path.exists():
            return image_path
    return None


def static_image_path_from_url(image_url: str | None, recipe_id: str | None = None) -> Path | None:
    if recipe_id:
        image_path = image_file_for_recipe(recipe_id)
        if image_path:
            return image_path

    if not image_url:
        return None

    parsed = urllib.parse.urlparse(image_url)
    image_path = parsed.path or image_url
    marker = "/images/"
    if marker in image_path:
        filename = Path(image_path.split(marker, 1)[1]).name
        if filename:
            path = IMAGES_DIR / filename
            return path if path.exists() else None

    endpoint_match = re.search(r"/api/(?:explore/)?recipes/([^/]+)/image/?$", image_path)
    if endpoint_match:
        return image_file_for_recipe(endpoint_match.group(1))

    return None


def save_recipe_image_bytes(
    recipe_id: str,
    image_data: bytes,
    content_type: str,
    connection: Any | None = None,
) -> str:
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


def save_recipe_image_file(recipe_id: str, image_path: Path, connection: Any | None = None) -> None:
    image_data = image_path.read_bytes()
    suffix = image_path.suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
    save_recipe_image_bytes(recipe_id, image_data, mime_type, connection)


def write_image_bytes(recipe_id: str, image_data: bytes, content_type: str) -> Path:
    content_type = content_type.split(";", 1)[0].strip().lower()
    suffix = ".png" if content_type == "image/png" else ".webp" if content_type == "image/webp" else ".jpg"
    image_path = IMAGES_DIR / f"{recipe_id}{suffix}"
    image_path.write_bytes(image_data)
    return image_path


def fetch_image_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> tuple[bytes, str]:
    response = requests.get(
        url,
        headers={
            "User-Agent": "RatatouilleAI/1.0",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
            **(headers or {}),
        },
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")

    content_type = response.headers.get("Content-Type", "").lower()
    image_data = response.content

    if not image_data or not content_type.startswith("image/"):
        raise ValueError(f"Respuesta de imagen invalida: {content_type or 'sin content-type'}")
    return image_data, content_type


def generate_pollinations_image(prompt: str) -> tuple[bytes, str]:
    api_key = os.getenv("POLLINATIONS_API_KEY", "").strip()
    encoded_prompt = urllib.parse.quote(prompt)
    errors: list[str] = []

    if api_key:
        url = f"https://gen.pollinations.ai/image/{encoded_prompt}?width=800&height=800&model=flux"
        return fetch_image_bytes(url, {"Authorization": f"Bearer {api_key}"}, timeout=90)

    legacy_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=800&height=800&nologo=true"
    try:
        return fetch_image_bytes(legacy_url, timeout=60)
    except Exception as exc:
        errors.append(str(exc))

    new_url = f"https://gen.pollinations.ai/image/{encoded_prompt}?width=800&height=800&model=flux"
    try:
        return fetch_image_bytes(new_url, timeout=60)
    except Exception as exc:
        errors.append(str(exc))

    raise RuntimeError("; ".join(errors))


def horde_api_base_url() -> str:
    return os.getenv("HORDE_API_URL", "https://aihorde.net/api/v2").rstrip("/")


def horde_headers(content_type: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": os.getenv("HORDE_API_KEY", "0000000000").strip() or "0000000000",
        "Client-Agent": "RatatouilleAI:1.0:local",
        "Accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def horde_json_request(url: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    if payload is None:
        response = requests.get(url, headers=horde_headers(), timeout=timeout)
    else:
        response = requests.post(url, json=payload, headers=horde_headers("application/json"), timeout=timeout)

    if not response.ok:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")

    return response.json()


def decode_horde_image(image_value: str) -> tuple[bytes, str]:
    if image_value.startswith("http://") or image_value.startswith("https://"):
        return fetch_image_bytes(image_value, timeout=90)

    if image_value.startswith("data:"):
        header, encoded_data = image_value.split(",", 1)
        mime_type = header.split(";", 1)[0].removeprefix("data:") or "image/png"
        return base64.b64decode(encoded_data), mime_type

    return base64.b64decode(image_value), "image/png"


def generate_horde_image(prompt: str) -> tuple[bytes, str]:
    request_payload = {
        "prompt": f"{prompt} ### text, watermark, logo, label, blurry, low quality, deformed",
        "params": {
            "width": 512,
            "height": 512,
            "steps": 10,
            "n": 1,
            "cfg_scale": 7,
            "sampler_name": "k_euler_a",
        },
        "nsfw": False,
        "censor_nsfw": True,
        "r2": False,
        "shared": False,
    }
    submit = horde_json_request(f"{horde_api_base_url()}/generate/async", request_payload, timeout=30)
    request_id = submit.get("id")
    if not request_id:
        raise RuntimeError(submit.get("message") or "AI Horde no devolvio id de generacion.")

    timeout_seconds = int(os.getenv("HORDE_IMAGE_TIMEOUT_SECONDS", "180"))
    deadline = time.monotonic() + timeout_seconds
    status_url = f"{horde_api_base_url()}/generate/status/{request_id}"
    last_status: dict[str, Any] = {}

    while time.monotonic() < deadline:
        time.sleep(5)
        last_status = horde_json_request(status_url, timeout=30)
        generations = last_status.get("generations") or []
        if generations:
            image_value = generations[0].get("img")
            if image_value:
                return decode_horde_image(str(image_value))
        if last_status.get("faulted"):
            raise RuntimeError(last_status.get("message") or "AI Horde marco la generacion como fallida.")

    wait_time = last_status.get("wait_time")
    queue_position = last_status.get("queue_position")
    raise TimeoutError(f"AI Horde no termino a tiempo. wait_time={wait_time}, queue_position={queue_position}")


def backfill_recipe_images_from_files(connection: Any) -> None:
    cursor = dict_cursor(connection)
    cursor.execute(
        """
        SELECT recipes.id, recipes.image_url
        FROM recipes
        LEFT JOIN recipe_images ON recipe_images.recipe_id = recipes.id
        WHERE recipes.image_url IS NOT NULL
          AND recipes.image_url <> ''
          AND recipe_images.recipe_id IS NULL
        """
    )
    for row in cursor.fetchall():
        if is_external_image_url(row["image_url"]):
            continue
        image_path = static_image_path_from_url(row["image_url"], row["id"])
        if image_path:
            save_recipe_image_file(row["id"], image_path, connection)


def load_recipe(recipe_id: str, user_id: str, connection: Any | None = None) -> Recipe | None:
    close_connection = connection is None
    if connection is None:
        connection = open_db_connection()

    try:
        backfilled_image = False
        cursor = dict_cursor(connection)
        cursor.execute("SELECT * FROM recipes WHERE id = %s AND user_id = %s", (recipe_id, user_id))
        row = cursor.fetchone()
        if not row:
            return None

        recipe = recipe_from_row(row)
        stored_image_url = row.get("image_url")
        if is_external_image_url(stored_image_url):
            recipe.imageUrl = stored_image_url
        else:
            cursor.execute("SELECT 1 FROM recipe_images WHERE recipe_id = %s", (recipe.id,))
            has_image = cursor.fetchone() is not None
            if not has_image:
                image_path = static_image_path_from_url(stored_image_url, recipe.id)
                if image_path:
                    save_recipe_image_file(recipe.id, image_path, connection)
                    has_image = True
                    backfilled_image = True
            if has_image:
                # Re-leer por si se subio a Supabase Storage durante el backfill
                cursor.execute("SELECT image_url FROM recipes WHERE id = %s", (recipe.id,))
                updated_row = cursor.fetchone()
                updated_url = updated_row.get("image_url") if updated_row else None
                if is_external_image_url(updated_url):
                    recipe.imageUrl = updated_url
                else:
                    recipe.imageUrl = recipe_image_url(recipe.id, row.get("visibility") == "public")
            else:
                recipe.imageUrl = None

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
        if close_connection and backfilled_image:
            connection.commit()
        return recipe
    finally:
        if close_connection:
            connection.close()


def load_recipes(user_id: str) -> list[Recipe]:
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


def save_recipe(recipe: Recipe, user_id: str, visibility: str = "private") -> Recipe:
    ensure_database_ready()
    if visibility not in {"public", "private"}:
        raise HTTPException(status_code=422, detail="Visibilidad de receta invalida.")

    with db_connection() as connection:
        cursor = connection.cursor()
        recipe_source_hash = source_url_hash(recipe.sourceUrl)
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
                    (recipe.id, ingredient.id, index, ingredient.text, ingredient.checked)
                    for index, ingredient in enumerate(recipe.ingredients)
                ],
            )
        if recipe.steps:
            cursor.executemany(
                "INSERT INTO recipe_steps (recipe_id, position, text) VALUES (%s, %s, %s)",
                [(recipe.id, index, step) for index, step in enumerate(recipe.steps)],
            )
        if recipe.notes:
            cursor.executemany(
                "INSERT INTO recipe_notes (recipe_id, position, text) VALUES (%s, %s, %s)",
                [(recipe.id, index, note) for index, note in enumerate(recipe.notes)],
            )
        return recipe


def update_ingredient_progress(user_id: str, recipe_id: str, ingredient_id: str, checked: bool) -> Recipe:
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
    ensure_database_ready()
    with db_connection() as connection:
        cursor = dict_cursor(connection)
        cursor.execute("SELECT plan FROM subscriptions WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        return Subscription(plan=row["plan"] if row else "Gratuito")


def is_paid_plan(user_id: str) -> bool:
    return get_subscription(user_id).plan in {"Gourmet", "Chef"}


def save_subscription(user_id: str, plan: str) -> Subscription:
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


def load_recipe_image(user_id: str, recipe_id: str) -> tuple[bytes | None, str, str | None]:
    """Devuelve (image_bytes, mime_type, redirect_url)."""
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
    """Devuelve (image_bytes, mime_type, redirect_url)."""
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


def save_public_recipe_to_user(public_recipe_id: str, user_id: str) -> Recipe:
    if not is_paid_plan(user_id):
        raise HTTPException(status_code=403, detail="Necesitas un plan Gourmet o Chef para guardar recetas de Explore.")

    with db_connection() as connection:
        public_recipe = load_recipe(public_recipe_id, "public-user", connection)
        if public_recipe is None:
            raise HTTPException(status_code=404, detail="Receta publica no encontrada.")

        private_id = f"recipe-{hashlib.sha256(f'{user_id}:{public_recipe.sourceUrl}:{public_recipe.title}'.encode('utf-8')).hexdigest()[:16]}"
        private_recipe = public_recipe.model_copy(deep=True)
        private_recipe.id = private_id
        if is_external_image_url(public_recipe.imageUrl):
            private_recipe.imageUrl = public_recipe.imageUrl
        else:
            private_recipe.imageUrl = recipe_image_url(private_id)
        private_recipe.ingredients = [
            Ingredient(id=ingredient.id, text=ingredient.text, checked=False)
            for ingredient in private_recipe.ingredients
        ]

    saved_recipe = save_recipe(private_recipe, user_id, "private")

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

    reloaded_recipe = load_recipe(saved_recipe.id, user_id)
    return reloaded_recipe or saved_recipe


def get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "tu_api_key_aqui":
        raise HTTPException(
            status_code=500,
            detail="Falta GROQ_API_KEY. Definela en .env o en las variables de entorno.",
        )
    return Groq(api_key=api_key)


def detect_platform(url: str) -> str:
    host = url.lower()
    if "tiktok.com" in host:
        return "TikTok"
    if "instagram.com" in host:
        return "Instagram"
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    return "Video"


def get_ffmpeg_location() -> str:
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
    """Descarga exclusivamente el flujo de audio (sin video) y extrae los metadatos del post."""
    ffmpeg_location = get_ffmpeg_location()
    output_template = str(work_dir / "source.%(ext)s")
    options: dict[str, Any] = {
        # Prioriza audio puro de bajo peso (m4a/webm/opus) sin bajar video
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

    # Soporte opcional de cookies (para evitar bloqueos 429 en datacenters como HF Spaces)
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


def download_audio(url: str, work_dir: Path) -> Path:
    audio_path, _ = download_audio_with_metadata(url, work_dir)
    return audio_path


def transcribe_audio(client: Groq, audio_path: Path, allow_short: bool = False) -> str:
    try:
        with audio_path.open("rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(audio_path.name, audio_file.read()),
                model="whisper-large-v3",
                response_format="text",
                temperature=0,
                language="es",
            )
    except Exception as exc:
        error_text = str(exc)
        if "invalid_api_key" in error_text or "Error code: 401" in error_text:
            raise HTTPException(
                status_code=401,
                detail="La API key de Groq es invalida o fue revocada. Revisa GROQ_API_KEY en .env.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Groq no pudo transcribir el audio. Intentalo otra vez en unos minutos.",
        ) from exc

    text = str(transcription).strip()
    if len(text) < 20 and not allow_short:
        raise HTTPException(
            status_code=422,
            detail="La transcripcion fue demasiado corta. El video debe tener narracion clara o descripcion con la receta.",
        )
    return text


def extract_json(text: str) -> dict[str, Any]:
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
    ingredients: list[Ingredient] = []
    for index, item in enumerate(items):
        text = str(item).strip()
        if text:
            ingredients.append(Ingredient(id=f"ing-{index + 1}", text=text))
    return ingredients


def extract_recipe(
    client: Groq,
    transcript: str,
    source_url: str,
    video_metadata: dict[str, Any] | None = None,
) -> Recipe:
    platform = detect_platform(source_url)
    meta = video_metadata or {}
    video_title = str(meta.get("title") or "").strip()
    video_description = str(meta.get("description") or "").strip()

    if len(transcript.strip()) < 15 and len(video_description) < 15:
        raise HTTPException(
            status_code=422,
            detail="El video no tiene narracion hablada ni descripcion con ingredientes suficientes para extraer la receta.",
        )

    context_sections = []
    if video_title:
        context_sections.append(f"Titulo del video:\n{video_title}")
    if video_description:
        context_sections.append(f"Descripcion del post / video:\n{video_description[:3000]}")
    if transcript.strip():
        context_sections.append(f"Transcripcion de audio:\n{transcript}")

    combined_source = "\n\n".join(context_sections)

    prompt = f"""
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

    data: dict[str, Any] | None = None
    gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    errors: list[str] = []

    # 1. Intentar con Gemini si la clave esta configurada
    if gemini_key:
        try:
            gemini_client = genai.Client(api_key=gemini_key)
            gemini_models = [
                "gemini-3.8-flash",
                "gemini-3.1-pro-preview",
            ]
            try:
                for m in gemini_client.models.list():
                    m_name = getattr(m, "name", "").replace("models/", "")
                    # Ignorar modelos que no son de texto/recetas (generacion de video, audio en vivo, etc)
                    if any(skip in m_name.lower() for skip in ["veo", "live", "native-audio", "embed", "imagen", "bidi", "tts"]):
                        continue
                    methods = getattr(m, "supported_generation_methods", []) or []
                    if methods and "generateContent" not in methods:
                        continue
                    if m_name and m_name not in gemini_models:
                        if "flash" in m_name.lower():
                            gemini_models.append(m_name)
                        elif "pro" in m_name.lower():
                            gemini_models.append(m_name)
            except Exception as list_err:
                print(f"Nota: list_models en Gemini no disponible: {list_err}")

            for g_model in gemini_models:
                try:
                    gemini_resp = gemini_client.models.generate_content(
                        model=g_model,
                        contents=prompt,
                    )
                    data = extract_json(gemini_resp.text or "{}")
                    if data and (data.get("ingredients") or data.get("steps")):
                        print(f"Receta estructurada exitosamente con Gemini: {g_model}")
                        break
                except Exception as g_exc:
                    print(f"Error con Gemini({g_model}): {g_exc}")
                    errors.append(f"Gemini({g_model}): {g_exc}")
        except Exception as gemini_init_exc:
            print(f"Error al inicializar cliente Gemini: {gemini_init_exc}")
            errors.append(f"Gemini Init: {gemini_init_exc}")

    # 2. Si no funciono o no hay Gemini, intentar con Groq
    if data is None and client is not None:
        groq_models = []
        try:
            available_groq = client.models.list()
            groq_models = [m.id for m in available_groq.data if "whisper" not in m.id.lower()]
        except Exception as groq_list_err:
            print(f"Nota: list_models en Groq: {groq_list_err}")

        if not groq_models:
            groq_models = ["llama-3.3-70b-specdec", "llama-3.2-3b-preview", "llama-3.2-1b-preview", "qwen-2.5-32b"]

        for q_model in groq_models:
            try:
                completion = client.chat.completions.create(
                    model=q_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Eres un chef editor que convierte transcripciones y descripciones de videos en recetas estructuradas y devuelve JSON valido.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                content = completion.choices[0].message.content or "{}"
                data = extract_json(content)
                if data and (data.get("ingredients") or data.get("steps")):
                    print(f"Receta estructurada exitosamente con Groq: {q_model}")
                    break
            except Exception as q_exc:
                print(f"Error con Groq({q_model}): {q_exc}")
                errors.append(f"Groq({q_model}): {q_exc}")

    if data is None:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo estructurar la receta desde la transcripcion. Errores: {'; '.join(errors) or 'Sin modelos disponibles'}",
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


@app.get("/")
@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "app": APP_NAME,
        "databaseReady": DATABASE_READY,
        "databaseError": DATABASE_ERROR,
        "storageConfigured": bool(supabase_url() and supabase_key()),
    }


@app.post("/api/auth/google", response_model=AuthResponse)
def login_with_google(payload: GoogleLoginRequest) -> AuthResponse:
    user = verify_google_login(payload.idToken)
    return AuthResponse(accessToken=create_access_token(user.id), user=user)


@app.get("/api/me", response_model=User)
def get_me(user: User = Depends(current_user)) -> User:
    return user


@app.get("/api/recipes", response_model=list[Recipe])
def get_saved_recipes(user: User = Depends(current_user)) -> list[Recipe]:
    return load_recipes(user.id)


@app.get("/api/explore/recipes", response_model=list[Recipe])
def get_explore_recipes(user: User = Depends(current_user)) -> list[Recipe]:
    return load_public_recipes()


@app.delete("/api/recipes")
def delete_all_recipes(user: User = Depends(current_user)) -> Response:
    ensure_database_ready()
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM recipes WHERE user_id = %s", (user.id,))
    return Response(status_code=204)


@app.delete("/api/recipes/{recipe_id}")
def delete_saved_recipe(recipe_id: str, user: User = Depends(current_user)) -> Response:
    ensure_database_ready()
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM recipes WHERE id = %s AND user_id = %s", (recipe_id, user.id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Receta no encontrada.")
    return Response(status_code=204)


@app.post("/api/recipes/{recipe_id}/save", response_model=SaveRecipeResponse)
def save_explore_recipe(recipe_id: str, user: User = Depends(current_user)) -> SaveRecipeResponse:
    saved_recipe = save_public_recipe_to_user(recipe_id, user.id)
    return SaveRecipeResponse(recipe=saved_recipe, subscription=get_subscription(user.id))


@app.get("/api/recipes/{recipe_id}/image")
def get_saved_recipe_image(
    recipe_id: str,
    access_token: str | None = None,
    authorization: str | None = Header(default=None),
) -> Response:
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
    return update_ingredient_progress(user.id, recipe_id, ingredient_id, payload.checked)


@app.get("/api/subscription", response_model=Subscription)
def get_saved_subscription(user: User = Depends(current_user)) -> Subscription:
    return get_subscription(user.id)


@app.put("/api/subscription", response_model=Subscription)
def update_saved_subscription(payload: Subscription, user: User = Depends(current_user)) -> Subscription:
    return save_subscription(user.id, payload.plan)


def generate_recipe_image_bytes(title: str, recipe_id: str, fallback_thumbnail_url: str | None = None) -> tuple[bytes, str] | None:
    prompt = f"Professional food photography of {title}, high quality, cinematic lighting, appetizing, highly detailed"
    provider_errors: list[str] = []

    for provider_name, generator in (
        ("Pollinations", generate_pollinations_image),
        ("AI Horde", generate_horde_image),
    ):
        try:
            image_data, content_type = generator(prompt)
            print(f"Imagen generada con {provider_name}: {recipe_id}")
            return image_data, content_type
        except Exception as exc:
            provider_errors.append(f"{provider_name}: {exc}")
            print(f"Error generando imagen con {provider_name}: {exc}")

    if fallback_thumbnail_url:
        try:
            image_data, content_type = fetch_image_bytes(fallback_thumbnail_url, timeout=20)
            print(f"Usando miniatura original del video para {recipe_id}")
            return image_data, content_type
        except Exception as exc:
            provider_errors.append(f"Thumbnail: {exc}")

    print(f"No se pudo generar imagen para {recipe_id}. {' | '.join(provider_errors)}")
    return None


def find_existing_recipe_by_url(source_url: str, owner_id: str) -> Recipe | None:
    """Busca en la DB si ya existe una receta con el mismo source_url para el owner dado."""
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


@app.post("/api/extract", response_model=Recipe)
def extract_from_video(payload: ExtractRequest, user: User | None = Depends(optional_current_user)) -> Recipe:
    ensure_database_ready()
    source_url = str(payload.url)
    should_save_private = user is not None
    owner_id = user.id if should_save_private else "public-user"

    # Verificar si la receta ya existe en la DB antes de procesarla
    existing_recipe = find_existing_recipe_by_url(source_url, owner_id)
    if existing_recipe is not None:
        if not existing_recipe.imageUrl:
            generated = generate_recipe_image_bytes(existing_recipe.title, existing_recipe.id)
            if generated:
                image_data, content_type = generated
                save_recipe_image_bytes(existing_recipe.id, image_data, content_type)
                reloaded_recipe = load_recipe(existing_recipe.id, owner_id)
                return reloaded_recipe or existing_recipe
        return existing_recipe

    get_ffmpeg_location()
    client = get_groq_client()

    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="video2recipe-", dir=TEMP_ROOT))
    try:
        audio_path, video_metadata = download_audio_with_metadata(source_url, Path(temp_dir))
        has_description = len(str(video_metadata.get("description") or "").strip()) >= 20
        transcript = transcribe_audio(client, audio_path, allow_short=has_description)
        recipe = extract_recipe(client, transcript, source_url, video_metadata=video_metadata)
        visibility = "private" if should_save_private else "public"
        recipe_id = hashlib.sha256(f"{owner_id}:{source_url}:{recipe.title}".encode("utf-8")).hexdigest()[:16]
        recipe.id = f"recipe-{recipe_id}"

        saved_recipe = save_recipe(recipe, owner_id, visibility)

        # Generar o rescatar miniatura y subir a Supabase Storage
        generated = generate_recipe_image_bytes(
            recipe.title,
            saved_recipe.id,
            fallback_thumbnail_url=video_metadata.get("thumbnail"),
        )
        if generated:
            image_data, content_type = generated
            save_recipe_image_bytes(saved_recipe.id, image_data, content_type)

        reloaded_recipe = load_recipe(saved_recipe.id, owner_id)
        return reloaded_recipe or saved_recipe
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
