<div align="center">

# Ratatouille AI — Multimodal Video-to-Recipe Extraction Engine

**Motor inteligente de extracción y estructuración de recetas culinarias a partir de vídeos de TikTok, Instagram Reels y YouTube Shorts utilizando Inteligencia Artificial multimodal y arquitecturas RESTful.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-AI%20GenAI-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev/)
[![Groq](https://img.shields.io/badge/Groq-Whisper%20STT-F55036?style=for-the-badge)](https://groq.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-4479A1?style=for-the-badge&logo=postgresql&logoColor=white)](https://supabase.com/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Audio%20Processing-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![React](https://img.shields.io/badge/React-18%2B-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)

</div>

---

## Descripción del Proyecto

Ratatouille AI resuelve el problema de la información no estructurada en redes sociales. Transforma clips de vídeo breves (donde los chefs o creadores muestran pasos apresurados) en recetas detalladas, estructuradas y accionables. 

El sistema descarga el contenido audiovisual mediante pipelines optimizados, extrae el flujo de audio con FFmpeg, realiza la transcripción fonética de alta precisión mediante Whisper en Groq y utiliza Google Gemini para razonar sobre la preparación, estructurando ingredientes, cantidades, tiempos de cocción y pasos ordenados en un esquema JSON validado con Pydantic y almacenado de forma persistente en PostgreSQL (Supabase).

---

## Flujo de Arquitectura y Pipeline ETL

```
[ Enlace de Video (TikTok / IG / YT) ]
                │
                ▼
      [ Ingesta con yt-dlp ]
                │
                ▼
   [ Extracción de Audio con FFmpeg ]
                │
                ▼
 [ Transcripción Ultra-rápida (Groq Whisper) ]
                │
                ▼
  [ Síntesis Semántica (Google Gemini LLM) ]
  (Estructuración JSON de Ingredientes, Tiempos, Pasos)
                │
                ▼
  [ API Backend Asíncrona (FastAPI + Pydantic) ]
                │
                ▼
  [ Persistencia Relacional & BLOBs (MySQL 8) ]
                │
                ▼
    [ Interfaz Web Interactiva (React + Vite) ]
```

---

<<<<<<< HEAD
## Características Principales

* **Ingesta Multiplataforma:** Soporte para URLs de TikTok, Instagram Reels y YouTube Shorts/Videos.
* **Procesamiento Asíncrono de Medios:** Descarga eficiente y aislamiento de canales de audio para minimizar consumo de ancho de banda.
* **Inferencia de IA de Baja Latencia:** Integración híbrida con Groq para transcripción instantánea y Google GenAI para razonamiento contextual culinario.
=======
## ✨ Características Principales

* **Ingesta Multiplataforma:** Soporte para URLs de TikTok, Instagram Reels y YouTube Shorts/Videos.
* **Procesamiento Asíncrono de Medios:** Descarga eficiente y aislamiento de canales de audio para minimizar consumo de ancho de banda.
* **Inferencia de IA de Baja Latencia:** Integración híbrida con **Groq** para transcripción instantánea y **Google GenAI** para razonamiento contextual culinario.
>>>>>>> ecd439a (feat: migrate backend to PostgreSQL (Supabase), add Docker & Render blueprint, update frontend CDN)
* **Normalización de Ingredientes y Pasos:** Algoritmo que clasifica ingredientes por tipo, cantidades exactas y pasos cronológicos interactivos.
* **Persistencia Relacional Segura:** Almacenamiento en MySQL de usuarios (autenticados con Google OAuth), recetas, listas interactivas y miniaturas en binario BLOB.

---

<<<<<<< HEAD
## Especificación de la API (FastAPI)
=======
## 🔌 Especificación de la API (FastAPI)
>>>>>>> ecd439a (feat: migrate backend to PostgreSQL (Supabase), add Docker & Render blueprint, update frontend CDN)

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `POST` | `/api/extract` | Inicia el pipeline de extracción a partir de una URL multimedia. |
| `GET` | `/api/recipes` | Obtiene el catálogo de recetas procesadas del usuario autenticado. |
| `GET` | `/api/recipes/{id}` | Recupera el detalle completo de una receta estructurada. |
| `GET` | `/api/recipes/{id}/image` | Devuelve la miniatura procesada servida como binario. |
| `POST` | `/api/auth/google` | Autenticación y verificación de token OAuth de Google. |

---

<<<<<<< HEAD
## Stack Tecnológico Detallado

* **Backend:** FastAPI, Uvicorn, Pydantic v2.
* **Inteligencia Artificial:** Google Gemini SDK (google-genai), Groq API (groq).
* **Ingesta Multimedia:** yt-dlp, imageio-ffmpeg.
* **Base de Datos:** MySQL 8.0+ (mysql-connector-python).
=======
## 🛠️ Stack Tecnológico Detallado

* **Backend:** FastAPI, Uvicorn, Pydantic v2.
* **Inteligencia Artificial:** Google Gemini SDK (`google-genai`), Groq API (`groq`).
* **Ingesta Multimedia:** `yt-dlp`, `imageio-ffmpeg`.
* **Base de Datos:** MySQL 8.0+ (`mysql-connector-python`).
>>>>>>> ecd439a (feat: migrate backend to PostgreSQL (Supabase), add Docker & Render blueprint, update frontend CDN)
* **Frontend:** React, Vite, Tailwind CSS.
* **Autenticación:** Google OAuth 2.0.

---

<<<<<<< HEAD
## Instalación y Puesta en Marcha
=======
## ⚡ Instalación y Puesta en Marcha
>>>>>>> ecd439a (feat: migrate backend to PostgreSQL (Supabase), add Docker & Render blueprint, update frontend CDN)

### 1. Clonar el Repositorio
```bash
git clone https://github.com/raymonrz4r-spec/Ratatouille_IA.git
cd Ratatouille_IA
```

### 2. Configurar Variables de Entorno (`.env`)
Crea un archivo `.env` en la raíz del proyecto con la siguiente estructura:
```env
GROQ_API_KEY=tu_api_key_de_groq
APP_SECRET=tu_secreto_para_sesiones
GOOGLE_CLIENT_ID=tu_google_oauth_client_id.apps.googleusercontent.com
VITE_GOOGLE_CLIENT_ID=tu_google_oauth_client_id.apps.googleusercontent.com
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=tu_password
MYSQL_DATABASE=ratatouille
```

### 3. Ejecución Rápida
En Windows, puedes iniciar ambos servicios con:
```bat
run.bat
```
O iniciar manualmente el backend:
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

---

<<<<<<< HEAD
## Autor
=======
## 👤 Autor
>>>>>>> ecd439a (feat: migrate backend to PostgreSQL (Supabase), add Docker & Render blueprint, update frontend CDN)

**Raymon Rosario**  
* Software Engineer | Backend Developer  
* GitHub: [@raymonrz4r-spec](https://github.com/raymonrz4r-spec)  
* LinkedIn: [linkedin.com/in/raymon-rosario](https://www.linkedin.com/in/raymon-rosario/)
