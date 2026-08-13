# postop-voice-agent — Agente de voz postoperatorio

Agente de **voz en tiempo real** para seguimiento postoperatorio en español (Colombia). Conversa
con el paciente por WebRTC, consulta guías clínicas (RAG), puntúa severidad con protocolos JSON
y decide si escalar a personal humano.

**Dos superficies funcionales:**

| Superficie | URL (Docker local) | Qué hace |
| ---------- | ------------------ | -------- |
| **App paciente (María)** | http://localhost:3000 | Registro + llamada de voz |
| **Consola admin** | http://localhost:8080 | Subir/listar/eliminar PDFs + ver llamadas |

---

## LLMs y herramientas de voz utilizadas

Esta solución declara explícitamente **dos modelos de lenguaje (LLM)** y el **stack de voz**
con el que se construyó el agente en tiempo real.

### Modelos de lenguaje (LLM)

| # | Modelo | Proveedor / API | Rol en la solución | Variable `.env` |
| - | ------ | --------------- | ------------------ | --------------- |
| **1** | **Meta Llama 3.3 70B Versatile** | [Groq Cloud](https://console.groq.com/) | Conversación multi-turno con el paciente: extrae síntomas, genera JSON estructurado por turno y texto hablable (streaming). | `GROQ_MODEL=llama-3.3-70b-versatile` |
| **2** | **Google Gemini 3.6 Flash** | [Google AI Studio](https://aistudio.google.com/) | Tareas **batch/admin** (no en la llamada de voz): generación de protocolos JSON por procedimiento, validación de PDFs al subir documentos y sugerencia de categoría cuando el admin elige "Otro". | `GEMINI_MODEL=gemini-3.6-flash` |

**Por qué dos LLMs:** Groq ofrece baja latencia para voz en tiempo real; Gemini maneja mejor
contextos largos y JSON estructurado en tareas asíncronas sin competir con la cuota de las llamadas.

**Dónde corre cada uno en código:**

| LLM | Módulo principal |
| --- | ---------------- |
| Groq (Llama 3.3 70B) | `src/agent/llm/groq_client.py`, `src/agent/llm/streaming.py` → `PostOpLLMService` (Pipecat) |
| Gemini 3.6 Flash | `src/knowledge/protocol/gemini_client.py`, `src/agent/llm/document_validator.py`, `src/api/services/procedure_classifier.py` |

### Herramientas de voz (pipeline en tiempo real)

La capa de voz está orquestada con **[Pipecat](https://github.com/pipecat-ai/pipecat)**. Flujo
de una llamada WebRTC:

```
Micrófono (navegador) → WebRTC → Deepgram STT → Groq LLM → Kokoro TTS → WebRTC → altavoz
```

| Componente | Herramienta / modelo | Función | Configuración (`.env`) |
| ---------- | -------------------- | ------- | ---------------------- |
| **Orquestación de voz** | Pipecat | Pipeline STT → LLM → TTS, agregación de turnos, cancelación por interrupción | `src/voice/pipeline.py`, `src/voice/browser.py` |
| **Transporte audio** | Pipecat **Small WebRTC** | Llamada de voz en el navegador (sin telefonía PSTN) | `src/voice/web_server.py` (:7860) |
| **Speech-to-Text (STT)** | **Deepgram Nova-2** (`es`) | Transcripción streaming del paciente | `DEEPGRAM_MODEL=nova-2`, `DEEPGRAM_LANGUAGE=es` |
| **Text-to-Speech (TTS)** | **Kokoro 82M** (local, CPU) | Voz de María; modelo `hexgrad/Kokoro-82M`, voz `ef_dora` | `KOKORO_VOICE=ef_dora`, `KOKORO_LANG_CODE=e` |
| **Detección de voz (VAD)** | **Silero VAD** (Pipecat) | Fin de turno del paciente e interrupciones del agente | Integrado en `SileroVADAnalyzer` |

**Backend de voz:** FastAPI + Pipecat en `backend-voice` (`postop-voice-web`, puerto **7860**).
**Frontend de llamada:** Next.js en `apps/voice-ui/` (puerto **3000**).

### RAG y conocimiento (no son voz, pero alimentan al LLM)

| Componente | Herramienta | Función |
| ---------- | ----------- | ------- |
| Embeddings | IBM Granite `granite-embedding-97m-multilingual-r2` (384d) | Vectorizar chunks clínicos |
| Vector store | Qdrant v1.19 | Búsqueda semántica por procedimiento |
| Corpus | 107 PDFs en `data/textos/` | Evidencia clínica citada en cada turno |

Detalle ampliado de modelos, prompts y configuración: [`docs/proyecto/README.md`](docs/proyecto/README.md).

---

## Levantamiento en ≤15 minutos (compuerta G2)

Sigue **solo este README**, en orden. El cronómetro mide desde `git clone` hasta que las URLs
anteriores responden y el agente está listo para llamadas.

**No cuenta contra los 15 minutos:** las pruebas funcionales del jurado después del arranque.

### Requisitos previos

| Requisito | Versión / nota | Comprobar |
| --------- | -------------- | --------- |
| Docker Engine | 24+ | `docker --version` |
| Docker Compose | v2 | `docker compose version` |
| Git | reciente | `git --version` |
| RAM libre | ~8 GB | Primera build descarga Kokoro + Granite |
| Disco Docker | ≥ 20 GB | Docker Desktop → Settings → Resources |
| Navegador | Chrome o Edge | WebRTC + micrófono |

### API keys obligatorias

Obtén las tres claves **antes** de empezar el cronómetro (crear cuenta gratuita en cada servicio):

| Variable en `.env` | Dónde obtenerla | Para qué |
| ------------------ | --------------- | -------- |
| `GROQ_API_KEY` | https://console.groq.com/ | Conversación del agente (Llama 3.3 70B) |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey | Validación de PDFs + protocolos clínicos |
| `DEEPGRAM_API_KEY` | https://console.deepgram.com/ | Speech-to-Text (Nova-2, español) |

---

### Paso 1 — Clonar el repositorio

```bash
git clone https://github.com/PaulaZuluagaG/postop-voice-agent.git
cd postop-voice-agent
```

Comprueba que el repo trae datos y bootstrap (arranque rápido sin re-ingestar):

```bash
ls data/textos/                          # carpetas con PDFs clínicos
ls bootstrap/protocols/*/protocol.json   # protocolos seed
ls bootstrap/qdrant/*.snapshot           # snapshot Qdrant precalculado
```

---

### Paso 2 — Configurar credenciales (`.env`)

```bash
cp .env.example .env
```

Edita `.env` y reemplaza **como mínimo** estas cinco variables:

```env
GROQ_API_KEY=gsk_tu_clave_groq
GEMINI_API_KEY=AI_tu_clave_gemini
DEEPGRAM_API_KEY=tu_clave_deepgram
ADMIN_TOKEN=elige_un_token_largo_y_secreto
NEXT_PUBLIC_VOICE_API_URL=http://localhost:7860
```

**`ADMIN_TOKEN`:** inventa un valor largo (p. ej. `postop-demo-2026-cambiar-esto`). Lo pegarás
después en http://localhost:8080. Debe coincidir **exactamente** con el valor en `.env`.

**No cambies** `NEXT_PUBLIC_VOICE_API_URL` salvo que cambies también el puerto de voz en Docker.

---

### Paso 3 — Levantar todo el stack (un solo comando)

```bash
chmod +x scripts/docker-eval-up.sh
./scripts/docker-eval-up.sh
```

El script ejecuta, en orden:

1. **Build** de backend + frontends (sin Jupyter).
2. **`docker compose up -d`** — 5 servicios: Qdrant, API admin, voz, frontend paciente, frontend admin.
3. **Bootstrap Qdrant** — restaura el snapshot de `bootstrap/qdrant/`. Si falla, ingesta PDFs con `--skip-protocols`.
4. **Verificación** — comprueba `/api/readiness` del backend de voz.

**Tiempo típico:**

| Escenario | Duración |
| --------- | -------- |
| Primera vez (con snapshot en repo) | **2–10 min** |
| Arranques posteriores (caché Docker) | **1–3 min** |

Al terminar debe aparecer:

```
OK: agente listo para llamadas.

URLs:
  Paciente:  http://localhost:3000
  Admin:     http://localhost:8080
  Voice API: http://localhost:7860/api/readiness
```

Si el script termina con `WARN` en readiness, sigue el [Paso 4](#paso-4--verificar-que-todo-responde) y la tabla de problemas al final.

---

### Paso 4 — Verificar que todo responde

Ejecuta cada comando. Todos deben terminar sin error:

```bash
docker compose ps
curl -sf http://localhost:6333/readyz && echo " → Qdrant OK"
curl -sf http://localhost:8000/openapi.json > /dev/null && echo " → Admin API OK"
curl -sf http://localhost:7860/status && echo ""
curl -sf http://localhost:7860/api/readiness | python3 -m json.tool
curl -sf http://localhost:3000 > /dev/null && echo " → Frontend paciente OK"
curl -sf http://localhost:8080 > /dev/null && echo " → Frontend admin OK"
```

**Resultado esperado de readiness:**

```json
{
  "ready": true,
  "detail": "Listo para llamadas de voz.",
  "indexed_documents": 107,
  "indexed_procedures": ["appendicitis", "..."],
  "missing_protocols": []
}
```

Si `"ready": false`, lee `"detail"` y consulta [Solución de problemas](#solución-de-problemas).

---

### Paso 5 — Acceder a la consola admin

1. Abre **http://localhost:8080**
2. En **Token de administrador**, pega el valor de `ADMIN_TOKEN` de tu `.env`
3. Pulsa **Guardar token**
4. Pestaña **Documentos** → **Actualizar** → debe listar PDFs indexados

**Subir un PDF (hot reload):**

1. Selecciona archivo PDF + tipo de procedimiento (p. ej. `appendicitis`)
2. **Subir e indexar** → espera toast de éxito (~30 s – 2 min)
3. **Actualizar** → el documento aparece en la tabla

---

### Paso 6 — Probar la llamada de voz

1. Abre **http://localhost:3000**
2. Completa el formulario:

   | Campo | Ejemplo |
   | ----- | ------- |
   | Nombre | María González |
   | ID paciente | PAC-001 |
   | Día postoperatorio | Día 1 |
   | Procedimiento | Appendicitis |

3. **Iniciar seguimiento** → el botón **Iniciar llamada** debe estar activo (no gris)
4. **Iniciar llamada** → acepta permiso de **micrófono**
5. Escucha a María (TTS) y responde en voz alta
6. **Finalizar llamada** → aparece resumen de severidad en pantalla
7. En admin → pestaña **Llamadas** → **Actualizar** → la llamada debe aparecer

Trazas en disco: `storage/logs/calls/<uuid>/`

---

### Detener y volver a levantar

```bash
docker compose down          # para servicios; conserva datos
./scripts/docker-eval-up.sh  # levantar de nuevo (sin rebuild si no hubo cambios)
```

Arranque en frío (borra volumen Qdrant; el snapshot se restaura solo):

```bash
docker compose down -v
./scripts/docker-eval-up.sh
```

---

## URLs y accesos (referencia rápida)

| Servicio | URL | Autenticación |
| -------- | --- | ------------- |
| App paciente | http://localhost:3000 | Ninguna |
| Consola admin | http://localhost:8080 | Token = `ADMIN_TOKEN` del `.env` |
| API admin (OpenAPI) | http://localhost:8000/docs | Header `Authorization: Bearer <ADMIN_TOKEN>` |
| Backend voz (readiness) | http://localhost:7860/api/readiness | Ninguna |
| Qdrant REST | http://localhost:6333 | Ninguna (solo local) |

---

## Métricas operativas (rúbrica §5)

Medidas y metodología completa en [`docs/metrics/README.md`](docs/metrics/README.md).
Evidencia JSON: [`docs/metrics/`](docs/metrics/).

### Latencia de respuesta (paciente deja de hablar → empieza audio del agente)

| Escenario | P50 | P95 |
| --------- | ---: | ---: |
| Turno en caliente | **~2,4 s** | **~3,2 s** |
| Primer turno (cold start) | — | **~7,5 s** |

Componentes medidos (turno en caliente): RAG warm P50 **37 ms** · Groq LLM **600–1 200 ms** · Kokoro TTFB **1 071 ms** · Deepgram STT post-utterance **~250 ms** (referencia).

Regenerar benchmarks:

```bash
uv run postop-call-metrics --retrieval-only --output docs/metrics/rag-latency.json
uv run python scripts/benchmark_kokoro_tts.py
```

### Consumo por turno y por llamada (~5 turnos)

| Métrica | Por turno | Por llamada |
| ------- | -------: | ----------: |
| Tokens entrada | ~3 200 | ~16 000 |
| Tokens salida | ~220 | ~1 100 |
| Invocaciones LLM (Groq) | 1 | ~5 |
| Consultas RAG (Qdrant) | 1 | ~6 (incl. apertura) |

### Costo estimado por llamada (extrapolación API producción)

| Concepto | USD |
| -------- | ---: |
| Groq (tokens) | ~0,011 |
| Deepgram (~4 min STT) | ~0,023 |
| **Total** | **~0,034** |

Kokoro TTS y embeddings Granite corren local → USD 0.

---

## Solución de problemas

| Síntoma | Qué hacer |
| ------- | --------- |
| `ERROR: falta .env` | `cp .env.example .env` y configura las API keys |
| `"ready": false` — sin documentos | Re-ejecuta `./scripts/docker-eval-up.sh` |
| `"ready": false` — faltan protocolos | `cp -a bootstrap/protocols/. storage/protocols/` y `docker compose restart backend-voice` |
| Admin: token inválido | Verifica que `ADMIN_TOKEN` en `.env` = token pegado en http://localhost:8080; `docker compose restart backend-api` |
| Botón de llamada deshabilitado | `curl -sf http://localhost:7860/api/readiness \| python3 -m json.tool` → sigue `"detail"` |
| WebRTC / voz no conecta | Confirma `NEXT_PUBLIC_VOICE_API_URL=http://localhost:7860` en `.env`; rebuild: `docker compose build frontend-paciente && docker compose up -d frontend-paciente` |
| Groq 429 | Cuota diaria agotada; espera reset o reduce pruebas |
| Build falla por disco | Libera espacio en Docker Desktop; `docker system prune -f` |
| Micrófono bloqueado | Chrome → candado en barra URL → permitir micrófono |

Logs en vivo:

```bash
docker compose logs -f backend-voice frontend-paciente
docker compose logs -f backend-api
```

---

## Qué hace el sistema (resumen)

- **RAG:** 107 PDFs clínicos → chunks en Qdrant (`postop_clinical_knowledge`) → retrieval por turno.
- **Protocolos JSON:** síntomas, umbrales y alertas por procedimiento en `storage/protocols/`.
- **Decisión clínica:** Python aplica scoring determinístico; el LLM conversa y extrae datos, no decide alertas.
- **Hot reload:** admin sube PDF → validación Gemini → reindex Qdrant → regenera protocolo.
- **Trazabilidad:** cada llamada en `storage/logs/calls/{call_id}/`.

Diagramas: [`docs/arquitectura/README.md`](docs/arquitectura/README.md)

---

## Documentación adicional

| Tema | Enlace |
| ---- | ------ |
| Informe completo (prompts, config, capturas) | [`docs/proyecto/README.md`](docs/proyecto/README.md) |
| Docker (detalle técnico) | [`docs/docker-guia.md`](docs/docker-guia.md) |
| Rúbrica de evaluación | [`docs/rubrica-evaluacion.md`](docs/rubrica-evaluacion.md) |
| Stack permitido | [`docs/stack-tecnico.md`](docs/stack-tecnico.md) |
| Datos del reto (`data/`) | [`docs/analisis-exploratorio-datos/hallazgos.md`](docs/analisis-exploratorio-datos/hallazgos.md) |

---

## Licencia y avisos

Código y datos sintéticos: licencia MIT ([`LICENSE`](LICENSE)).

Los PDFs de `data/textos/` son obra de sus autores; se incluyen solo como material de referencia
del reto. Los datos clínicos son **sintéticos** y no tienen validez clínica real.

**Contacto:** [communications@sourcemeridian.com](mailto:communications@sourcemeridian.com)

**Video (entregable 04 — argumentación de la solución y demostración en funcionamiento):** https://drive.google.com/file/d/1llsF-i63V-bBC8oJjVONnwMYzFCX5CIe/view?usp=sharing
