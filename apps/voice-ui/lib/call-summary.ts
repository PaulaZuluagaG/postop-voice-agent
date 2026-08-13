export type CallSummary = {
  call_id: string
  procedure_id: string
  custom_procedure?: string | null
  postop_day: number
  patient_name: string
  patient_id?: string | null
  decision_label: string
  alert_triggered?: boolean
  symptoms_reported: Record<string, unknown>
  next_steps: string
  clinical_summary: string
  final_score: number
  sources_used: string[]
}

const ESCALATION_NEXT_STEP_MARKERS = [
  "evaluación presencial",
  "escalar al equipo",
] as const

function isEscalationNextStep(nextSteps: string): boolean {
  const normalized = nextSteps.toLowerCase()
  return ESCALATION_NEXT_STEP_MARKERS.some((marker) => normalized.includes(marker))
}

export function displayDecisionLabel(summary: Pick<CallSummary, "decision_label" | "alert_triggered" | "next_steps">): string {
  if (
    summary.alert_triggered ||
    summary.decision_label.toLowerCase() === "rojo" ||
    isEscalationNextStep(summary.next_steps)
  ) {
    return decisionLabelEs("rojo")
  }
  return decisionLabelEs(summary.decision_label)
}

export function displayDecisionTone(summary: Pick<CallSummary, "decision_label" | "alert_triggered" | "next_steps">): string {
  if (
    summary.alert_triggered ||
    summary.decision_label.toLowerCase() === "rojo" ||
    isEscalationNextStep(summary.next_steps)
  ) {
    return "border-rose-200 bg-rose-50 text-rose-800"
  }
  if (summary.decision_label.toLowerCase() === "amarillo") {
    return "border-amber-200 bg-amber-50 text-amber-900"
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-800"
}

export function decisionLabelEs(label: string): string {
  switch (label.toLowerCase()) {
    case "rojo":
      return "Rojo — escalar hoy"
    case "amarillo":
      return "Amarillo — vigilancia"
    case "verde":
      return "Verde — rutinario"
    default:
      return label
  }
}

export function formatSymptoms(symptoms: Record<string, unknown>): string {
  const entries = Object.entries(symptoms)
  if (entries.length === 0) {
    return "Sin síntomas cuantificados"
  }
  return entries
    .map(([key, value]) => {
      const label = key.replace(/_/g, " ")
      if (typeof value === "boolean") {
        return `${label}: ${value ? "sí" : "no"}`
      }
      return `${label}: ${String(value)}`
    })
    .join(" · ")
}
