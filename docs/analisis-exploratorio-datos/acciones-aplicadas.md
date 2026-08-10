# Acciones aplicadas tras el EDA

Este documento describe **qué se implementó** en código y en el dataset para resolver los hallazgos del análisis exploratorio.

---

## Resumen ejecutivo

| Acción EDA | Estado | Implementación |
|------------|--------|----------------|
| Renombrar `breast_cancer` → `cuello uterino` | ✅ Hecho | Script + actualización de `core/scenarios.py` |
| Reclasificar 5 PDFs | ✅ Hecho | 4 movidos a `Otro/`; 1 corregido por el renombre de carpeta |
| OCR en docs escaneados | ✅ Hecho (código) | `knowledge/ingest/pdf_ocr.py` — 12 con señal; 1 crítico bajo mínimo ingest |
| Limpiar 15 docs con alto junk | ✅ Hecho (código) | `knowledge/ingest/text_cleaner.py` — se aplica en cada ingestión |

---

## 1. Renombrar carpeta de cuello uterino

**Antes:** `dataset/textos/breast_cancer/` (19 PDFs)
**Después:** `dataset/textos/cuello uterino/` (19 PDFs)

**Código actualizado:**

- `core/scenarios.py` — `CERVICAL_CANCER` apunta a `"cuello uterino"`
- Alias legacy `breast_cancer` → `CERVICAL_CANCER` por compatibilidad

---

## 2. Reclasificar PDFs mal ubicados

Se creó la carpeta `dataset/textos/Otro/` y se movieron **4 documentos**:

| Archivo | Desde | Motivo |
|---------|-------|--------|
| `Establishing the need for clinical follow-up...` | Appendicitis | Seguimiento genérico → Otro |
| `REVISIÓN DE LA LITERATURA SOBRE LAAPENDICITIS...` | Appendicitis | Escaneo sin texto → Otro |
| `CUIDADO ESTANDARIZADO EN EL PACIENTE QUIRÚRGICO...` | cholecystitis | Guía GI general → Otro |
| `Postoperative care for patients undergoing cholecystectomy...` | cholecystitis | Revisión de enfermería → Otro |

**Quinto caso (`cervical-es-patient.pdf`):** El EDA lo marcó como “Otro”, pero es una guía de paciente de cáncer cervical. **No se movió** — quedó en `cuello uterino/` tras el renombre de carpeta.

**Script:** `scripts/remediate_dataset.py` (idempotente; soporta `--dry-run`)

```bash
uv run python scripts/remediate_dataset.py
```

---

## 3. OCR para PDFs escaneados

**Módulo:** `knowledge/ingest/pdf_ocr.py`

**Comportamiento:**

1. Extrae texto nativo de cada página.
2. Si hay imágenes y el texto tiene menos de 80 caracteres, intenta OCR.
3. Usa PyMuPDF (`get_textpage_ocr`) + Tesseract.

**Configuración** (`.env` / `core/config.py`):

```env
OCR_ENABLED=true
OCR_LANGUAGES=spa+eng
OCR_DPI=200
OCR_MIN_CHARS=80
```

**Prerrequisito:**

```bash
brew install tesseract tesseract-lang
```

Si Tesseract no está instalado, el sistema sigue funcionando pero omite OCR y registra un aviso en logs.

**Integración:** `knowledge/ingest/pdf_parser.py` llama a `extract_page_text()` en cada página.

---

## 4. Limpieza de texto basura

**Módulo:** `knowledge/ingest/text_cleaner.py`

**Elimina o reduce:**

- DOIs (`doi:10.xxxx/...`)
- URLs (`https://...`)
- Artefactos PDF (`cid:12345`)
- Referencias bibliográficas (`vol.`, `pp.`, ISSN)
- Puntuación repetida (`...`, `---`)
- Caracteres de reemplazo Unicode

**Integración:**

- `clean_clinical_text()` se aplica al extraer cada página
- `normalize_clinical_text()` en `knowledge/text_utils.py` combina limpieza + normalización

La limpieza se ejecuta **en tiempo de ingestión**, no modifica los PDFs originales. Los 15 documentos con `junk_score ≥ 0.50` se benefician automáticamente al re-ingestar.

---

## 5. Estructura del dataset tras la remediación

```
dataset/textos/
├── Appendicitis/          (22 PDFs)
├── cholecystitis/         (15 PDFs)
├── colorectal cancer/     (25 PDFs)
├── cuello uterino/        (19 PDFs)   ← renombrado
├── total joint replacement/ (22 PDFs)
└── Otro/                  (4 PDFs)    ← nuevo
```

Total: **107 PDFs** (107 nombres únicos; 107 `content_hash` únicos — ver sección 2 del notebook EDA).

---

## 6. Próximos pasos recomendados

1. **Instalar Tesseract** si aún no está disponible en el entorno de ingestión.
2. **Re-ingestar el corpus** para aplicar OCR y limpieza en Qdrant:

   ```bash
   postop-ingest --recreate
   ```

3. **Validar** con una llamada de prueba por escenario (`scripts/chat_demo.py` o registro de paciente).

4. **Re-ejecutar el notebook EDA** (`notebooks/eda_dataset_textos.ipynb`) para confirmar la mejora en `junk_score` y cobertura de texto en escaneos.

---

## 7. Tests

Se añadieron pruebas para la limpieza de texto y se actualizó el mapeo de carpetas:

- `tests/test_text_cleaner.py`
- `tests/test_knowledge.py` — incluye `cuello uterino` y alias `breast_cancer`

Ejecutar:

```bash
uv run pytest
```

(86 tests pasando tras la remediación.)
