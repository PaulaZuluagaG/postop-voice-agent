export type CallSummary = {
  call_id: string
  procedure_id: string
  custom_procedure?: string | null
  postop_day: number
  patient_name: string
  patient_id?: string | null
  decision_label: string
  symptoms_reported: Record<string, unknown>
  next_steps: string
  clinical_summary: string
  final_score: number
  sources_used: string[]
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
