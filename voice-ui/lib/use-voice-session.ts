"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js"
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport"

import type { PatientData } from "@/components/intake-form"
import type { Message } from "@/components/transcript"
import { VOICE_API_URL } from "@/lib/voice-api"

type Speaker = "agent" | "patient" | null

export function useVoiceSession(patient: PatientData) {
  const clientRef = useRef<PipecatClient | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const botBufferRef = useRef("")

  const [inCall, setInCall] = useState(false)
  const [speaker, setSpeaker] = useState<Speaker>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)

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

  const endCall = useCallback(async () => {
    setConnecting(false)
    setSpeaker(null)
    botBufferRef.current = ""
    cleanupAudio()
    const client = clientRef.current
    clientRef.current = null
    if (client) {
      try {
        await client.disconnect()
      } catch {
        // Ignore teardown errors after a dropped connection.
      }
    }
    setInCall(false)
  }, [cleanupAudio])

  const startCall = useCallback(async () => {
    if (connecting || inCall) return

    setConnecting(true)
    setError(null)
    setMessages([])
    botBufferRef.current = ""

    const client = new PipecatClient({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onConnected: () => {
          setInCall(true)
          setConnecting(false)
        },
        onDisconnected: () => {
          void endCall()
        },
        onUserStartedSpeaking: () => setSpeaker("patient"),
        onUserStoppedSpeaking: () => setSpeaker(null),
        onBotStartedSpeaking: () => setSpeaker("agent"),
        onBotStoppedSpeaking: () => {
          if (botBufferRef.current.trim()) {
            appendMessage("agent", botBufferRef.current)
            botBufferRef.current = ""
          }
          setSpeaker(null)
        },
        onUserTranscript: (data) => {
          if (data.final) {
            appendMessage("patient", data.text)
          }
        },
        onBotLlmText: (data) => {
          botBufferRef.current += data.text
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
      setConnecting(false)
      setError(
        err instanceof Error
          ? err.message
          : "No se pudo conectar con el agente de voz.",
      )
    }
  }, [appendMessage, cleanupAudio, connecting, endCall, inCall, patient])

  useEffect(() => {
    return () => {
      void endCall()
    }
  }, [endCall])

  return {
    inCall,
    connecting,
    speaker,
    messages,
    error,
    startCall,
    endCall,
  }
}
