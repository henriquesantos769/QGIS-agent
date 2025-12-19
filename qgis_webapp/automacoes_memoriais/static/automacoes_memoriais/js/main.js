// ---------------------------------------------------------
// 🔧 Seletores
// ---------------------------------------------------------
const dropProject = document.getElementById("dropzone-qgis");
const fileInputProject = document.getElementById("fileInputProject");

const layerLotes = document.getElementById("layerLotes");
const layerQuadras = document.getElementById("layerQuadras");
const layerRuas = document.getElementById("layerRuas");

const startBtn = document.getElementById("startBtn");
const progressArea = document.getElementById("progressArea");
const resetBtn = document.getElementById("resetBtn");
const downloadBtn = document.getElementById("downloadMemoriais");
const toast = document.getElementById("toast");

let selectedProject = null;
let monitoramentoAtivo = false;
let toastTimeout = null;

// ---------------------------------------------------------
// 🔄 Loader visual
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

// ---------------------------------------------------------
// 🔄 Utilitários UI
// ---------------------------------------------------------
function setLoading(btn, label) {
  if (!btn) return;
  if (!btn.dataset.originalHtml) {
    btn.dataset.originalHtml = btn.innerHTML;
  }
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
  toastTimeout = setTimeout(() => {
    toast.classList.remove("show");
  }, 2200);
}

// ---------------------------------------------------------
// 📂 Estado: projeto selecionado
// ---------------------------------------------------------
function checkReady() {
  if (selectedProject) {
    progressArea.style.display = "grid";
    startBtn.style.display = "inline-flex";
    startBtn.disabled = false;
  }
}

function handleChosenProject(file) {
  if (!file) return;

  // valida ZIP
  if (!file.name.toLowerCase().endsWith(".zip")) {
    showToast("❌ Envie um projeto QGIS compactado (.zip)");
    return;
  }

  selectedProject = file;

  const hint = dropProject.querySelector(".hint");
  const strong = dropProject.querySelector("strong");

  if (strong) strong.textContent = file.name;
  if (hint) hint.textContent = "Projeto QGIS selecionado";

  dropProject.classList.add("chosen");
  showToast(`Projeto carregado: ${file.name}`);
  checkReady();
}

// ---------------------------------------------------------
// 📂 Input file — handlers robustos
// ---------------------------------------------------------

// Força abertura do seletor ao clicar no card inteiro
dropProject.addEventListener("click", () => {
  fileInputProject.click();
});

// change (padrão)
fileInputProject.addEventListener("change", e => {
  const file = e.target.files && e.target.files[0];
  if (file) handleChosenProject(file);

  // permite selecionar o mesmo arquivo novamente
  e.target.value = "";
});

// input (fallback)
fileInputProject.addEventListener("input", e => {
  const file = e.target.files && e.target.files[0];
  if (file) handleChosenProject(file);
});

// ---------------------------------------------------------
// 🧲 Drag & Drop
// ---------------------------------------------------------
dropProject.addEventListener("dragover", e => {
  e.preventDefault();
  dropProject.style.transform = "scale(1.02)";
});

dropProject.addEventListener("dragleave", () => {
  dropProject.style.transform = "none";
});

dropProject.addEventListener("drop", e => {
  e.preventDefault();
  dropProject.style.transform = "none";

  const file = e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) handleChosenProject(file);
});

// ---------------------------------------------------------
// 🔐 CSRF
// ---------------------------------------------------------
function getCSRFToken() {
  return document
    .querySelector('meta[name="csrf-token"]')
    .getAttribute("content");
}

// ---------------------------------------------------------
// 🚀 Enviar projeto QGIS (ZIP) ao backend
// ---------------------------------------------------------
async function enviarProjetoQGIS() {
  if (!selectedProject) {
    showToast("❌ Selecione um projeto QGIS (.zip)");
    return false;
  }

  if (!layerLotes.value.trim()) {
    showToast("❌ Informe o nome da camada de lotes");
    return false;
  }

  const formData = new FormData();
  formData.append("arquivo", selectedProject);
  formData.append("layer_lotes", layerLotes.value.trim());
  formData.append("layer_quadras", layerQuadras.value.trim());
  formData.append("layer_ruas", layerRuas.value.trim());

  setLoading(startBtn, "Processando...");
  showToast("⏳ Processando projeto QGIS...");

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
    showToast("❌ Erro inesperado no envio");
    clearLoading(startBtn);
    return false;
  }
}

// ---------------------------------------------------------
// 📊 Monitoramento do progresso
// ---------------------------------------------------------
async function monitorarProgresso() {
  const bar = document.getElementById("barFill");
  const stageTitle = document.getElementById("stageTitle");
  const percentLabel = document.getElementById("percentLabel");
  const detail = document.getElementById("detailLine");
  const stageChip = document.getElementById("stageChip");

  const TOTAL_ETAPAS = 20;
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
        showToast("❌ Erro ao gerar memoriais");
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
// 🧹 Finalização da UI
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
// ▶️ Botão Iniciar
// ---------------------------------------------------------
startBtn.addEventListener("click", async () => {
  monitoramentoAtivo = false;

  document.getElementById("barFill").style.width = "0%";
  document.getElementById("percentLabel").textContent = "0%";

  showToast("🚀 Iniciando processamento...");

  const ok = await enviarProjetoQGIS();
  if (ok) monitorarProgresso();
  else clearLoading(startBtn);
});

// ---------------------------------------------------------
// ⬇️ Download dos memoriais
// ---------------------------------------------------------
downloadBtn.addEventListener("click", () => {
  window.location.href = "download/";
});

// ---------------------------------------------------------
// 🔄 Reiniciar
// ---------------------------------------------------------
resetBtn.addEventListener("click", () => location.reload());

// ---------------------------------------------------------
// ♻️ Reset backend ao carregar página
// ---------------------------------------------------------
window.addEventListener("load", async () => {
  try {
    await fetch("resetar_progresso/", {
      method: "POST",
      credentials: "include"
    });
  } catch (e) {}

  resetBtn.style.display = "none";
  downloadBtn.style.display = "none";
});
