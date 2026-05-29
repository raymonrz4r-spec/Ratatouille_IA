# Ratatouille

Extrae recetas automaticamente desde videos de TikTok, Instagram Reels y YouTube usando IA.

## Requisitos

- Python 3.10+
- Node.js 18+
- MySQL 8+ en ejecucion
- FFmpeg local instalado por `setup.bat`
- API key de Groq
- Google OAuth Client ID para iniciar sesion

## Instalacion

Doble click en:

```bat
setup.bat
```

Luego edita `.env` y coloca:

```env
GROQ_API_KEY=tu_api_key_aqui
APP_SECRET=un_secreto_largo_para_firmar_sesiones
GOOGLE_CLIENT_ID=tu_google_oauth_client_id.apps.googleusercontent.com
VITE_GOOGLE_CLIENT_ID=tu_google_oauth_client_id.apps.googleusercontent.com
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=ratatouille
```

La app intenta crear la base de datos `ratatouille` y sus tablas automaticamente al iniciar el backend. Si tu usuario de MySQL no tiene permiso para crear bases de datos, crea la base manualmente y deja ese nombre en `MYSQL_DATABASE`.

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
5. La receta queda guardada en MySQL dentro de la cuenta que inicio sesion.

## Datos guardados

MySQL guarda:

- Usuarios autenticados con Google, identificados por `google_sub`.
- Recetas con titulo, URL original, plataforma, tiempos, porciones y resumen.
- Imagenes de recetas como binario en MySQL, servidas desde `/api/recipes/{id}/image`.
- Ingredientes con su estado de marcado.
- Pasos y notas de la receta.
- Plan de suscripcion por usuario.

No se guardan numeros de tarjeta, CVV ni datos de pago del modal de suscripcion.

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
