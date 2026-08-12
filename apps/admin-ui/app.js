/** Clinical knowledge admin console — wired to FastAPI /admin routes. */

const TOKEN_KEY = "postop_admin_token";

/** @type {Array<{source_id: string, procedure_type: string, file_name: string}>} */
let docs = [];
/** @type {{source_id: string, procedure_type: string, file_name: string} | null} */
let confirmTarget = null;
/** @type {{temp_id: string, file_name: string, procedure_label: string} | null} */
let pendingProcedureUpload = null;
let loadingDocs = false;
let uploading = false;
let confirmingProcedure = false;

/** @type {Array<{call_id: string, patient_name: string, procedure_id?: string, postop_day?: number, decision_label: string, closed_reason?: string, closed_at?: string}>} */
let calls = [];
let loadingCalls = false;
let activeTab = "documents";
let isAuthenticated = false;

const tokenInput = document.getElementById("admin-token");
const tokenSavedMsg = document.getElementById("token-saved-msg");
const tokenErrorMsg = document.getElementById("token-error-msg");
const saveTokenBtn = document.getElementById("save-token-btn");
const refreshBtn = document.getElementById("refresh-btn");
const refreshIcon = document.getElementById("refresh-icon");
const refreshLabel = document.getElementById("refresh-label");
const docsBody = document.getElementById("docs-body");
const docCount = document.getElementById("doc-count");
const docFile = document.getElementById("doc-file");
const docType = document.getElementById("doc-type");
const uploadBtn = document.getElementById("upload-btn");
const uploadHint = document.getElementById("upload-hint");
const confirmDialog = document.getElementById("confirm-dialog");
const confirmMessage = document.getElementById("confirm-message");
const confirmCancel = document.getElementById("confirm-cancel");
const confirmDelete = document.getElementById("confirm-delete");
const procedureDialog = document.getElementById("procedure-dialog");
const suggestedProcedure = document.getElementById("suggested-procedure");
const suggestedProcedureLabel = document.getElementById("suggested-procedure-label");
const manualProcedure = document.getElementById("manual-procedure");
const manualProcedureLabel = document.getElementById("manual-procedure-label");
const procedureCancel = document.getElementById("procedure-cancel");
const procedureConfirm = document.getElementById("procedure-confirm");
const procedureProcessing = document.getElementById("procedure-processing");
const toastArea = document.getElementById("toast-area");
const tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
const panelDocuments = document.getElementById("panel-documents");
const panelCalls = document.getElementById("panel-calls");
const callsBody = document.getElementById("calls-body");
const callCount = document.getElementById("call-count");
const refreshCallsBtn = document.getElementById("refresh-calls-btn");
const refreshCallsIcon = document.getElementById("refresh-calls-icon");
const refreshCallsLabel = document.getElementById("refresh-calls-label");
const callDetailDialog = document.getElementById("call-detail-dialog");
const callDetailContent = document.getElementById("call-detail-content");
const callDetailClose = document.getElementById("call-detail-close");

function decisionBadgeClass(label) {
  const value = String(label || "").toLowerCase();
  if (value === "rojo") return "bg-rose-50 text-rose-700";
  if (value === "amarillo") return "bg-amber-50 text-amber-800";
  return "bg-emerald-50 text-emerald-700";
}

function setAuthenticated(value) {
  isAuthenticated = value;
  updateAuthUI();
  if (!value) {
    docs = [];
    calls = [];
    renderDocs();
    renderCalls();
    docType.innerHTML = '<option value="" disabled selected>Selecciona un tipo…</option>';
  }
}

function updateAuthUI() {
  const authed = isAuthenticated;
  refreshBtn.disabled = !authed || loadingDocs;
  refreshCallsBtn.disabled = !authed || loadingCalls;
  docFile.disabled = !authed;
  docType.disabled = !authed;
  panelDocuments.classList.toggle("opacity-60", !authed);
  panelCalls.classList.toggle("opacity-60", !authed);
  updateUploadState();
}

function showTokenStatus({ saved = false, error = false } = {}) {
  tokenSavedMsg.classList.toggle("hidden", !saved);
  tokenErrorMsg.classList.toggle("hidden", !error);
}

