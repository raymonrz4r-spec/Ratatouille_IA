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
import mysql.connector
from mysql.connector import Error as MySQLError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
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
TEMP_ROOT = BASE_DIR / ".tmp"
IMAGES_DIR = BASE_DIR / "static" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_READY = False
DATABASE_ERROR = "MySQL no se ha inicializado todavia."

app = FastAPI(title=APP_NAME, version="1.0.0")

app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://tttfsqq3-5173.use2.devtunnels.ms/"
    ],
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


def get_mysql_settings(include_database: bool = True) -> dict[str, Any]:
    database = os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME") or "ratatouille"
    if not re.fullmatch(r"[A-Za-z0-9_$]+", database):
        raise HTTPException(
            status_code=500,
            detail="MYSQL_DATABASE/DB_NAME solo puede contener letras, numeros, _ o $.",
        )

    settings: dict[str, Any] = {
        "host": os.getenv("MYSQL_HOST") or os.getenv("DB_HOST") or "localhost",
        "port": int(os.getenv("MYSQL_PORT") or os.getenv("DB_PORT") or "3306"),
        "user": os.getenv("MYSQL_USER") or os.getenv("DB_USER") or "root",
        "password": os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD") or "",
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "autocommit": False,
    }
    if include_database:
        settings["database"] = database
    return settings


