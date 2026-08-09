/** Clinical knowledge admin console — wired to FastAPI /admin routes. */

const TOKEN_KEY = "postop_admin_token";

/** @type {Array<{source_id: string, procedure_type: string}>} */
let docs = [];
/** @type {{source_id: string, procedure_type: string} | null} */
let confirmTarget = null;
let loadingDocs = false;
let uploading = false;

const tokenInput = document.getElementById("admin-token");
const tokenSavedMsg = document.getElementById("token-saved-msg");
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
const toastArea = document.getElementById("toast-area");

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
  const id = Date.now() + Math.random();
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
  docCount.textContent = `${docs.length} documento(s) indexado(s)`;
  docsBody.innerHTML = "";

  if (docs.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML =
      '<td colspan="3" class="px-6 py-10 text-center text-sm text-slate-400">No hay documentos en la base de conocimiento.</td>';
    docsBody.appendChild(row);
    return;
  }

  for (const doc of docs) {
    const row = document.createElement("tr");
    row.className = "border-t border-slate-100 hover:bg-slate-50/60";
    row.innerHTML = `
      <td class="px-6 py-3 font-mono text-[13px] text-slate-800"></td>
      <td class="px-6 py-3">
        <span class="inline-flex items-center rounded-full bg-teal-50 px-2.5 py-0.5 text-xs font-medium text-teal-700"></span>
      </td>
      <td class="px-6 py-3 text-right">
        <button type="button" class="delete-btn inline-flex items-center rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-rose-700 focus:outline-none focus:ring-2 focus:ring-rose-500/40">
          Eliminar
        </button>
      </td>`;
    row.querySelector("td:first-child").textContent = doc.source_id;
    row.querySelector("span").textContent = doc.procedure_type;
    row.querySelector(".delete-btn").addEventListener("click", () => openConfirm(doc));
    docsBody.appendChild(row);
  }
}

function updateUploadState() {
  const hasFile = Boolean(docFile.files && docFile.files[0]);
  const hasType = Boolean(docType.value);
  const canUpload = hasFile && hasType && !uploading;
  uploadBtn.disabled = !canUpload;
  uploadBtn.textContent = uploading ? "Subiendo…" : "Subir documento";
  uploadHint.classList.toggle("hidden", hasType);
}

async function loadProcedureTypes() {
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
  if (loadingDocs) return;
  loadingDocs = true;
  refreshBtn.disabled = true;
  refreshIcon.classList.add("animate-spin");
  refreshLabel.textContent = "Actualizando…";

  try {
    docs = await apiFetch("/admin/documents");
    renderDocs();
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

async function deleteDocument() {
  if (!confirmTarget) return;
  const target = confirmTarget;
  closeConfirm();

  try {
    await apiFetch(`/admin/documents/${encodeURIComponent(target.source_id)}`, {
      method: "DELETE",
    });
    docs = docs.filter((item) => item.source_id !== target.source_id);
    renderDocs();
    pushToast("success", `Documento "${target.source_id}" eliminado.`);
  } catch (error) {
    pushToast("error", error.message);
  }
}

async function uploadDocument() {
  const file = docFile.files && docFile.files[0];
  if (!file || !docType.value || uploading) return;

  uploading = true;
  updateUploadState();

  const body = new FormData();
  body.append("file", file);
  body.append("procedure_type", docType.value);

  try {
    const created = await apiFetch("/admin/documents", { method: "POST", body });
    docs = [...docs.filter((item) => item.source_id !== created.source_id), created].sort((a, b) =>
      a.source_id.localeCompare(b.source_id),
    );
    renderDocs();
    docFile.value = "";
    docType.value = "";
    pushToast("success", "Documento agregado a la base de conocimiento.");
  } catch (error) {
    pushToast("error", error.message);
  } finally {
    uploading = false;
    updateUploadState();
  }
}

saveTokenBtn.addEventListener("click", () => {
  const value = tokenInput.value.trim();
  if (!value) {
    pushToast("error", "El token de administrador no puede estar vacío.");
    return;
  }
  setToken(value);
  tokenSavedMsg.classList.remove("hidden");
  pushToast("success", "Token de administrador guardado.");
  loadProcedureTypes();
  refreshDocuments();
});

tokenInput.addEventListener("input", () => {
  tokenSavedMsg.classList.add("hidden");
});

refreshBtn.addEventListener("click", refreshDocuments);
docFile.addEventListener("change", updateUploadState);
docType.addEventListener("change", updateUploadState);
uploadBtn.addEventListener("click", uploadDocument);
confirmCancel.addEventListener("click", closeConfirm);
confirmDelete.addEventListener("click", deleteDocument);
confirmDialog.addEventListener("click", (event) => {
  if (event.target === confirmDialog) closeConfirm();
});

const savedToken = getToken();
if (savedToken) {
  tokenInput.value = savedToken;
  tokenSavedMsg.classList.remove("hidden");
  loadProcedureTypes();
  refreshDocuments();
}

updateUploadState();
renderDocs();
