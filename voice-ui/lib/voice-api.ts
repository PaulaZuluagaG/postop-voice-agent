export type ProcedureOption = {
  value: string
  label: string
}

export type RiskFactorOption = {
  id: string
  label: string
}

export const VOICE_API_URL =
  process.env.NEXT_PUBLIC_VOICE_API_URL ?? "http://localhost:7860"

export async function fetchProcedureOptions(): Promise<ProcedureOption[]> {
  const response = await fetch("/api/procedures", {
    method: "GET",
    headers: { Accept: "application/json" },
  })

  if (!response.ok) {
    let message = "No se pudieron cargar los tipos de procedimiento."
    try {
      const body = (await response.json()) as { error?: string }
      if (body.error) message = body.error
    } catch {
      // Keep default message when the proxy returns non-JSON.
    }
    throw new Error(message)
  }

  const payload = (await response.json()) as Array<{ value?: string; label?: string }>
  return payload
    .filter((item) => item.value && item.label)
    .map((item) => ({
      value: item.value as string,
      label: item.label as string,
    }))
}

export async function fetchRiskFactors(procedureId: string): Promise<RiskFactorOption[]> {
  if (!procedureId || procedureId === "other") {
    return []
  }

  const response = await fetch(
    `/api/procedures/${encodeURIComponent(procedureId)}/risk-factors`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
    },
  )

  if (!response.ok) {
    return []
  }

  const payload = (await response.json()) as Array<{ id?: string; label?: string }>
  return payload
    .filter((item) => item.id && item.label)
    .map((item) => ({
      id: item.id as string,
      label: item.label as string,
    }))
}