@contextmanager
def mysql_connection(include_database: bool = True) -> Iterator[Any]:
    try:
        connection = mysql.connector.connect(**get_mysql_settings(include_database))
    except (MySQLError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar a MySQL. Revisa MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD y MYSQL_DATABASE en .env.",
        ) from exc

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def source_url_hash(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def column_exists(cursor: Any, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    )
    row = cursor.fetchone()
    return bool(row[0] if isinstance(row, tuple) else row["count"])


def index_exists(cursor: Any, table: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND index_name = %s
        """,
        (table, index_name),
    )
    row = cursor.fetchone()
    return bool(row[0] if isinstance(row, tuple) else row["count"])


def constraint_exists(cursor: Any, constraint_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.table_constraints
        WHERE table_schema = DATABASE()
          AND constraint_name = %s
        """,
        (constraint_name,),
    )
    row = cursor.fetchone()
    return bool(row[0] if isinstance(row, tuple) else row["count"])


def init_database() -> None:
    database_name = os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME") or "ratatouille"

    with mysql_connection(include_database=False) as connection:
        cursor = connection.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )

    with mysql_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(80) PRIMARY KEY,
                google_sub VARCHAR(255) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL,
                name VARCHAR(255) NULL,
                picture_url TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_users_email (email)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            INSERT INTO users (id, google_sub, email, name)
            VALUES ('legacy-user', 'legacy-default-user', 'legacy@ratatouille.local', 'Legacy User')
            ON DUPLICATE KEY UPDATE id = id
            """
        )
        cursor.execute(
            """
            INSERT INTO users (id, google_sub, email, name)
            VALUES ('public-user', 'public-recipes', 'public@ratatouille.local', 'Public Recipes')
            ON DUPLICATE KEY UPDATE id = id
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipes (
                id VARCHAR(80) PRIMARY KEY,
                user_id VARCHAR(80) NULL,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        if not column_exists(cursor, "recipes", "user_id"):
            cursor.execute("ALTER TABLE recipes ADD COLUMN user_id VARCHAR(80) NULL AFTER id")
        if not column_exists(cursor, "recipes", "visibility"):
            cursor.execute("ALTER TABLE recipes ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'private' AFTER user_id")
        cursor.execute("UPDATE recipes SET user_id = 'legacy-user' WHERE user_id IS NULL")
        cursor.execute("UPDATE recipes SET visibility = 'private' WHERE visibility IS NULL OR visibility = ''")
        cursor.execute("ALTER TABLE recipes MODIFY COLUMN user_id VARCHAR(80) NOT NULL")
        if index_exists(cursor, "recipes", "source_url_hash"):
            cursor.execute("ALTER TABLE recipes DROP INDEX source_url_hash")
        if not index_exists(cursor, "recipes", "uniq_recipes_user_source"):
            cursor.execute("ALTER TABLE recipes ADD UNIQUE KEY uniq_recipes_user_source (user_id, source_url_hash)")
        if not index_exists(cursor, "recipes", "idx_recipes_user_updated"):
            cursor.execute("ALTER TABLE recipes ADD INDEX idx_recipes_user_updated (user_id, updated_at)")
        if not index_exists(cursor, "recipes", "idx_recipes_visibility_updated"):
            cursor.execute("ALTER TABLE recipes ADD INDEX idx_recipes_visibility_updated (visibility, updated_at)")
        if not constraint_exists(cursor, "fk_recipes_user"):
            cursor.execute(
                """
                ALTER TABLE recipes
                ADD CONSTRAINT fk_recipes_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
                """
            )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                recipe_id VARCHAR(80) NOT NULL,
                ingredient_id VARCHAR(80) NOT NULL,
                position INT NOT NULL,
                text TEXT NOT NULL,
                checked BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (recipe_id, ingredient_id),
                CONSTRAINT fk_recipe_ingredients_recipe
                    FOREIGN KEY (recipe_id) REFERENCES recipes(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_steps (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                recipe_id VARCHAR(80) NOT NULL,
                position INT NOT NULL,
                text TEXT NOT NULL,
                INDEX idx_recipe_steps_recipe (recipe_id),
                CONSTRAINT fk_recipe_steps_recipe
                    FOREIGN KEY (recipe_id) REFERENCES recipes(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_notes (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                recipe_id VARCHAR(80) NOT NULL,
                position INT NOT NULL,
                text TEXT NOT NULL,
                INDEX idx_recipe_notes_recipe (recipe_id),
                CONSTRAINT fk_recipe_notes_recipe
                    FOREIGN KEY (recipe_id) REFERENCES recipes(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_images (
                recipe_id VARCHAR(80) PRIMARY KEY,
                mime_type VARCHAR(100) NOT NULL DEFAULT 'image/jpeg',
                image_data LONGBLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_recipe_images_recipe
                    FOREIGN KEY (recipe_id) REFERENCES recipes(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id VARCHAR(80) PRIMARY KEY,
                plan VARCHAR(50) NOT NULL DEFAULT 'Gratuito',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_subscriptions_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        if column_exists(cursor, "subscriptions", "id") and not column_exists(cursor, "subscriptions", "user_id"):
            cursor.execute("ALTER TABLE subscriptions CHANGE COLUMN id user_id VARCHAR(80) NOT NULL")
        if not constraint_exists(cursor, "fk_subscriptions_user"):
            cursor.execute("UPDATE subscriptions SET user_id = 'legacy-user' WHERE user_id = 'default-user'")
            cursor.execute(
                """
                ALTER TABLE subscriptions
                ADD CONSTRAINT fk_subscriptions_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
                """
            )
        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, plan)
            VALUES ('legacy-user', 'Gratuito')
            ON DUPLICATE KEY UPDATE user_id = user_id
            """
        )
        backfill_recipe_images_from_files(connection)


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
        print(f"MySQL no esta listo: {DATABASE_ERROR}")


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
        connection = mysql.connector.connect(**get_mysql_settings())

    try:
        cursor = connection.cursor(dictionary=True)
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

    with mysql_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO users (id, google_sub, email, name, picture_url)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                email = VALUES(email),
                name = VALUES(name),
                picture_url = VALUES(picture_url),
                last_login_at = CURRENT_TIMESTAMP
            """,
            (user_id, google_sub, email, name, picture_url),
        )
        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, plan)
            VALUES (%s, 'Gratuito')
            ON DUPLICATE KEY UPDATE user_id = user_id
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
    with mysql_connection() as connection:
        user = get_user_by_id(user_id, connection)
        if user is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado.")
        return user


def recipe_image_url(recipe_id: str, is_public: bool = False) -> str:
    path = "explore/recipes" if is_public else "recipes"
    return f"{api_base_url()}/api/{path}/{recipe_id}/image"


def static_image_path_from_url(image_url: str | None) -> Path | None:
    if not image_url:
        return None

    parsed = urllib.parse.urlparse(image_url)
    image_path = parsed.path or image_url
    marker = "/images/"
    if marker not in image_path:
        return None

    filename = Path(image_path.split(marker, 1)[1]).name
    if not filename:
        return None

    path = IMAGES_DIR / filename
    return path if path.exists() else None


def save_recipe_image_file(recipe_id: str, image_path: Path, connection: Any | None = None) -> None:
    close_connection = connection is None
    if connection is None:
        connection = mysql.connector.connect(**get_mysql_settings())

    try:
        image_data = image_path.read_bytes()
        suffix = image_path.suffix.lower()
        mime_type = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO recipe_images (recipe_id, mime_type, image_data)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                mime_type = VALUES(mime_type),
                image_data = VALUES(image_data)
            """,
            (recipe_id, mime_type, image_data),
        )
        if close_connection:
            connection.commit()
    finally:
        if close_connection:
            connection.close()


def backfill_recipe_images_from_files(connection: Any) -> None:
    cursor = connection.cursor(dictionary=True)
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
        image_path = static_image_path_from_url(row["image_url"])
        if image_path:
            save_recipe_image_file(row["id"], image_path, connection)


def load_recipe(recipe_id: str, user_id: str, connection: Any | None = None) -> Recipe | None:
    close_connection = connection is None
    if connection is None:
        connection = mysql.connector.connect(**get_mysql_settings())

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM recipes WHERE id = %s AND user_id = %s", (recipe_id, user_id))
        row = cursor.fetchone()
        if not row:
            return None

        recipe = recipe_from_row(row)
        cursor.execute("SELECT 1 FROM recipe_images WHERE recipe_id = %s", (recipe.id,))
        if cursor.fetchone():
            recipe.imageUrl = recipe_image_url(recipe.id, row.get("visibility") == "public")

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
        return recipe
    finally:
        if close_connection:
            connection.close()


def load_recipes(user_id: str) -> list[Recipe]:
    ensure_database_ready()
    with mysql_connection() as connection:
        cursor = connection.cursor(dictionary=True)
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
    with mysql_connection() as connection:
        cursor = connection.cursor(dictionary=True)
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

    with mysql_connection() as connection:
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
                prep_time, cook_time, transcript_summary, image_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                visibility = VALUES(visibility),
                title = VALUES(title),
                source_url = VALUES(source_url),
                source_url_hash = VALUES(source_url_hash),
                platform = VALUES(platform),
                servings = VALUES(servings),
                prep_time = VALUES(prep_time),
                cook_time = VALUES(cook_time),
                transcript_summary = VALUES(transcript_summary),
                image_url = VALUES(image_url)
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
    with mysql_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE recipe_ingredients
            INNER JOIN recipes ON recipes.id = recipe_ingredients.recipe_id
            SET recipe_ingredients.checked = %s
            WHERE recipe_ingredients.recipe_id = %s
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
    with mysql_connection() as connection:
        cursor = connection.cursor(dictionary=True)
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
    with mysql_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, plan)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE plan = VALUES(plan)
            """,
            (user_id, plan),
        )
    return Subscription(plan=plan)


def load_recipe_image(user_id: str, recipe_id: str) -> tuple[bytes, str]:
    ensure_database_ready()
    with mysql_connection() as connection:
        cursor = connection.cursor(dictionary=True)
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

        return bytes(row["image_data"]), row["mime_type"]


def load_public_recipe_image(recipe_id: str) -> tuple[bytes, str]:
    ensure_database_ready()
    with mysql_connection() as connection:
        cursor = connection.cursor(dictionary=True)
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

        return bytes(row["image_data"]), row["mime_type"]


def save_public_recipe_to_user(public_recipe_id: str, user_id: str) -> Recipe:
    if not is_paid_plan(user_id):
        raise HTTPException(status_code=403, detail="Necesitas un plan Gourmet o Chef para guardar recetas de Explore.")

    with mysql_connection() as connection:
        public_recipe = load_recipe(public_recipe_id, "public-user", connection)
        if public_recipe is None:
            raise HTTPException(status_code=404, detail="Receta publica no encontrada.")

        private_id = f"recipe-{hashlib.sha256(f'{user_id}:{public_recipe.sourceUrl}:{public_recipe.title}'.encode('utf-8')).hexdigest()[:16]}"
        private_recipe = public_recipe.model_copy(deep=True)
        private_recipe.id = private_id
        private_recipe.imageUrl = recipe_image_url(private_id)
        private_recipe.ingredients = [
            Ingredient(id=ingredient.id, text=ingredient.text, checked=False)
            for ingredient in private_recipe.ingredients
        ]

    saved_recipe = save_recipe(private_recipe, user_id, "private")

    with mysql_connection() as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT mime_type, image_data FROM recipe_images WHERE recipe_id = %s",
            (public_recipe_id,),
        )
        image_row = cursor.fetchone()
        if image_row:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO recipe_images (recipe_id, mime_type, image_data)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    mime_type = VALUES(mime_type),
                    image_data = VALUES(image_data)
                """,
                (private_id, image_row["mime_type"], image_row["image_data"]),
            )

    return saved_recipe


def get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "tu_api_key_aqui":
        raise HTTPException(
            status_code=500,
            detail="Falta GROQ_API_KEY. Definela en run.bat, .env o en las variables de entorno.",
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
            detail="ffmpeg no esta disponible. Ejecuta setup.bat para instalar el FFmpeg local de la app.",
        ) from exc


def download_audio(url: str, work_dir: Path) -> Path:
    ffmpeg_location = get_ffmpeg_location()
    output_template = str(work_dir / "source.%(ext)s")
    options: dict[str, Any] = {
        "format": "bestaudio/best",
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
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        error_text = str(exc)
        if "HTTP Error 429" in error_text or "Too Many Requests" in error_text:
            raise HTTPException(
                status_code=429,
                detail=(
                    "TikTok esta limitando temporalmente la descarga de este video. "
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
    return audio_path


def transcribe_audio(client: Groq, audio_path: Path) -> str:
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
    if len(text) < 20:
        raise HTTPException(
            status_code=422,
            detail="La transcripcion fue demasiado corta. El video debe tener narracion clara de una receta.",
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


def extract_recipe(client: Groq, transcript: str, source_url: str) -> Recipe:
    platform = detect_platform(source_url)
    prompt = f"""
Extrae una receta desde esta transcripcion de un video de cocina.

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
- Si no hay una receta reconocible, usa title "No se encontro receta" y deja ingredients/steps vacios.
- No inventes cantidades especificas si la transcripcion no las menciona; usa frases como "cantidad al gusto".
- Escribe todo en espanol natural.

Transcripcion:
{transcript}
""".strip()

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Eres un chef editor que convierte transcripciones en recetas estructuradas y devuelve JSON valido.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        data = extract_json(content)
    except Exception as exc:
        error_text = str(exc)
        if "invalid_api_key" in error_text or "Error code: 401" in error_text:
            raise HTTPException(
                status_code=401,
                detail="La API key de Groq es invalida o fue revocada. Revisa GROQ_API_KEY en .env.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Groq no pudo extraer la receta desde la transcripcion.",
        ) from exc

    raw_ingredients = data.get("ingredients") or []
    raw_steps = data.get("steps") or []
    ingredients = normalize_ingredients(raw_ingredients if isinstance(raw_ingredients, list) else [])
    steps = [str(step).strip() for step in raw_steps if str(step).strip()] if isinstance(raw_steps, list) else []

    if not ingredients or not steps:
        raise HTTPException(
            status_code=422,
            detail="No se encontro una receta clara. Prueba con un video que tenga ingredientes y pasos narrados.",
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


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "app": APP_NAME,
        "databaseReady": DATABASE_READY,
        "databaseError": DATABASE_ERROR,
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
    with mysql_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM recipes WHERE user_id = %s", (user.id,))
    return Response(status_code=204)


@app.delete("/api/recipes/{recipe_id}")
def delete_saved_recipe(recipe_id: str, user: User = Depends(current_user)) -> Response:
    ensure_database_ready()
    with mysql_connection() as connection:
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
    image_data, mime_type = load_recipe_image(user.id, recipe_id)
    return Response(content=image_data, media_type=mime_type)


@app.get("/api/explore/recipes/{recipe_id}/image")
def get_public_recipe_image(recipe_id: str) -> Response:
    image_data, mime_type = load_public_recipe_image(recipe_id)
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


def generate_recipe_image(title: str, recipe_id: str, is_public: bool = False) -> tuple[str, Path] | None:
    try:
        import urllib.request
        
        # Using Pollinations AI since Gemini Imagen requires a paid tier
        prompt = f"Professional food photography of {title}, high quality, cinematic lighting, appetizing, highly detailed"
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=800&height=800&nologo=true"
        
        image_filename = f"{recipe_id}.jpg"
        image_path = IMAGES_DIR / image_filename
        
        req = urllib.request.Request(
            image_url, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        
        with urllib.request.urlopen(req) as response, open(image_path, 'wb') as out_file:
            out_file.write(response.read())

        return recipe_image_url(recipe_id, is_public), image_path
            
    except Exception as e:
        print(f"Error generando imagen: {e}")
        return None

@app.post("/api/extract", response_model=Recipe)
def extract_from_video(payload: ExtractRequest, user: User | None = Depends(optional_current_user)) -> Recipe:
    get_ffmpeg_location()
    client = get_groq_client()
    source_url = str(payload.url)

    TEMP_ROOT.mkdir(exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="video2recipe-", dir=TEMP_ROOT))
    try:
        audio_path = download_audio(source_url, Path(temp_dir))
        transcript = transcribe_audio(client, audio_path)
        recipe = extract_recipe(client, transcript, source_url)
        should_save_private = user is not None
        owner_id = user.id if should_save_private else "public-user"
        visibility = "private" if should_save_private else "public"
        recipe_id = hashlib.sha256(f"{owner_id}:{source_url}:{recipe.title}".encode("utf-8")).hexdigest()[:16]
        recipe.id = f"recipe-{recipe_id}"
        
        # Intentar generar la imagen de manera segura
        generated_image = generate_recipe_image(recipe.title, recipe.id, visibility == "public")
        image_path = None
        if generated_image:
            recipe.imageUrl, image_path = generated_image

        saved_recipe = save_recipe(recipe, owner_id, visibility)
        if image_path:
            save_recipe_image_file(saved_recipe.id, image_path)
        return saved_recipe
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
