export type ProcedureOption = {
  value: string
  label: string
}

export const VOICE_API_URL =
  process.env.NEXT_PUBLIC_VOICE_API_URL ?? "http://localhost:7860"

export async function fetchProcedureOptions(): Promise<ProcedureOption[]> {
  const response = await fetch(`${VOICE_API_URL}/api/procedures`, { cache: "no-store" })
  if (!response.ok) {
    throw new Error("No se pudieron cargar los procedimientos.")
  }
  return response.json()
}
