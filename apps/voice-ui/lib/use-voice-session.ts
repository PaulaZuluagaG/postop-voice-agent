"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js"
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport"

import type { PatientData } from "@/components/intake-form"
import type { Message } from "@/components/transcript"
import type { CallSummary } from "@/lib/call-summary"
import { VOICE_API_URL } from "@/lib/voice-api"

type Speaker = "agent" | "patient" | null

const SUMMARY_POLL_ATTEMPTS = 12
const SUMMARY_POLL_DELAY_MS = 500

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function fetchCallSummary(sessionId: string): Promise<CallSummary | null> {
  for (let attempt = 0; attempt < SUMMARY_POLL_ATTEMPTS; attempt += 1) {
    const response = await fetch(`${VOICE_API_URL}/sessions/${sessionId}/summary`, {
      method: "GET",
      headers: { Accept: "application/json" },
    })
    if (response.ok) {
      return (await response.json()) as CallSummary
    }
    if (response.status !== 404) {
      return null
    }
    await sleep(SUMMARY_POLL_DELAY_MS)
  }
  return null
}

export function useVoiceSession(patient: PatientData) {
  const clientRef = useRef<PipecatClient | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const botBufferRef = useRef("")

  const [inCall, setInCall] = useState(false)
  const [callEnded, setCallEnded] = useState(false)
  const [speaker, setSpeaker] = useState<Speaker>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [callSummary, setCallSummary] = useState<CallSummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)

  const appendMessage = useCallback((role: "agent" | "patient", text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role, text: trimmed }])
  }, [])

  const cleanupAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.srcObject = null
      audioRef.current.remove()
      audioRef.current = null
    }
  }, [])

  const loadSummary = useCallback(async (sessionId: string) => {
    setSummaryLoading(true)
    try {
      const summary = await fetchCallSummary(sessionId)
      setCallSummary(summary)
    } finally {
      setSummaryLoading(false)
    }
  }, [])

  const endCall = useCallback(
    async (options?: { ended?: boolean }) => {
      setConnecting(false)
      setSpeaker(null)
      botBufferRef.current = ""
      cleanupAudio()
      const client = clientRef.current
      const sessionId = sessionIdRef.current
      clientRef.current = null
      if (client) {
        try {
          await client.disconnect()
        } catch {
          // Ignore teardown errors after a dropped connection.
        }
      }
      setInCall(false)
      if (options?.ended !== false) {
        setCallEnded(true)
        if (sessionId) {
          void loadSummary(sessionId)
        }
      }
    },
    [cleanupAudio, loadSummary],
  )

  const startCall = useCallback(async () => {
    if (connecting || inCall) return

    setConnecting(true)
    setError(null)
    setCallEnded(false)
    setCallSummary(null)
    setSummaryLoading(false)
    setMessages([])
    botBufferRef.current = ""
    sessionIdRef.current = null

    const client = new PipecatClient({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onBotStarted: (response) => {
          const payload = response as { sessionId?: string }
          if (payload.sessionId) {
            sessionIdRef.current = payload.sessionId
          }
        },
        onConnected: () => {
          setInCall(true)
          setConnecting(false)
        },
        onDisconnected: () => {
          void endCall({ ended: true })
        },
        onUserStartedSpeaking: () => setSpeaker("patient"),
        onUserStoppedSpeaking: () => setSpeaker(null),
        onBotStartedSpeaking: () => {
          setSpeaker("agent")
        },
        onBotStoppedSpeaking: () => {
          setSpeaker(null)
        },
        onBotLlmStarted: () => {
          botBufferRef.current = ""
        },
        onBotLlmText: (data) => {
          botBufferRef.current += data.text
        },
        onBotLlmStopped: () => {
          if (botBufferRef.current.trim()) {
            appendMessage("agent", botBufferRef.current)
            botBufferRef.current = ""
          }
        },
        onUserTranscript: (data) => {
          if (data.final) {
            appendMessage("patient", data.text)
          }
        },
        onError: (err) => {
          setError(typeof err === "string" ? err : "Error en la llamada de voz.")
          setConnecting(false)
        },
      },
    })

    client.on(RTVIEvent.TrackStarted, (track, participant) => {
      if (participant?.local || track.kind !== "audio") return
      cleanupAudio()
      const audio = document.createElement("audio")
      audio.autoplay = true
      audio.srcObject = new MediaStream([track])
      document.body.appendChild(audio)
      audioRef.current = audio
    })

    clientRef.current = client

    try {
      await client.startBotAndConnect({
        endpoint: `${VOICE_API_URL}/start`,
        requestData: {
          transport: "webrtc",
          enableDefaultIceServers: true,
          body: patient,
        },
      })
    } catch (err) {
      clientRef.current = null
      sessionIdRef.current = null
      setConnecting(false)
      setError(
        err instanceof Error ? err.message : "No se pudo conectar con el agente de voz.",
      )
    }
  }, [appendMessage, cleanupAudio, connecting, endCall, inCall, patient])

  useEffect(() => {
    return () => {
      void endCall({ ended: false })
    }
  }, [endCall])

  return {
    inCall,
    callEnded,
    connecting,
    speaker,
    messages,
    error,
    callSummary,
    summaryLoading,
    startCall,
    endCall,
  }
}
