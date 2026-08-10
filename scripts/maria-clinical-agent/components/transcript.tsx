"use client"

import { useEffect, useRef, useState } from "react"
import { ChevronDown, MessagesSquare } from "lucide-react"

export type Message = {
  id: string
  role: "agent" | "patient"
  text: string
}

export function Transcript({ messages }: { messages: Message[] }) {
  const [open, setOpen] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, open])

  return (
    <section className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2.5">
          <MessagesSquare className="size-5 text-primary" aria-hidden="true" />
          <span className="text-sm font-semibold text-foreground">
            Transcripción en tiempo real
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
            {messages.length}
          </span>
          <ChevronDown
            className={`size-5 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </span>
      </button>

      {open && (
        <div
          ref={scrollRef}
          className="flex max-h-72 flex-col gap-3 overflow-y-auto border-t border-border px-5 py-4"
        >
          {messages.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              La conversación aparecerá aquí cuando inicie la llamada.
            </p>
          ) : (
            messages.map((m) =>
              m.role === "agent" ? (
                <div key={m.id} className="flex flex-col items-start">
                  <span className="mb-1 pl-1 text-xs font-medium text-primary">María</span>
                  <p className="max-w-[85%] rounded-2xl rounded-tl-md bg-accent px-4 py-2.5 text-[0.95rem] leading-relaxed text-accent-foreground">
                    {m.text}
                  </p>
                </div>
              ) : (
                <div key={m.id} className="flex flex-col items-end">
                  <span className="mb-1 pr-1 text-xs font-medium text-muted-foreground">
                    Paciente
                  </span>
                  <p className="max-w-[85%] rounded-2xl rounded-tr-md border border-border bg-secondary px-4 py-2.5 text-[0.95rem] leading-relaxed text-foreground">
                    {m.text}
                  </p>
                </div>
              ),
            )
          )}
        </div>
      )}
    </section>
  )
}