async function validateAndActivateToken(token) {
  setToken(token);
  try {
    await apiFetch("/admin/documents");
    setAuthenticated(true);
    showTokenStatus({ saved: true, error: false });
    return true;
  } catch (error) {
    sessionStorage.removeItem(TOKEN_KEY);
    setAuthenticated(false);
    showTokenStatus({ saved: false, error: true });
    pushToast("error", error.message || "Token de administrador inválido.");
    return false;
  }
}

function switchTab(tab) {
  activeTab = tab;
  for (const button of tabButtons) {
    const selected = button.dataset.tab === tab;
    button.classList.toggle("border-slate-200", selected);
    button.classList.toggle("border-b-0", selected);
    button.classList.toggle("bg-white", selected);
    button.classList.toggle("text-teal-700", selected);
    button.classList.toggle("border-transparent", !selected);
    button.classList.toggle("text-slate-500", !selected);
  }
  panelDocuments.classList.toggle("hidden", tab !== "documents");
  panelCalls.classList.toggle("hidden", tab !== "calls");
  if (tab === "calls" && isAuthenticated) {
    refreshCalls();
  }
}

function renderCalls() {
  callCount.textContent = isAuthenticated
    ? `${calls.length} llamada(s) registrada(s)`
    : "Autenticación requerida";
  callsBody.innerHTML = "";

  if (!isAuthenticated) {
    const row = document.createElement("tr");
    row.innerHTML =
      '<td colspan="6" class="px-2 py-10 text-center text-sm text-slate-400">Guarda un token válido para ver las llamadas.</td>';
    callsBody.appendChild(row);
    return;
  }

  if (calls.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML =
      '<td colspan="6" class="px-2 py-10 text-center text-sm text-slate-400">No hay llamadas registradas todavía.</td>';
    callsBody.appendChild(row);
    return;
  }

  for (const call of calls) {
    const row = document.createElement("tr");
    row.className = "border-t border-slate-100 hover:bg-slate-50/60";
    row.innerHTML = `
      <td class="px-2 py-3 text-sm text-slate-800"></td>
      <td class="px-2 py-3 text-sm text-slate-700"></td>
      <td class="px-2 py-3 text-sm text-slate-700"></td>
      <td class="px-2 py-3"></td>
      <td class="px-2 py-3 text-xs text-slate-500"></td>
      <td class="px-2 py-3 text-right">
        <button type="button" class="view-call-btn rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50">
          Ver resumen
        </button>
      </td>`;
    row.children[0].textContent = call.patient_name || "Paciente";
    row.children[1].textContent = call.procedure_id || "—";
    row.children[2].textContent =
      call.postop_day === null || call.postop_day === undefined ? "—" : `Día ${call.postop_day}`;
    row.children[3].innerHTML = `<span class="inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${decisionBadgeClass(call.decision_label)}">${call.decision_label || "—"}</span>`;
    row.children[4].textContent = call.closed_reason || "—";
    row.querySelector(".view-call-btn").addEventListener("click", () => openCallDetail(call.call_id));
    callsBody.appendChild(row);
  }
}

async function refreshCalls() {
  if (loadingCalls || !isAuthenticated) return;
  loadingCalls = true;
  refreshCallsBtn.disabled = true;
  refreshCallsIcon.classList.add("animate-spin");
  refreshCallsLabel.textContent = "Actualizando…";

  try {
    calls = await apiFetch("/admin/calls");
    renderCalls();
    pushToast("success", "Lista de llamadas actualizada.");
  } catch (error) {
    pushToast("error", error.message);
  } finally {
    loadingCalls = false;
    refreshCallsBtn.disabled = false;
    refreshCallsIcon.classList.remove("animate-spin");
    refreshCallsLabel.textContent = "Actualizar";
  }
}

function closeCallDetail() {
  callDetailDialog.classList.add("hidden");
  callDetailDialog.classList.remove("flex");
  callDetailContent.innerHTML = "";
}

