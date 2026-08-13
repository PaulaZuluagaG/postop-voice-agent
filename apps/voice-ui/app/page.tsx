"use client"

import { useState } from "react"
import { IntakeForm, type PatientData } from "@/components/intake-form"
import { PatientDashboard } from "@/components/patient-dashboard"

export default function Page() {
  const [patient, setPatient] = useState<PatientData | null>(null)

  return (
    <div className="mx-auto min-h-dvh w-full max-w-md bg-background">
      {patient ? (
        <PatientDashboard patient={patient} onGoHome={() => setPatient(null)} />
      ) : (
        <IntakeForm onStart={setPatient} />
      )}
    </div>
  )
}
