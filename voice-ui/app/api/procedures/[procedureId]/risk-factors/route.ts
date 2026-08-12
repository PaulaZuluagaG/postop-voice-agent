import { NextResponse } from "next/server"

const VOICE_API_URL =
  process.env.VOICE_API_URL ??
  process.env.NEXT_PUBLIC_VOICE_API_URL ??
  "http://localhost:7860"

export async function GET(
  _request: Request,
  context: { params: Promise<{ procedureId: string }> },
) {
  const { procedureId } = await context.params

  if (!procedureId || procedureId === "other") {
    return NextResponse.json([])
  }

  try {
    const response = await fetch(
      `${VOICE_API_URL}/api/procedures/${encodeURIComponent(procedureId)}/risk-factors`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      },
    )

    if (!response.ok) {
      return NextResponse.json([])
    }

    const payload = await response.json()
    return NextResponse.json(payload)
  } catch {
    return NextResponse.json([])
  }
}
