# Hallazgos del análisis exploratorio

Este documento resume lo que el EDA reveló sobre los PDFs clínicos en `dataset/textos/`. Está pensado para cualquier persona del equipo, sin necesidad de leer el notebook completo.

---

## 1. Panorama general del corpus

| Métrica | Valor |
|---------|-------|
| Total de PDFs | 107 |
| Total de páginas | ~2.098 |
| Carpetas por escenario | 5 (antes de la remediación) |
| Chunks estimados para RAG | ~3.071 |

**Distribución por carpeta (antes de la remediación):**

| Carpeta | PDFs | Escenario clínico real |
|---------|------|------------------------|
| colorectal cancer | 25 | Cáncer colorrectal |
| Appendicitis | 24 | Apendicitis |
| total joint replacement | 22 | Reemplazo articular |
| breast_cancer ⚠️ | 19 | **Cáncer de cuello uterino** (nombre incorrecto) |
| cholecystitis | 17 | Colecistitis |

La carpeta más grande concentra ~23 % de los documentos. Ninguna carpeta está vacía ni es desproporcionadamente pequeña respecto a las demás.

---

## 2. Problema principal: carpeta `breast_cancer`

**Qué vimos:** La carpeta se llamaba `breast_cancer` (cáncer de mama), pero **18 de 19 PDFs hablan de cáncer de cuello uterino** — guías de paciente, protocolos de histerectomía, material en español sobre cérvix, etc.

**Por qué importa:** Si el agente de voz busca información para un paciente de cuello uterino, el RAG filtraba por escenario `cervical_cancer` pero los archivos vivían bajo un nombre que no correspondía. Eso generaba confusión en ingestión, hot reload y mantenimiento.

**Acción recomendada:** Renombrar la carpeta a `cuello uterino`.

---

## 3. PDFs mal clasificados (5 detectados)

Usamos palabras clave en el texto extraído para comparar **carpeta esperada** vs **tema detectado**. Se marcaron 5 documentos:

| Archivo | Carpeta original | Problema |
|---------|------------------|----------|
| `Establishing the need for clinical follow-up...` | Appendicitis | Estudio de seguimiento genérico; el heurístico lo marcó como “Otro” |
| `REVISIÓN DE LA LITERATURA SOBRE LAAPENDICITIS AGUDA PEDIÁTRICA...` | Appendicitis | PDF escaneado, **0 caracteres** extraídos |
| `cervical-es-patient.pdf` | breast_cancer | Guía de paciente cervical; falso positivo del heurístico — **pertenece a cuello uterino** |
| `CUIDADO ESTANDARIZADO EN EL PACIENTE QUIRÚRGICO...` | cholecystitis | Guía GI general, no específica de colecistitis |
| `Postoperative care for patients undergoing cholecystectomy...` | cholecystitis | Revisión de enfermería transversal |

**Interpretación:** No todos los “mal clasificados” son errores graves. `cervical-es-patient.pdf` está bien temáticamente; el problema era la carpeta `breast_cancer`. Los otros cuatro conviene moverlos a `Otro/`.

---

## 4. Documentos escaneados

**Heurística (EDA + ingest):** página con imagen(s) y <80 caracteres de texto nativo extraíble.

| Métrica | Valor | Significado |
|---------|-------|-------------|
| Con señal de escaneo | **12** | ≥1 página con imagen y poco texto nativo |
| Crítico (bajo mínimo ingest) | **1** | No alcanza 200 chars sin OCR |
| Impacto alto (≥2 págs. escaneadas) | **2** | Pérdida relevante de contenido |
| Impacto bajo (solo 1 pág., usualmente portada) | **9** | El cuerpo del documento sí es extraíble |

**Importante:** los **12** no son 12 PDFs completamente escaneados. La mayoría solo tienen la portada como imagen; el RAG puede usar el resto del texto nativo.

**Casos relevantes:**

