"use client"

import { useEffect, useMemo, useState } from "react"
import { HeartPulse, ChevronDown, ArrowRight, Loader2 } from "lucide-react"

import {
  fetchProcedureOptions,
  fetchRiskFactors,
  type ProcedureOption,
  type RiskFactorOption,
} from "@/lib/voice-api"

export type PatientData = {
  name: string
  patientId: string
  postopDay: number
  procedure: string
  procedureLabel: string
  customProcedure?: string
  comorbidities: string[]
}

export const POSTOP_DAY_OPTIONS = [
  { value: 1, label: "Día 1 — primer día postoperatorio" },
  { value: 3, label: "Día 3 — inicio de recuperación" },
  { value: 7, label: "Día 7 — primera semana" },
  { value: 14, label: "Día 14 — dos semanas" },
] as const

const OTHER_VALUE = "other"

export function IntakeForm({ onStart }: { onStart: (data: PatientData) => void }) {
  const [form, setForm] = useState<PatientData>({
    name: "",
    patientId: "",
    postopDay: 0,
    procedure: "",
    procedureLabel: "",
    customProcedure: "",
    comorbidities: [],
  })
  const [errors, setErrors] = useState<Partial<Record<keyof PatientData, boolean>>>({})
  const [procedures, setProcedures] = useState<ProcedureOption[]>([])
  const [riskFactors, setRiskFactors] = useState<RiskFactorOption[]>([])
  const [loadingProcedures, setLoadingProcedures] = useState(true)
  const [loadingRiskFactors, setLoadingRiskFactors] = useState(false)
  const [procedureError, setProcedureError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchProcedureOptions()
      .then((options) => {
        if (!cancelled) {
          setProcedures(options)
          setProcedureError(null)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setProcedureError(err.message)
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingProcedures(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!form.procedure || form.procedure === OTHER_VALUE) {
      setRiskFactors([])
      setForm((current) => ({ ...current, comorbidities: [] }))
      return
    }

    let cancelled = false
    setLoadingRiskFactors(true)
    fetchRiskFactors(form.procedure)
      .then((options) => {
        if (cancelled) return
        setRiskFactors(options)
        setForm((current) => ({
          ...current,
          comorbidities: current.comorbidities.filter((id) =>
            options.some((option) => option.id === id),
          ),
        }))
      })
      .finally(() => {
        if (!cancelled) setLoadingRiskFactors(false)
      })

    return () => {
      cancelled = true
    }
  }, [form.procedure])

  const comorbiditiesEnabled = useMemo(() => {
    return Boolean(form.procedure) && form.procedure !== OTHER_VALUE && riskFactors.length > 0
  }, [form.procedure, riskFactors.length])

  const comorbiditiesHint = useMemo(() => {
    if (!form.procedure) {
      return "Seleccione un procedimiento para ver comorbilidades disponibles."
    }
    if (form.procedure === OTHER_VALUE) {
      return "No aplica para procedimiento Otro."
    }
    if (loadingRiskFactors) {
      return "Cargando comorbilidades…"
    }
    if (riskFactors.length === 0) {
      return "Este procedimiento no tiene comorbilidades configuradas."
    }
    return "Opcional. Puede seleccionar una o más."
  }, [form.procedure, loadingRiskFactors, riskFactors.length])

  const isComplete = useMemo(() => {
    const base =
      form.name.trim() &&
      form.patientId.trim() &&
      POSTOP_DAY_OPTIONS.some((option) => option.value === form.postopDay) &&
      form.procedure.trim()
    if (!base) return false
    if (form.procedure === OTHER_VALUE) {
      return Boolean(form.customProcedure?.trim())
    }
    return true
  }, [form])

  function update<K extends keyof PatientData>(key: K, value: PatientData[K]) {
    setForm((f) => ({ ...f, [key]: value }))
    setErrors((e) => ({ ...e, [key]: false }))
  }

  function updateProcedure(value: string) {
    const label = procedures.find((option) => option.value === value)?.label ?? value
    setForm((f) => ({
      ...f,
      procedure: value,
      procedureLabel: label,
      customProcedure: value === OTHER_VALUE ? f.customProcedure ?? "" : "",
      comorbidities: [],
    }))
    setErrors((e) => ({ ...e, procedure: false, customProcedure: false }))
  }

  function toggleComorbidity(id: string) {
    if (!comorbiditiesEnabled || loadingRiskFactors) return
    setForm((current) => ({
      ...current,
      comorbidities: current.comorbidities.includes(id)
        ? current.comorbidities.filter((item) => item !== id)
        : [...current.comorbidities, id],
    }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const next: Partial<Record<keyof PatientData, boolean>> = {}
    ;(Object.keys(form) as (keyof PatientData)[]).forEach((k) => {
      if (k === "customProcedure" && form.procedure !== OTHER_VALUE) return
      if (k === "comorbidities") return
      if (k === "postopDay") {
        if (!POSTOP_DAY_OPTIONS.some((option) => option.value === form.postopDay)) {
          next[k] = true
        }
        return
      }
      if (!String(form[k] ?? "").trim()) next[k] = true
    })
    if (Object.keys(next).length > 0) {
      setErrors(next)
      return
    }
    onStart(form)
  }

  return (
    <div className="flex min-h-dvh flex-col justify-center px-6 py-10">
      <header className="mb-8 flex flex-col items-center text-center">
        <span className="mb-4 flex size-16 items-center justify-center rounded-3xl bg-primary text-primary-foreground shadow-lg shadow-primary/20">
          <HeartPulse className="size-8" aria-hidden="true" />
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground text-balance">
          Bienvenido a María
        </h1>
        <p className="mt-2 max-w-xs text-sm leading-relaxed text-muted-foreground text-pretty">
          Tu asistente de voz para el seguimiento postoperatorio. Completa tus datos para comenzar.
        </p>
      </header>

      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5">
        <Field label="Nombre del paciente" htmlFor="name" error={errors.name}>
          <input
            id="name"
            type="text"
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
            placeholder="Ej. Ana Martínez"
            className="input-base"
            autoComplete="name"
          />
        </Field>

        <Field label="ID del paciente" htmlFor="patientId" error={errors.patientId}>
          <input
            id="patientId"
            type="text"
            value={form.patientId}
            onChange={(e) => update("patientId", e.target.value)}
            placeholder="Ej. PAC-00482"
            className="input-base"
          />
        </Field>

        <Field label="Día postoperatorio" htmlFor="postopDay" error={errors.postopDay}>
          <div className="relative">
            <select
              id="postopDay"
              value={form.postopDay || ""}
              onChange={(e) => update("postopDay", Number(e.target.value))}
              className={`input-base appearance-none pr-10 ${form.postopDay ? "" : "text-muted-foreground"}`}
            >
              <option value="" disabled>
                Selecciona el día de seguimiento
              </option>
              {POSTOP_DAY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value} className="text-foreground">
                  {option.label}
                </option>
              ))}
            </select>
            <ChevronDown
              className="pointer-events-none absolute right-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
          </div>
        </Field>

        <Field label="Tipo de procedimiento" htmlFor="procedure" error={errors.procedure}>
          <div className="relative">
            <select
              id="procedure"
              value={form.procedure}
              onChange={(e) => updateProcedure(e.target.value)}
              disabled={loadingProcedures || !!procedureError}
              className={`input-base appearance-none pr-10 ${form.procedure ? "" : "text-muted-foreground"}`}
            >
              <option value="" disabled>
                {loadingProcedures ? "Cargando opciones…" : "Selecciona una opción"}
              </option>
              {procedures.map((option) => (
                <option key={option.value} value={option.value} className="text-foreground">
                  {option.label}
                </option>
              ))}
            </select>
            {loadingProcedures ? (
              <Loader2
                className="pointer-events-none absolute right-4 top-1/2 size-5 -translate-y-1/2 animate-spin text-muted-foreground"
                aria-hidden="true"
              />
            ) : (
              <ChevronDown
                className="pointer-events-none absolute right-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
            )}
          </div>
          {procedureError && (
            <span className="text-xs font-medium text-destructive">{procedureError}</span>
          )}
        </Field>

        {form.procedure === OTHER_VALUE && (
          <Field
            label="Nombre de su procedimiento"
            htmlFor="customProcedure"
            error={errors.customProcedure}
          >
            <input
              id="customProcedure"
              type="text"
              value={form.customProcedure ?? ""}
              onChange={(e) => update("customProcedure", e.target.value)}
              placeholder="Ej. Reparación de hernia"
              className="input-base"
            />
          </Field>
        )}

        <Field label="Comorbilidades" htmlFor="comorbidities">
          <div
            id="comorbidities"
            role="group"
            aria-describedby="comorbidities-hint"
            className={`flex flex-col gap-2 ${!comorbiditiesEnabled || loadingRiskFactors ? "opacity-60" : ""}`}
          >
            {riskFactors.length > 0 ? (
              riskFactors.map((option) => {
                const selected = form.comorbidities.includes(option.id)
                return (
                  <label
                    key={option.id}
                    htmlFor={`comorbidity-${option.id}`}
                    className={`flex cursor-pointer items-center gap-3 rounded-2xl border px-4 py-3 transition-colors ${
                      selected
                        ? "border-primary bg-primary/5"
                        : "border-border bg-card hover:border-primary/40"
                    } ${!comorbiditiesEnabled || loadingRiskFactors ? "cursor-not-allowed" : ""}`}
                  >
                    <input
                      id={`comorbidity-${option.id}`}
                      type="checkbox"
                      checked={selected}
                      disabled={!comorbiditiesEnabled || loadingRiskFactors}
                      onChange={() => toggleComorbidity(option.id)}
                      className="size-4 shrink-0 accent-[var(--primary)]"
                    />
                    <span className="text-sm leading-snug text-foreground">{option.label}</span>
                  </label>
                )
              })
            ) : (
              <p className="rounded-2xl border border-dashed border-border bg-card px-4 py-3 text-sm text-muted-foreground">
                {comorbiditiesHint}
              </p>
            )}
          </div>
          {riskFactors.length > 0 && (
            <span id="comorbidities-hint" className="text-xs text-muted-foreground">
              {comorbiditiesHint}
              {form.comorbidities.length > 0
                ? ` · ${form.comorbidities.length} seleccionada(s)`
                : ""}
            </span>
          )}
        </Field>

        <button
          type="submit"
          disabled={!isComplete || loadingProcedures || !!procedureError}
          className="mt-3 flex items-center justify-center gap-2 rounded-2xl bg-primary px-6 py-4 text-base font-semibold text-primary-foreground shadow-lg shadow-primary/25 transition-colors hover:bg-primary/90 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
        >
          Iniciar
          <ArrowRight className="size-5" aria-hidden="true" />
        </button>
      </form>

      <style jsx>{`
        .input-base {
          width: 100%;
          border-radius: 1rem;
          border: 1px solid var(--border);
          background-color: var(--card);
          padding: 0.875rem 1rem;
          font-size: 1rem;
          color: var(--foreground);
          outline: none;
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .input-base:focus {
          border-color: var(--primary);
          box-shadow: 0 0 0 3px color-mix(in oklch, var(--primary) 18%, transparent);
        }
        .input-base:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .input-base::placeholder {
          color: var(--muted-foreground);
        }
      `}</style>
    </div>
  )
}

function Field({
  label,
  htmlFor,
  error,
  children,
}: {
  label: string
  htmlFor: string
  error?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={htmlFor} className="text-sm font-medium text-foreground">
        {label}
      </label>
      {children}
      {error && (
        <span className="text-xs font-medium text-destructive">Este campo es obligatorio.</span>
      )}
    </div>
  )
}
