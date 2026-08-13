"use client"

import { Mic, PhoneOff, Stethoscope, CalendarDays, User, Home, PhoneCall, ClipboardList } from "lucide-react"

import type { PatientData } from "./intake-form"
import { Transcript } from "./transcript"
import { Waveform } from "./waveform"
import { Button } from "@/components/ui/button"
import { displayDecisionLabel, displayDecisionTone, formatSymptoms, type CallSummary } from "@/lib/call-summary"
import { useVoiceSession } from "@/lib/use-voice-session"

function procedureLabel(patient: PatientData) {
  return patient.procedureLabel || patient.procedure
}

export function PatientDashboard({
  patient,
  onGoHome,
}: {
  patient: PatientData
  onGoHome?: () => void
}) {
  const {
    inCall,
    callEnded,
    connecting,
    speaker,
    messages,
    error,
    callSummary,
    summaryLoading,
    voiceReady,
    readinessDetail,
    readinessLoading,
    startCall,
    endCall,
  } = useVoiceSession(patient)

  const day = patient.postopDay
  const active = inCall || connecting
  const showEndedScreen = callEnded && !inCall && !connecting

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
              {showEndedScreen ? (
                <span className="relative inline-flex size-2 rounded-full bg-muted-foreground/50" />
              ) : (
                <>
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500 opacity-75" />
                  <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
                </>
              )}
            </span>
            <span
              className={`text-xs font-medium ${
                showEndedScreen ? "text-muted-foreground" : "text-emerald-700"
              }`}
            >
              {showEndedScreen ? "Llamada finalizada" : "En línea"}
            </span>
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
            value={day ? `Día ${day}` : "—"}
          />
        </section>

        <section className="flex flex-1 flex-col items-center justify-center gap-8 rounded-3xl border border-border bg-card px-6 py-10 shadow-sm">
          {!voiceReady && !readinessLoading && readinessDetail ? (
            <div className="w-full max-w-md rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-amber-950 text-pretty">
              {readinessDetail}
            </div>
          ) : null}
          {showEndedScreen ? (
            <div className="flex w-full max-w-sm flex-col items-center gap-6 text-center">
              <span className="flex size-20 items-center justify-center rounded-full bg-secondary text-primary">
                <PhoneCall className="size-10" aria-hidden="true" />
              </span>
              <div className="space-y-2">
                <h2 className="text-lg font-semibold text-foreground">Llamada terminada</h2>
                <p className="text-sm leading-relaxed text-muted-foreground text-pretty">
                  Gracias por completar su seguimiento de hoy. Puede revisar la conversación
                  abajo y volver al inicio cuando lo desee.
                </p>
              </div>

              <ClinicalSummaryCard
                patient={patient}
                summary={callSummary}
                loading={summaryLoading}
              />

              <Button type="button" size="lg" className="h-11 px-6" onClick={onGoHome}>
                <Home className="size-4" aria-hidden="true" />
                Volver al inicio
              </Button>
            </div>
          ) : (
            <>
              <div className="text-center">
                <p className="text-sm font-medium text-muted-foreground">
                  {readinessLoading
                    ? "Verificando disponibilidad del agente…"
                    : connecting
                    ? "Conectando con María…"
                    : inCall
                      ? speaker === "agent"
                        ? "María está hablando…"
                        : speaker === "patient"
                          ? "Escuchando al paciente…"
                          : "Llamada en curso"
                      : voiceReady
                        ? "Toca para iniciar tu revisión de hoy"
                        : "Llamadas bloqueadas hasta completar la ingesta"}
                </p>
                {error && (
                  <p className="mt-2 text-sm font-medium text-destructive text-pretty">{error}</p>
                )}
              </div>

              <button
                type="button"
                onClick={inCall ? () => void endCall() : startCall}
                disabled={connecting || readinessLoading || (!inCall && !voiceReady)}
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
            </>
          )}
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

function ClinicalSummaryCard({
  patient,
  summary,
  loading,
}: {
  patient: PatientData
  summary: CallSummary | null
  loading: boolean
}) {
  const procedure = summary?.custom_procedure || patient.procedureLabel || patient.procedure
  const postopDayLabel =
    summary?.postop_day !== undefined ? `Día ${summary.postop_day}` : "—"
  const symptoms = summary ? formatSymptoms(summary.symptoms_reported) : "—"
  const decision = summary ? displayDecisionLabel(summary) : "—"
  const nextStep = summary?.next_steps || "—"

  const decisionTone = summary ? displayDecisionTone(summary) : "border-emerald-200 bg-emerald-50 text-emerald-800"

  return (
    <section className="w-full max-w-md rounded-2xl border border-border bg-card p-4 text-left shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <ClipboardList className="size-4 text-primary" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-foreground">Resumen para su equipo de salud</h3>
      </div>

      {loading && !summary ? (
        <p className="text-sm text-muted-foreground">Generando resumen clínico…</p>
      ) : summary ? (
        <div className="space-y-3 text-sm">
          <SummaryRow label="Procedimiento" value={procedure} />
          <SummaryRow label="Día postop" value={postopDayLabel} />
          <SummaryRow label="Síntomas" value={symptoms} />
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Decisión
            </p>
            <p
              className={`mt-1 inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${decisionTone}`}
            >
              {decision}
            </p>
          </div>
          <SummaryRow label="Próximo paso" value={nextStep} />
          {summary.clinical_summary ? (
            <p className="border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground text-pretty">
              {summary.clinical_summary}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          El resumen clínico no está disponible todavía. Su equipo puede consultarlo en la consola
          de administración.
        </p>
      )}
    </section>
  )
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 leading-snug text-foreground text-pretty">{value}</p>
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