| Archivo | Carpeta | Escaneo | Chars |
|---------|---------|---------|-------|
| `REVISIÓN DE LA LITERATURA SOBRE LAAPENDICITIS AGUDA PEDIÁTRICA...` | appendicitis | 1/1 págs. | **0** (crítico) |
| `Diagnóstico y tratamiento del paciente con colecistitis aguda...` | cholecystitis | 9/110 págs. | alto impacto |
| `Colon Cancer Surgery and Recovery.pdf` | colorectal-cancer | 2/24 págs. | alto impacto |
| `Acute Appendicitis Evidence Based Medicine Guideline.pdf` | appendicitis | 1/7 págs. | portada |
| Otros 8 PDFs | varias | 1 pág. c/u | portada |

**Impacto:** Sin OCR, el único documento crítico no entra al RAG. Los de impacto alto pierden secciones; los de portada escaneada aportan casi todo su contenido.

---

## 5. Texto basura (`junk_score`)

Medimos la “limpieza” del texto con un puntaje compuesto **0–1** (`junk_score`):

- **< 0.35** — limpio
- **0.35 – 0.50** — ruido moderado
- **≥ 0.50** — ruido alto

| Categoría | Documentos | % del corpus |
|-----------|------------|--------------|
| Limpios | 58 | 54 % |
| Ruido moderado | 34 | 32 % |
| Ruido alto | 15 | 14 % |

**Qué cuenta como basura:** DOIs, URLs, referencias bibliográficas (`vol.`, `pp.`, ISSN), artefactos PDF (`cid:123`), caracteres de reemplazo y repeticiones anómalas.

**Peor caso:** `REVISIÓN DE LA LITERATURA...` — `junk_score = 1.0`, `alpha_ratio = 0.0` (sin texto alfabético porque es escaneo puro).

**Promedio de calidad:** `alpha_ratio` ≈ 0.76 — en general el corpus tiene buena proporción de letras vs. símbolos.

---

## 6. Páginas vacías y documentos cortos

- Algunos PDFs tienen páginas sin texto extraíble (portadas, imágenes).
- El umbral mínimo del sistema es **200 caracteres** por documento (`MIN_DOCUMENT_CHARS`). Los escaneos sin OCR no superan ese umbral y fallan en ingestión.

---

## 7. Idioma y tokens

- Mezcla de documentos en **español** e **inglés** (esperable en material clínico internacional).
- Promedio de tokens por documento varía por escenario; los papers académicos suelen ser más largos que las guías de paciente.

---

## 8. Documentos duplicados

El notebook calcula `content_hash` con el mismo algoritmo que `postop-ingest` (`compute_content_hash`) y busca:

| Tipo | Criterio | Resultado en corpus actual |
|------|----------|----------------------------|
| Nombre repetido | Mismo `file_name` en más de una ruta | 0 grupos |
| Contenido idéntico | Mismo `content_hash` (texto normalizado) | 0 grupos |

**107 PDFs → 107 nombres únicos y 107 hashes únicos** (sin duplicados exactos detectados).

**Limitación:** el EDA extrae texto nativo del PDF sin OCR. Dos copias del mismo documento escaneado podrían no detectarse si ambas tienen poco texto extraíble.

---

## 9. Conclusión del EDA

| Área | Estado | Prioridad |
|------|--------|-----------|
| Volumen y cobertura | ✅ Adecuado | — |
| Nombre de carpeta cuello uterino | ❌ Incorrecto | Alta |
| 4 PDFs en categoría equivocada | ⚠️ Revisar | Media |
| PDFs escaneados | ⚠️ 12 con señal (1 crítico, 2 alto impacto) | Alta |
| Ruido bibliográfico | ⚠️ 15 con junk alto | Media |
| Documentos duplicados | ✅ 0 por nombre y 0 por content_hash | — |

El corpus **sirve para RAG**, pero necesitaba las cuatro acciones descritas en [acciones-aplicadas.md](./acciones-aplicadas.md) antes de una re-ingestión confiable.
