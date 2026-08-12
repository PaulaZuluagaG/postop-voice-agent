"use client"

import { useEffect, useRef } from "react"

type Speaker = "agent" | "patient" | null

export function Waveform({ active, speaker }: { active: boolean; speaker: Speaker }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const bars = 48
    const phases = Array.from({ length: bars }, (_, i) => i * 0.35)
    let t = 0

    function resize() {
      const dpr = window.devicePixelRatio || 1
      const { width, height } = canvas.getBoundingClientRect()
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener("resize", resize)

    function draw() {
      const { width, height } = canvas.getBoundingClientRect()
      if (width <= 0 || height <= 0) {
        rafRef.current = requestAnimationFrame(draw)
        return
      }

      ctx.clearRect(0, 0, width, height)

      const mid = height / 2
      const gap = 3
      const available = width - gap * (bars - 1)
      if (available <= 0) {
        rafRef.current = requestAnimationFrame(draw)
        return
      }
      const barWidth = available / bars

      // Color reflects who is speaking. Indigo for agent, sky for patient.
      const color =
        speaker === "patient"
          ? "oklch(0.685 0.15 237.3)"
          : "oklch(0.511 0.222 276.9)"

      for (let i = 0; i < bars; i++) {
        const x = i * (barWidth + gap)
        let amp: number
        if (active) {
          // Simulated audio activity — replace with real analyser data from
          // the WebSocket audio stream (see dashboard for the socket hook).
          const envelope = Math.sin((i / bars) * Math.PI)
          amp =
            (0.25 +
              0.75 *
                Math.abs(Math.sin(t * 0.12 + phases[i]) * Math.cos(t * 0.05 + i))) *
            envelope
        } else {
          amp = 0.06 + 0.02 * Math.sin(t * 0.04 + phases[i])
        }
        const barHeight = Math.max(3, amp * (height * 0.9))
        if (barWidth <= 0 || barHeight <= 0) continue
        ctx.fillStyle = color
        ctx.globalAlpha = active ? 0.9 : 0.4
        const r = Math.min(barWidth / 2, barHeight / 2)
        roundRect(ctx, x, mid - barHeight / 2, barWidth, barHeight, r)
        ctx.fill()
      }
      t += 1
      rafRef.current = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      window.removeEventListener("resize", resize)
    }
  }, [active, speaker])

  return (
    <canvas
      ref={canvasRef}
      className="h-20 w-full"
      role="img"
      aria-label={active ? "Actividad de audio en curso" : "Sin actividad de audio"}
    />
  )
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  if (w <= 0 || h <= 0) return
  const radius = Math.max(0, Math.min(r, w / 2, h / 2))
  if (radius === 0) {
    ctx.beginPath()
    ctx.rect(x, y, w, h)
    ctx.closePath()
    return
  }
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.arcTo(x + w, y, x + w, y + h, radius)
  ctx.arcTo(x + w, y + h, x, y + h, radius)
  ctx.arcTo(x, y + h, x, y, radius)
  ctx.arcTo(x, y, x + w, y, radius)
  ctx.closePath()
}
