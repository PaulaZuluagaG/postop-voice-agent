# Métricas operativas

Medición de latencia, consumo y costo del agente de voz postoperatorio.
**Fecha de ejecución:** 2026-08-12 · **Entorno:** macOS, backends en local, Qdrant v1.19 en Docker, corpus bootstrap (3 010 chunks).

Evidencia cruda: [`rag-latency.json`](rag-latency.json), [`kokoro-tts.json`](kokoro-tts.json), [`call-metrics.json`](call-metrics.json).

---

## 1. Cómo se calculan las métricas

### 1.1 Latencia de respuesta (P50 / P95)

**Definición (rúbrica):** milisegundos desde que el paciente **termina de hablar** hasta que **empieza a sonar** el audio del agente.

**Instrumentación en código:**

| Tramo | Medición | Campo en log |
| --- | --- | --- |
| Fin de utterance → inicio pipeline | Deepgram entrega transcripción final → `PostOpUserTurnFrame` | (externo al orquestador) |
| Pipeline → primer audio | `voice_latency_tracker.begin_turn()` → primer chunk Kokoro | `timings.voice_response_ms` |
| Sub-componentes | RAG, Groq, TTS por separado | `retrieval_ms`, `llm_ms`, `tts_ttfb_ms` |

**Procedimiento de benchmark ejecutado:**

1. **RAG** — cinco mensajes de paciente simulados (appendicitis, día 3), misma sesión, embedder con warmup explícito:
   ```bash
   uv run postop-call-metrics --retrieval-only --output docs/metrics/rag-latency.json
   ```
   Percentiles con interpolación lineal sobre `retrieval_ms` (`agent/metrics/aggregation.py`).

2. **Kokoro TTS** — texto clínico de 174 caracteres (saludo + pregunta), modo `SENTENCE` (igual que Pipecat):
   ```bash
   uv run python scripts/benchmark_kokoro_tts.py
   ```
   TTFB = tiempo hasta el primer chunk PCM16 no vacío.

3. **Groq LLM** — no se pudo ejecutar benchmark live el 2026-08-12 (cuota TPD agotada). Rango reportado proviene de `timings.llm_ms` observado en desarrollo y del tiempo total del orquestador menos RAG.

4. **Latencia voz agregada (P50/P95 en caliente)** — suma de componentes medidos en turnos **post-warmup**:
   ```
   P50_voz ≈ STT_post_utterance + P50_RAG_warm + P50_LLM + TTFB_Kokoro
   ```
   STT post-utterance: **250 ms** (referencia publicada Deepgram Nova-2; no re-medido en esta sesión).

### 1.2 Consumo (tokens, invocaciones, RAG)

**Por turno de paciente** — registrado automáticamente en cada `TurnRecord`:

| Métrica | Cálculo |
| --- | --- |
| Tokens entrada / salida | `response.usage` de la API Groq → `llm_usage.prompt_tokens` / `completion_tokens` |
| Invocaciones LLM | Contador fijo **1** por turno (`llm_invocations=1`) |
| Consultas RAG | Contador fijo **1** por turno (`rag_queries=1`; búsqueda en Qdrant) |

**Por llamada** — suma de todos los turnos en `CallSummary.usage` al cerrar (`aggregate_call_usage`).

**Procedimiento previsto (no ejecutado por cuota Groq):**
```bash
uv run postop-call-metrics --runs 2 --output docs/metrics/call-metrics-live.json
```
Dos llamadas simuladas de 5 turnos cada una contra Groq + Qdrant reales.

**Valores de tokens en este documento** — estimación estructural: prompt clínico (~8,6 KB system + user con protocolo, historial y evidencia RAG) ≈ **3 200 tokens in**, JSON de salida ≈ **220 tokens out** por turno. Se extrapola a 5 turnos + apertura (RAG sin LLM).

### 1.3 Costo por llamada

Extrapolación a precios de API de producción (`agent/metrics/cost.py`), asumiendo ejecución local de Kokoro y Granite:

```
costo_groq = (prompt_tokens / 1e6 × 0,59) + (completion_tokens / 1e6 × 0,79)
costo_deepgram = minutos_audio_paciente × 0,0058
costo_total = costo_groq + costo_deepgram
```

Tarifas: Groq Llama 3.3 70B on-demand; Deepgram pay-as-you-go. TTS local = USD 0.

---

## 2. Resultados tras ejecutar los benchmarks

### 2.1 RAG — retrieval (`rag-latency.json`)

| Métrica | Valor |
| --- | ---: |
| Muestras | 5 |
| P50 | **36,6 ms** |
| P95 | **4 148,7 ms** |
| Media | 1 062,7 ms |

Valores individuales (ms): `5175,8` · `40,0` · `34,7` · `26,3` · `36,6`

La primera muestra incluye carga del embedder IBM Granite en CPU; las cuatro restantes son consultas en caliente.

### 2.2 Kokoro TTS (`kokoro-tts.json`)

Texto de prueba: *«Hola Paula, soy María… ¿Cuál es su temperatura corporal actual?»* (174 chars)

| Métrica | Valor |
| --- | ---: |
| TTFB (primer audio) | **1 071 ms** |
| Síntesis completa | 3 146 ms |
| Chunks de audio | 3 |

