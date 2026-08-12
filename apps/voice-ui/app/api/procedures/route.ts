import { NextResponse } from "next/server"

const VOICE_API_URL =
  process.env.VOICE_API_URL ??
  process.env.NEXT_PUBLIC_VOICE_API_URL ??
  "http://localhost:7860"

export async function GET() {
  try {
    const response = await fetch(`${VOICE_API_URL}/api/procedures`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    })

    if (!response.ok) {
      return NextResponse.json(
        { error: "No se pudieron cargar los tipos de procedimiento." },
        { status: 502 },
      )
    }

    const payload = await response.json()
    return NextResponse.json(payload)
  } catch {
    return NextResponse.json(
      {
        error:
          "No se pudo conectar con el servidor de voz. Verifique que postop-voice-web esté en ejecución.",
      },
      { status: 503 },
    )
  }
}
