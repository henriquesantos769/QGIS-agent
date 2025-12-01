// ---------------------------------------------------------
// 🔧 Seletores
// ---------------------------------------------------------
const dropDXF = document.getElementById("dropzone-dxf");
const fileInputDXF = document.getElementById("fileInputDXF");

const startBtn = document.getElementById("startBtn");
const progressArea = document.getElementById("progressArea");
const resetBtn = document.getElementById("resetBtn");
const downloadBtn = document.getElementById("downloadMemoriais");
const toast = document.getElementById("toast");

let selectedDXF = null;
let monitoramentoAtivo = false;
let toastTimeout = null;

// ---------------------------------------------------------
// Loader visual
// ---------------------------------------------------------
const SPINNER = `
  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 50 50">
    <circle cx="25" cy="25" r="20" fill="none" stroke="currentColor" 
            stroke-width="4" stroke-linecap="round"
            stroke-dasharray="31.415, 31.415">
      <animateTransform attributeName="transform" type="rotate"
                        from="0 25 25" to="360 25 25"
                        dur="0.8s" repeatCount="indefinite"/>
    </circle>
  </svg>`;

function setLoading(btn, label) {
  if (!btn) return;
  if (!btn.dataset.originalHtml) btn.dataset.originalHtml = btn.innerHTML;
  btn.innerHTML = `${label} ${SPINNER}`;
  btn.disabled = true;
}

function clearLoading(btn) {
  if (!btn) return;
  btn.disabled = false;
  if (btn.dataset.originalHtml) {
    btn.innerHTML = btn.dataset.originalHtml;
    delete btn.dataset.originalHtml;
  }
}

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add("show");
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove("show"), 2200);
}

// ---------------------------------------------------------
// Ativar UI após selecionar arquivo
// ---------------------------------------------------------
function checkReady() {
  if (selectedDXF) {
    progressArea.style.display = "grid";
    startBtn.style.display = "inline-flex";
    startBtn.disabled = false;
  }
}

// ---------------------------------------------------------
// Upload de arquivo DXF
// ---------------------------------------------------------
function handleChosenDXF(file) {
  selectedDXF = file;
  dropDXF.querySelector(".hint").textContent = `Selecionado: ${file.name}`;
  dropDXF.classList.add("chosen");
  showToast(`DXF carregado: ${file.name}`);
  checkReady();
}

fileInputDXF.addEventListener("change", e => {
  const file = e.target.files?.[0];
  if (file) handleChosenDXF(file);
  e.target.value = "";
});

// Drag & drop
dropDXF.addEventListener("dragover", e => { 
  e.preventDefault(); 
  dropDXF.style.transform = "scale(1.02)"; 
});
dropDXF.addEventListener("dragleave", () => { 
  dropDXF.style.transform = "none"; 
});
dropDXF.addEventListener("drop", e => {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (file) handleChosenDXF(file);
  dropDXF.style.transform = "none";
});

// ---------------------------------------------------------
// Enviar DXF ao backend
// ---------------------------------------------------------
function getCSRFToken() {
  return document.querySelector('meta[name="csrf-token"]').getAttribute("content");
}

async function enviarDXF() {
  if (!selectedDXF) {
    showToast("❌ Selecione um arquivo DXF!");
    return false;
  }

  const formData = new FormData();
  formData.append("arquivo", selectedDXF);

  setLoading(startBtn, "Processando...");
  showToast("⏳ Processando DXF...");

  try {
    const response = await fetch("gerar_memoriais/", {
      method: "POST",
      headers: { "X-CSRFToken": getCSRFToken() },
      body: formData,
      credentials: "include"
    });

    const data = await response.json();

    if (data.status === "sucesso") {
      return true;
    } else {
      showToast("❌ " + data.mensagem);
      clearLoading(startBtn);
      return false;
    }
  } catch (err) {
    console.error(err);
    showToast("❌ Erro inesperado.");
    clearLoading(startBtn);
    return false;
  }
}

// ---------------------------------------------------------
// Monitoramento do progresso
// ---------------------------------------------------------
async function monitorarProgresso() {
  const bar = document.getElementById("barFill");
  const stageTitle = document.getElementById("stageTitle");
  const percentLabel = document.getElementById("percentLabel");
  const detail = document.getElementById("detailLine");
  const stageChip = document.getElementById("stageChip");

  const TOTAL_ETAPAS = 18;
  monitoramentoAtivo = true;

  async function atualizar() {
    if (!monitoramentoAtivo) return;

    try {
      const res = await fetch(`progresso/?v=${Date.now()}`, {
        cache: "no-store",
        credentials: "include"
      });

      const data = await res.json();
      const etapa = data.etapa || 0;
      const msg = data.mensagem || "Processando…";

      const pct = Math.min((etapa / TOTAL_ETAPAS) * 100, 100);

      bar.style.width = `${pct}%`;
      percentLabel.textContent = `${Math.round(pct)}%`;
      stageTitle.textContent = msg;
      detail.textContent = msg;
      stageChip.textContent = `Etapa ${Math.min(etapa, TOTAL_ETAPAS)} de ${TOTAL_ETAPAS}`;

      if (etapa < TOTAL_ETAPAS && etapa !== 99) {
        setTimeout(atualizar, 700);
      } else if (etapa >= TOTAL_ETAPAS) {
        bar.style.width = "100%";
        percentLabel.textContent = "100%";
        monitoramentoAtivo = false;
        finalizarUI();
        showToast("✅ Memoriais gerados!");
      } else if (etapa === 99) {
        showToast("❌ Erro ao gerar memoriais.");
        monitoramentoAtivo = false;
        finalizarUI(true);
      }

    } catch (err) {
      console.error(err);
    }
  }

  atualizar();
}

// ---------------------------------------------------------
// Finalização da UI
// ---------------------------------------------------------
function finalizarUI(erro = false) {
  clearLoading(startBtn);
  startBtn.style.display = "none";

  if (!erro) {
    downloadBtn.style.display = "inline-flex";
  }

  resetBtn.style.display = "inline-flex";
}

// ---------------------------------------------------------
// Botão "Iniciar"
// ---------------------------------------------------------
startBtn.addEventListener("click", async () => {
  monitoramentoAtivo = false;

  const bar = document.getElementById("barFill");
  bar.style.width = "0%";
  document.getElementById("percentLabel").textContent = "0%";

  showToast("🚀 Iniciando processamento...");

  const ok = await enviarDXF();
  if (ok) monitorarProgresso();
  else clearLoading(startBtn);
});

// ---------------------------------------------------------
// Botão "Baixar memoriais"
// ---------------------------------------------------------
downloadBtn.addEventListener("click", () => {
  window.location.href = "download/";
});

// ---------------------------------------------------------
// Botão "Reiniciar"
// ---------------------------------------------------------
resetBtn.addEventListener("click", () => location.reload());

// ---------------------------------------------------------
// Reset backend ao carregar página
// ---------------------------------------------------------
window.addEventListener("load", async () => {
  try {
    await fetch("resetar_progresso/", { method: "POST", credentials: "include" });
  } catch (e) {}

  resetBtn.style.display = "none";
  downloadBtn.style.display = "none";
});
