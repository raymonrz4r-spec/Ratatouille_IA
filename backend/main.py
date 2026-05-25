import json
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yt_dlp
import imageio_ffmpeg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel, Field, HttpUrl
from google import genai

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")
load_dotenv(BASE_DIR.parent / ".env", encoding="utf-8-sig")

APP_NAME = "Video2Recipe"
MAX_AUDIO_BYTES = 25 * 1024 * 1024
TEMP_ROOT = BASE_DIR / ".tmp"
IMAGES_DIR = BASE_DIR / "static" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

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
def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME}


def generate_recipe_image(title: str, recipe_id: str) -> str | None:
    try:
        import urllib.parse
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
            
        apiUrl = os.getenv("VITE_API_URL", "http://localhost:8000")
        return f"{apiUrl}/images/{image_filename}"
            
    except Exception as e:
        print(f"Error generando imagen: {e}")
        return None

@app.post("/api/extract", response_model=Recipe)
def extract_from_video(payload: ExtractRequest) -> Recipe:
    get_ffmpeg_location()
    client = get_groq_client()
    source_url = str(payload.url)

    TEMP_ROOT.mkdir(exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="video2recipe-", dir=TEMP_ROOT))
    try:
        audio_path = download_audio(source_url, Path(temp_dir))
        transcript = transcribe_audio(client, audio_path)
        recipe = extract_recipe(client, transcript, source_url)
        
        # Intentar generar la imagen de manera segura
        recipe.imageUrl = generate_recipe_image(recipe.title, recipe.id)
        
        return recipe
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