### 2.3 Latencia de voz — valores reportados

| Escenario | P50 | P95 | Base |
| --- | ---: | ---: | --- |
| Turno en caliente | **~2,4 s** | **~3,2 s** | Componentes medidos + STT ref. |
| Primer turno (cold start) | — | **~7,5 s** | 1.ª query RAG 5,2 s + resto |

Desglose componentes (turno en caliente):

| Componente | Resultado medido |
| --- | ---: |
| Deepgram STT (post-utterance) | ~250 ms (referencia) |
| RAG warm (P50) | 36,6 ms |
| Groq LLM | 600–1 200 ms (rango desarrollo) |
| Kokoro TTFB | 1 071 ms |

### 2.4 Consumo por turno y por llamada

| Métrica | Por turno | Por llamada (~5 turnos) | Fuente |
| --- | ---: | ---: | --- |
| Tokens entrada | ~3 200 | ~16 000 | Estimación de prompt* |
| Tokens salida | ~220 | ~1 100 | Estimación de prompt* |
| Tokens totales | ~3 420 | ~17 100 | Estimación de prompt* |
| Invocaciones LLM | 1 | 5 | Instrumentación |
| Consultas RAG | 1 | 6† | Instrumentación |

\* Pendiente de confirmar con `postop-call-metrics --runs 2` cuando haya cuota Groq.
† Incluye 1 retrieval de apertura (sin llamada LLM).

### 2.5 Costo estimado por llamada

| Componente | USD |
| --- | ---: |
| Groq (17 100 tokens estimados) | 0,0106 |
| Deepgram (~4 min STT) | 0,0232 |
| Kokoro + Granite (local) | 0,00 |
| **Total** | **0,0338** |

---

## 3. Análisis

### 3.1 Latencia

**Cuello de botella principal en caliente: Kokoro TTS (~1,1 s TTFB).** Representa ~45 % del presupuesto de ~2,4 s. Es esperable en CPU local sin GPU; el pipeline compartido (`get_shared_kokoro_pipeline`) evita recargas sucesivas pero no acelera la inferencia fonética.

**Segundo componente: Groq LLM (0,6–1,2 s).** El streaming reduce la percepción de espera porque el TTS empieza antes de cerrar el JSON completo, pero el TTFB de audio sigue ligado al primer token hablable dentro del campo `texto_paciente`.

**RAG en caliente es despreciable (P50 ≈ 37 ms)** tras warmup del embedder. El problema de latencia RAG aparece solo en **arranque frío**: la primera query a 5,2 s domina el P95 global (4,1 s) y puede hacer que el **primer turno de una llamada** supere los 7 s si el backend acaba de reiniciarse. Mitigación implementada: `voice_warmup_on_start` e `ingest_warmup_on_start` precargan Granite al startup.

**Implicación para la demo:** conviene hacer una llamada de prueba (o warmup explícito) antes de grabar; los turnos 2–N deberían sentirse en ~2–3 s, coherente con conversación clínica tolerable.

### 3.2 Consumo

**Una invocación Groq y una consulta RAG por turno** — diseño intencional: el protocolo clínico y la evidencia se inyectan en un único prompt estructurado; no hay reintentos ni cadenas multi-agente.

**~3 400 tokens/turno** es elevado frente a un chatbot genérico, pero acorde a un agente clínico con: system prompt extenso, síntomas pendientes del protocolo JSON, historial compacto, chunks RAG citables y salida JSON con categoría + fuentes. El costo marginal sigue bajo (~USD 0,002/turno en Groq).

**La apertura no consume tokens LLM** (mensaje determinístico desde protocolo + RAG opcional), ahorrando ~3 400 tokens respecto a generar el saludo con Groq.

### 3.3 Costo

**~USD 0,034/llamada** posiciona el agente como viable para triage telefónico masivo frente a una llamada humana. El 69 % del costo extrapolado es **Deepgram STT**, no el LLM — optimizar duración de habla del paciente o usar tier negociado de STT impacta más que cambiar de modelo de lenguaje.

En el reto, la ejecución en tier gratuito (Groq + Gemini batch + Deepgram trial) hace el costo efectivo **USD 0** en desarrollo; las cifras anteriores sirven para proyección de producción.

### 3.4 Limitaciones de esta medición

| Limitación | Impacto |
| --- | --- |
| Cuota Groq TPD agotada el 2026-08-12 | Tokens y `llm_ms` exactos no re-medidos en esta sesión |
| STT no benchmarked localmente | 250 ms es referencia, no medición propia |
| Sin `voice_response_ms` en logs de llamada real aún | P50/P95 voz derivados de componentes; confirmar con `--logs storage/logs/calls` post-demo |
| Entorno local vs Docker eval | Docker en CPU puede añadir 1,5–2× en embeddings y TTS |

**Acción pendiente antes de evaluación:** ejecutar una llamada de voz completa y regenerar:

```bash
uv run postop-call-metrics --logs storage/logs/calls --output docs/metrics/call-metrics-live.json
uv run postop-call-metrics --runs 2 --output docs/metrics/call-metrics-live.json
```
