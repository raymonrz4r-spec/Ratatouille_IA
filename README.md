# Ratatouille

Extrae recetas automaticamente desde videos de TikTok, Instagram Reels y YouTube usando IA.

## Requisitos

- Python 3.10+
- Node.js 18+
- FFmpeg local instalado por `setup.bat`
- API key de Groq

## Instalacion

Doble click en:

```bat
setup.bat
```

Luego edita `.env` y coloca:

```env
GROQ_API_KEY=tu_api_key_aqui
```

## Ejecutar

Doble click en:

```bat
run.bat
```

La app abre:

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`

## Uso

1. Copia el enlace de un video publico de cocina.
2. Pegalo en la barra de busqueda.
3. Presiona **Extraer**.
4. Espera mientras se descarga el audio, se transcribe y se estructura la receta.
5. La receta queda guardada en LocalStorage.

## Estructura

```text
video2recipe/
├── backend/
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── SearchBar.jsx
│   │   │   ├── RecipeGrid.jsx
│   │   │   ├── RecipeCard.jsx
│   │   │   ├── Patrocinador.jsx
│   │   │   └── ErrorToast.jsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── setup.bat
├── run.bat
└── README.md
```
