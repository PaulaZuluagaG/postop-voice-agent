# Guía Docker — postop-voice-agent

Orquestación completa del sistema con un único `docker-compose.yml`.

## Arquitectura

```mermaid
flowchart LR
  subgraph frontends [Frontends]
    FP[frontend-paciente :3000]
    FA[frontend-admin :8080]
  end

  subgraph backend [Backend Python]
    BA[backend-api :8000]
    BV[backend-voice :7860]
  end

  subgraph data [Datos]
    QD[(qdrant-db :6333)]
    DS[dataset/textos]
    LG[storage/logs]
  end

  JU[jupyter-notebook :8888]

  FP -->|WebRTC + REST| BV
  FP -->|SSR proxy /api/*| BV
  FA -->|/admin/*| BA
  BA --> QD
  BV --> QD
  BA --> DS
  BV --> DS
  BA --> LG
  BV --> LG
  JU --> DS
  JU --> QD
```

| Servicio | Puerto host | Tecnología | Rol |
| -------- | ----------- | ---------- | --- |
| `qdrant-db` | 6333 | Qdrant v1.19 | Base vectorial (embeddings IBM Granite) |
| `backend-api` | 8000 | FastAPI + uv | API admin, ingest hot-reload, trazas |
| `backend-voice` | 7860 | Pipecat + Groq + Deepgram + Kokoro | WebRTC streaming de voz |
| `frontend-paciente` | 3000 | Next.js 16 | Registro + llamada de voz (María) |
| `frontend-admin` | 8080 | Nginx + HTML/JS | Consola de documentos clínicos |
| `jupyter-notebook` | 8888 | Jupyter Lab | EDA sobre `dataset/textos` y datos `.xlsx` |

> **Nota:** La consola admin es una SPA estática (`apps/admin-ui/`), no Next.js. Se sirve con Nginx y delega `/admin/*` al backend FastAPI.

## Requisitos previos

- Docker Engine 24+ y Docker Compose v2
- ~8 GB RAM libres (PyTorch + Kokoro + Granite en la imagen backend)
- Archivo `.env` con API keys válidas

## 1. Configurar entorno

```bash
cp .env.example .env
```

Edita `.env` y define al menos:

```env
GROQ_API_KEY=...
GEMINI_API_KEY=...
DEEPGRAM_API_KEY=...
ADMIN_TOKEN=un_token_seguro

QDRANT_HOST=qdrant-db
TEXTOS_DIR=dataset/textos
NEXT_PUBLIC_VOICE_API_URL=http://localhost:7860
VOICE_WEB_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

## 2. Construir e iniciar

```bash
docker compose build
docker compose up -d
```

La primera build descarga Kokoro, IBM Granite y dependencias PyTorch (~10–20 min según red).

Verifica salud:

```bash
docker compose ps
curl -sf http://localhost:6333/readyz && echo " Qdrant OK"
curl -sf http://localhost:8000/openapi.json > /dev/null && echo " Admin API OK"
curl -sf http://localhost:7860/status && echo " Voice Web OK"
curl -sf http://localhost:3000 > /dev/null && echo " Frontend paciente OK"
curl -sf http://localhost:8080 > /dev/null && echo " Frontend admin OK"
```

## 3. Ingesta inicial del corpus RAG y protocolos

En el primer arranque, Qdrant y `./storage/protocols/` están **vacíos**. Los protocolos
clínicos se generan a partir de los PDFs indexados (RAG + Gemini); no vienen precargados.

Solo la primera vez (o tras borrar volúmenes):

```bash
docker compose --profile init run --rm ingest-init
```

Alternativa manual:

```bash
docker compose exec backend-api postop-ingest --recreate
```

## 4. Probar el sistema de punta a punta

1. **Consola admin** → http://localhost:8080
   - Pega el `ADMIN_TOKEN` configurado en `.env`
   - Sube un PDF; debe indexarse en Qdrant vía `backend-api`

2. **App paciente** → http://localhost:3000
   - Completa el formulario de registro
   - **Antes de `ingest-init`**, el botón de llamada permanece deshabilitado
   - Tras la ingesta, inicia la llamada de voz (micrófono del navegador)
   - WebRTC negocia contra `http://localhost:7860` (Pipecat Small WebRTC)

3. **Jupyter EDA** → http://localhost:8888
   - Abre `eda_dataset_textos.ipynb`
   - Notebooks persisten en `./notebooks/`

4. **Trazas de llamadas** → `./storage/logs/calls/<call_id>/`
5. **Protocolos clínicos** → `./storage/protocols/<procedimiento>/protocol.json`

## Volúmenes persistentes

| Volumen / bind mount | Contenido |
| -------------------- | --------- |
| `qdrant_data` | Índice vectorial Qdrant |
| `hf_cache` | Caché Hugging Face (Granite + Kokoro) |
| `./dataset/textos` | PDFs clínicos compartidos (admin sube, backend ingesta) |
| `./storage/protocols` | Protocolos clínicos generados por `ingest-init` o upload admin (vacío al primer arranque) |
| `./storage/logs` | Eventos y resúmenes de llamadas |
| `./notebooks` | Notebooks Jupyter |
| `./data` | Datasets `.xlsx` para análisis |

## WebSockets / WebRTC (Pipecat)

- El navegador **no** puede usar hostnames Docker internos (`backend-voice`).
- `NEXT_PUBLIC_VOICE_API_URL` debe apuntar al host donde el usuario abre el frontend (`http://localhost:7860` en local).
- `VOICE_API_URL=http://backend-voice:7860` (solo server-side en Next.js) proxya `/api/procedures`.
- CORS del servidor de voz se controla con `VOICE_WEB_CORS_ORIGINS`.
- Puertos UDP adicionales no son necesarios con Small WebRTC (ICE/STUN vía Google).

## Comandos útiles

```bash
# Logs en vivo
docker compose logs -f backend-voice frontend-paciente

# Regenerar protocolos clínicos
docker compose exec backend-api postop-protocols

# Parar y conservar datos
docker compose down

# Parar y borrar índice Qdrant (re-ingesta necesaria)
docker compose down -v
```

## Solución de problemas

| Síntoma | Causa probable | Acción |
| ------- | -------------- | ------ |
| Voice UI no conecta | `NEXT_PUBLIC_VOICE_API_URL` incorrecta | Debe ser `http://localhost:7860`, reconstruir frontend |
| Admin 502 al subir PDF | Cuota Gemini o Qdrant caído | Revisar logs: `docker compose logs backend-api` |
| Ingesta vacía | `dataset/textos` sin PDFs | Verificar bind mount y ejecutar `ingest-init` |
| OCR no funciona | Tesseract ausente | Ya incluido en imagen backend (`tesseract-ocr-spa`) |
| Protocolos vacíos tras `up` | Comportamiento esperado | Ejecutar `ingest-init`; los protocolos se crean al indexar PDFs |
| Protocolos perdidos tras rebuild | Volumen no montado | Verificar `./storage/protocols`; regenerar con `ingest-init` o `postop-protocols` |
