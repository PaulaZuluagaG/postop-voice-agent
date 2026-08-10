"use client"

import { Mic, PhoneOff, Stethoscope, CalendarDays, User } from "lucide-react"

import type { PatientData } from "./intake-form"
import { Transcript } from "./transcript"
import { Waveform } from "./waveform"
import { useVoiceSession } from "@/lib/use-voice-session"

function formatDate(iso: string) {
  if (!iso) return "—"
  const d = new Date(iso + "T00:00:00")
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" })
}

function postopDay(iso: string) {
  if (!iso) return null
  const surgery = new Date(iso + "T00:00:00")
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.floor((today.getTime() - surgery.getTime()) / 86_400_000)
  return diff >= 0 ? diff : null
}

function procedureLabel(patient: PatientData) {
  return patient.procedureLabel || patient.procedure
}

export function PatientDashboard({ patient }: { patient: PatientData }) {
  const { inCall, connecting, speaker, messages, error, startCall, endCall } =
    useVoiceSession(patient)

  const day = postopDay(patient.surgeryDate)
  const active = inCall || connecting

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-10 border-b border-border bg-card/90 px-5 py-4 backdrop-blur">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
              <Stethoscope className="size-5" aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-base font-semibold leading-tight text-foreground">
                Asistente de Voz Postoperatorio
              </h1>
              <p className="text-xs text-muted-foreground">María · Clínica de Seguimiento</p>
            </div>
          </div>
          <span className="flex items-center gap-1.5 rounded-full bg-secondary px-2.5 py-1">
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
            </span>
            <span className="text-xs font-medium text-emerald-700">En línea</span>
          </span>
        </div>
      </header>

      <main className="flex flex-1 flex-col gap-6 px-5 py-6">
        <section className="grid grid-cols-3 gap-2 rounded-3xl border border-border bg-card p-2 shadow-sm">
          <StatusItem icon={<User className="size-4" />} label="Paciente" value={patient.name} />
          <StatusItem
            icon={<Stethoscope className="size-4" />}
            label="Cirugía"
            value={procedureLabel(patient)}
          />
          <StatusItem
            icon={<CalendarDays className="size-4" />}
            label="Día postop"
            value={day !== null ? `Día ${day}` : formatDate(patient.surgeryDate)}
          />
        </section>

        <section className="flex flex-1 flex-col items-center justify-center gap-8 rounded-3xl border border-border bg-card px-6 py-10 shadow-sm">
          <div className="text-center">
            <p className="text-sm font-medium text-muted-foreground">
              {connecting
                ? "Conectando con María…"
                : inCall
                  ? speaker === "agent"
                    ? "María está hablando…"
                    : speaker === "patient"
                      ? "Escuchando al paciente…"
                      : "Llamada en curso"
                  : "Toca para iniciar tu revisión de hoy"}
            </p>
            {error && (
              <p className="mt-2 text-sm font-medium text-destructive text-pretty">{error}</p>
            )}
          </div>

          <button
            type="button"
            onClick={inCall ? endCall : startCall}
            disabled={connecting}
            aria-label={inCall ? "Finalizar llamada" : "Iniciar llamada"}
            className={`relative flex size-40 items-center justify-center rounded-full text-primary-foreground shadow-xl transition-all active:scale-95 disabled:cursor-wait disabled:opacity-80 ${
              inCall
                ? "bg-destructive shadow-destructive/30 hover:bg-destructive/90"
                : "bg-primary shadow-primary/30 hover:bg-primary/90"
            }`}
          >
            {inCall && (
              <>
                <span className="absolute inset-0 animate-ping rounded-full bg-destructive/30" />
                <span className="absolute -inset-3 animate-pulse rounded-full border-2 border-destructive/20" />
              </>
            )}
            <span className="relative flex flex-col items-center gap-2">
              {inCall ? (
                <PhoneOff className="size-11" aria-hidden="true" />
              ) : (
                <Mic className="size-11" aria-hidden="true" />
              )}
              <span className="text-sm font-semibold">
                {connecting ? "Conectando…" : inCall ? "Finalizar" : "Iniciar"}
              </span>
            </span>
          </button>

          <div className="w-full max-w-sm">
            <Waveform active={active} speaker={speaker} />
          </div>
        </section>

        <Transcript messages={messages} />

        <p className="pb-2 text-center text-xs leading-relaxed text-muted-foreground text-pretty">
          En caso de emergencia o dolor intenso, contacta de inmediato a tu equipo médico o llama a
          urgencias.
        </p>
      </main>
    </div>
  )
}

function StatusItem({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-2xl px-2 py-3 text-center">
      <span className="flex items-center gap-1 text-muted-foreground">{icon}</span>
      <span className="text-[0.7rem] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="line-clamp-2 text-sm font-semibold leading-tight text-foreground">
        {value}
      </span>
    </div>
  )
}