async function openCallDetail(callId) {
  if (!isAuthenticated) return;
  try {
    const summary = await apiFetch(`/admin/calls/${encodeURIComponent(callId)}`);
    callDetailContent.innerHTML = `
      <p><span class="font-medium text-slate-900">Paciente:</span> ${summary.patient_name || "—"}${summary.patient_id ? ` (${summary.patient_id})` : ""}</p>
      <p><span class="font-medium text-slate-900">Procedimiento:</span> ${summary.custom_procedure || summary.procedure_id || "—"}</p>
      <p><span class="font-medium text-slate-900">Día postop:</span> ${summary.postop_day ?? "—"}</p>
      <p><span class="font-medium text-slate-900">Decisión:</span> <span class="inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${decisionBadgeClass(summary.decision_label || summary.severity)}">${summary.decision_label || summary.severity || "—"}</span></p>
      <p><span class="font-medium text-slate-900">Próximo paso:</span> ${summary.next_steps || "—"}</p>
      <p class="rounded-lg border border-slate-200 bg-slate-50 p-3 leading-relaxed">${summary.clinical_summary || "Sin resumen disponible."}</p>
      <p class="text-xs text-slate-500">ID llamada: <span class="font-mono">${summary.call_id}</span></p>`;
    callDetailDialog.classList.remove("hidden");
    callDetailDialog.classList.add("flex");
  } catch (error) {
    pushToast("error", error.message);
  }
}

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

