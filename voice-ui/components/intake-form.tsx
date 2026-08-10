"use client"

import { useEffect, useMemo, useState } from "react"
import { HeartPulse, ChevronDown, ArrowRight, Loader2 } from "lucide-react"

import { fetchProcedureOptions, type ProcedureOption } from "@/lib/voice-api"

export type PatientData = {
  name: string
  patientId: string
  surgeryDate: string
  procedure: string
  procedureLabel: string
}

export function IntakeForm({ onStart }: { onStart: (data: PatientData) => void }) {
  const [form, setForm] = useState<PatientData>({
    name: "",
    patientId: "",
    surgeryDate: "",
    procedure: "",
    procedureLabel: "",
  })
  const [errors, setErrors] = useState<Partial<Record<keyof PatientData, boolean>>>({})
  const [procedures, setProcedures] = useState<ProcedureOption[]>([])
  const [loadingProcedures, setLoadingProcedures] = useState(true)
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

  const isComplete = useMemo(
    () =>
      form.name.trim() &&
      form.patientId.trim() &&
      form.surgeryDate.trim() &&
      form.procedure.trim(),
    [form],
  )

  function update<K extends keyof PatientData>(key: K, value: PatientData[K]) {
    setForm((f) => ({ ...f, [key]: value }))
    setErrors((e) => ({ ...e, [key]: false }))
  }

  function updateProcedure(value: string) {
    const label = procedures.find((option) => option.value === value)?.label ?? value
    setForm((f) => ({ ...f, procedure: value, procedureLabel: label }))
    setErrors((e) => ({ ...e, procedure: false }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const next: Partial<Record<keyof PatientData, boolean>> = {}
    ;(Object.keys(form) as (keyof PatientData)[]).forEach((k) => {
      if (!form[k].trim()) next[k] = true
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

        <Field label="Fecha de cirugía" htmlFor="surgeryDate" error={errors.surgeryDate}>
          <input
            id="surgeryDate"
            type="date"
            value={form.surgeryDate}
            onChange={(e) => update("surgeryDate", e.target.value)}
            max={new Date().toISOString().split("T")[0]}
            className="input-base"
          />
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