function setToken(value) {
  sessionStorage.setItem(TOKEN_KEY, value);
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function pushToast(kind, message) {
  const toast = document.createElement("div");
  toast.role = "status";
  toast.className =
    "flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm shadow-md " +
    (kind === "success"
      ? "border-teal-200 bg-teal-50 text-teal-800"
      : "border-rose-200 bg-rose-50 text-rose-800");
  toast.innerHTML = `<span></span><button type="button" aria-label="Cerrar notificación" class="shrink-0 text-current/70 transition hover:opacity-70">✕</button>`;
  toast.querySelector("span").textContent = message;
  toast.querySelector("button").addEventListener("click", () => toast.remove());
  toastArea.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let detail = "Error inesperado del servidor.";
    try {
      const payload = await response.json();
      if (payload.detail) {
        detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
      }
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function renderDocs() {
  docCount.textContent = isAuthenticated
    ? `${docs.length} documento(s) indexado(s)`
    : "Autenticación requerida";
  docsBody.innerHTML = "";

  if (!isAuthenticated) {
    const row = document.createElement("tr");
    row.innerHTML =
      '<td colspan="4" class="px-6 py-10 text-center text-sm text-slate-400">Guarda un token válido para listar documentos y usar acciones.</td>';
    docsBody.appendChild(row);
    return;
  }

  if (docs.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML =
      '<td colspan="4" class="px-6 py-10 text-center text-sm text-slate-400">No hay documentos en la base de conocimiento.</td>';
    docsBody.appendChild(row);
    return;
  }

  for (const doc of docs) {
    const row = document.createElement("tr");
    row.className = "border-t border-slate-100 hover:bg-slate-50/60";
    row.innerHTML = `
      <td class="px-6 py-3">
        <button type="button" class="delete-btn inline-flex items-center rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-rose-700 focus:outline-none focus:ring-2 focus:ring-rose-500/40">
          Eliminar
        </button>
      </td>
      <td class="doc-source-id px-6 py-3 font-mono text-[13px] text-slate-800"></td>
      <td class="doc-file-name px-6 py-3 text-sm text-slate-700"></td>
      <td class="doc-procedure-type px-6 py-3">
        <span class="inline-flex items-center rounded-full bg-teal-50 px-2.5 py-0.5 text-xs font-medium text-teal-700"></span>
      </td>`;
    row.querySelector(".doc-source-id").textContent = doc.source_id;
    row.querySelector(".doc-file-name").textContent = doc.file_name || "—";
    row.querySelector(".doc-procedure-type span").textContent = doc.procedure_type || "—";
    row.querySelector(".delete-btn").addEventListener("click", () => openConfirm(doc));
    docsBody.appendChild(row);
  }
}

function updateUploadState() {
  const hasFile = Boolean(docFile.files && docFile.files[0]);
  const hasType = Boolean(docType.value);
  const canUpload = isAuthenticated && hasFile && hasType && !uploading;
  uploadBtn.disabled = !canUpload;
  uploadBtn.textContent = uploading ? "Subiendo…" : "Subir documento";
  uploadHint.classList.toggle("hidden", hasType);
}

async function loadProcedureTypes() {
  if (!isAuthenticated) return;
  try {
    const options = await apiFetch("/admin/procedure-types");
    docType.innerHTML = '<option value="" disabled selected>Selecciona un tipo…</option>';
    for (const option of options) {
      const el = document.createElement("option");
      el.value = option.value;
      el.textContent = option.label;
      docType.appendChild(el);
    }
  } catch (error) {
    pushToast("error", error.message);
  }
}

async function refreshDocuments() {
  if (loadingDocs || !isAuthenticated) return;
  loadingDocs = true;
  refreshBtn.disabled = true;
  refreshIcon.classList.add("animate-spin");
  refreshLabel.textContent = "Actualizando…";

  try {
    docs = await apiFetch("/admin/documents");
    renderDocs();
    await loadProcedureTypes();
    pushToast("success", "Lista de documentos actualizada.");
  } catch (error) {
    pushToast("error", error.message);
  } finally {
    loadingDocs = false;
    refreshBtn.disabled = false;
    refreshIcon.classList.remove("animate-spin");
    refreshLabel.textContent = "Actualizar";
  }
}

function openConfirm(doc) {
  if (!isAuthenticated) return;
  confirmTarget = doc;
  confirmMessage.innerHTML =
    `¿Seguro que deseas eliminar <span class="font-mono font-medium text-slate-900">${doc.source_id}</span> de la base de conocimiento? Esta acción no se puede deshacer.`;
  confirmDialog.classList.remove("hidden");
  confirmDialog.classList.add("flex");
}

function closeConfirm() {
  confirmTarget = null;
  confirmDialog.classList.add("hidden");
  confirmDialog.classList.remove("flex");
}

function updateProcedureDialogState() {
  const busy = confirmingProcedure;
  procedureConfirm.disabled = busy;
  procedureCancel.disabled = busy;
  manualProcedure.disabled = busy;
  manualProcedureLabel.disabled = busy;
  procedureConfirm.textContent = busy ? "Procesando…" : "Confirmar";
  procedureConfirm.classList.toggle("opacity-60", busy);
  procedureConfirm.classList.toggle("cursor-not-allowed", busy);
  procedureProcessing.classList.toggle("hidden", !busy);
}

function openProcedureDialog(suggestion) {
  confirmingProcedure = false;
  updateProcedureDialogState();
  suggestedProcedure.textContent = suggestion.suggested_procedure;
  suggestedProcedureLabel.textContent = suggestion.suggested_procedure_label;
  manualProcedure.value = suggestion.suggested_procedure;
  manualProcedureLabel.value = suggestion.suggested_procedure_label;
  pendingProcedureUpload = {
    temp_id: suggestion.temp_id,
    file_name: docFile.files[0].name,
    procedure_label: suggestion.suggested_procedure_label,
  };
  procedureDialog.classList.remove("hidden");
  procedureDialog.classList.add("flex");
}

function closeProcedureDialog() {
  pendingProcedureUpload = null;
  confirmingProcedure = false;
  updateProcedureDialogState();
  procedureDialog.classList.add("hidden");
  procedureDialog.classList.remove("flex");
}

async function deleteDocument() {
  if (!confirmTarget || !isAuthenticated) return;
  const target = confirmTarget;
  closeConfirm();

  try {
    await apiFetch(`/admin/documents/${encodeURIComponent(target.source_id)}`, {
      method: "DELETE",
    });
    docs = docs.filter((item) => item.source_id !== target.source_id);
    renderDocs();
    await loadProcedureTypes();
    if (docType.value && !Array.from(docType.options).some((opt) => opt.value === docType.value)) {
      docType.value = "";
    }
    updateUploadState();
    pushToast("success", `Documento "${target.source_id}" eliminado.`);
  } catch (error) {
    pushToast("error", error.message);
  }
}

async function confirmProcedureUpload() {
  if (!pendingProcedureUpload) return;
  const procedureId = manualProcedure.value.trim();
  const procedureLabel = manualProcedureLabel.value.trim();
  if (!procedureId) {
    pushToast("error", "Debes indicar el slug en inglés para la carpeta.");
    return;
  }
  if (!procedureLabel) {
    pushToast("error", "Debes indicar el nombre en español del procedimiento.");
    return;
  }

  confirmingProcedure = true;
  updateProcedureDialogState();

  const body = new FormData();
  body.append("temp_id", pendingProcedureUpload.temp_id);
  body.append("procedure_id", procedureId);
  body.append("procedure_label", procedureLabel);
  body.append("file_name", pendingProcedureUpload.file_name);

  try {
    const created = await apiFetch("/admin/documents/confirm", { method: "POST", body });
    docs = [...docs.filter((item) => item.source_id !== created.source_id), created].sort((a, b) =>
      a.source_id.localeCompare(b.source_id),
    );
    renderDocs();
    docFile.value = "";
    docType.value = "";
    closeProcedureDialog();
    pushToast("success", `Documento indexado como ${created.procedure_type}.`);
    await loadProcedureTypes();
  } catch (error) {
    pushToast("error", error.message);
  } finally {
    confirmingProcedure = false;
    updateProcedureDialogState();
  }
}

async function uploadDocument() {
  const file = docFile.files && docFile.files[0];
  if (!isAuthenticated || !file || !docType.value || uploading) return;

  uploading = true;
  updateUploadState();

  try {
    if (docType.value === "other") {
      const body = new FormData();
      body.append("file", file);
      const suggestion = await apiFetch("/admin/documents/analyze", { method: "POST", body });
      uploading = false;
      updateUploadState();
      openProcedureDialog(suggestion);
      return;
    }

    const body = new FormData();
    body.append("file", file);
    body.append("procedure_type", docType.value);
    const created = await apiFetch("/admin/documents", { method: "POST", body });
    docs = [...docs.filter((item) => item.source_id !== created.source_id), created].sort((a, b) =>
      a.source_id.localeCompare(b.source_id),
    );
    renderDocs();
    docFile.value = "";
    docType.value = "";
    pushToast("success", "Documento agregado y protocolo regenerado.");
    await loadProcedureTypes();
  } catch (error) {
    pushToast("error", error.message);
  } finally {
    uploading = false;
    updateUploadState();
  }
}

saveTokenBtn.addEventListener("click", async () => {
  const value = tokenInput.value.trim();
  if (!value) {
    pushToast("error", "El token de administrador no puede estar vacío.");
    return;
  }
  saveTokenBtn.disabled = true;
  const ok = await validateAndActivateToken(value);
  saveTokenBtn.disabled = false;
  if (!ok) return;
  pushToast("success", "Token de administrador validado.");
  await loadProcedureTypes();
  await refreshDocuments();
  if (activeTab === "calls") await refreshCalls();
});

tokenInput.addEventListener("input", () => {
  showTokenStatus({ saved: false, error: false });
  if (isAuthenticated) {
    setAuthenticated(false);
  }
});

refreshBtn.addEventListener("click", refreshDocuments);
refreshCallsBtn.addEventListener("click", refreshCalls);
for (const button of tabButtons) {
  button.addEventListener("click", () => switchTab(button.dataset.tab || "documents"));
}
callDetailClose.addEventListener("click", closeCallDetail);
callDetailDialog.addEventListener("click", (event) => {
  if (event.target === callDetailDialog) closeCallDetail();
});
docFile.addEventListener("change", updateUploadState);
docType.addEventListener("change", updateUploadState);
uploadBtn.addEventListener("click", uploadDocument);
confirmCancel.addEventListener("click", closeConfirm);
confirmDelete.addEventListener("click", deleteDocument);
procedureCancel.addEventListener("click", () => {
  if (!confirmingProcedure) closeProcedureDialog();
});
procedureConfirm.addEventListener("click", confirmProcedureUpload);
confirmDialog.addEventListener("click", (event) => {
  if (event.target === confirmDialog) closeConfirm();
});
procedureDialog.addEventListener("click", (event) => {
  if (event.target === procedureDialog && !confirmingProcedure) closeProcedureDialog();
});

const savedToken = getToken();
if (savedToken) {
  tokenInput.value = savedToken;
  void validateAndActivateToken(savedToken).then((ok) => {
    if (ok) {
      void loadProcedureTypes();
      void refreshDocuments();
    }
  });
}

updateAuthUI();
renderDocs();
renderCalls();
switchTab("documents");
