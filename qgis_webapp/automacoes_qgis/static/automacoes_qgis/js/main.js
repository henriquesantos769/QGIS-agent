// main.js (VERSÃO DE DEPURAÇÃO)

const dropDXF = document.getElementById("dropzone-dxf");
const dropOrtho = document.getElementById("dropzone-ortho");
const fileInputDXF = document.getElementById("fileInputDXF");
const fileInputOrtho = document.getElementById("fileInputOrtho");

const startBtn = document.getElementById("startBtn");
const progressArea = document.getElementById("progressArea");
const resetBtn = document.getElementById("resetBtn");
const viewBtn = document.getElementById("viewBtn");
const btnExportQField = document.getElementById("btnExportQField");
const btnBaixarEnviar = document.getElementById("btnBaixarEnviar");
const toast = document.getElementById("toast");
let projetoPath = null;

let selectedDXF = null;
let selectedOrtho = null;

let toastTimeout = null;
let monitoramentoAtivo = false;

const SPINNER_SVG = `
  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 50 50" style="vertical-align:middle; margin-left:8px">
    <circle cx="25" cy="25" r="20" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"
            stroke-dasharray="31.415, 31.415">
      <animateTransform attributeName="transform" type="rotate"
                       from="0 25 25" to="360 25 25" dur="0.8s" repeatCount="indefinite"/>
   </circle>
  </svg>`;

function setLoading(btn, label) {
  if (!btn) return;
  if (!btn.dataset.originalHtml) btn.dataset.originalHtml = btn.innerHTML;
  btn.innerHTML = `${label} ${SPINNER_SVG}`;
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
// 🔹 Exibe botão "Iniciar" só quando ambos arquivos forem selecionados
// ---------------------------------------------------------
function checkReadyToStart() {
  // DEBUG: Loga o estado das variáveis
  console.log(`[DEBUG] Verificando: DXF=${!!selectedDXF}, Ortho=${!!selectedOrtho}`);

  if (selectedDXF && selectedOrtho) {
    // DEBUG: Condição atendida
    console.log("[DEBUG] ✅ Ambos selecionados! Mostrando botão E ÁREA.");
    progressArea.style.display = "grid"; // <-- ❗ AQUI ESTÁ A CORREÇÃO
    startBtn.style.display = "inline-flex";
    startBtn.disabled = false;
  } else {
    // DEBUG: Condição falhou
    console.log("[DEBUG] ❌ Faltando arquivos. Botão e área ocultos.");
    startBtn.disabled = true;
    startBtn.style.display = "none";
    progressArea.style.display = "none"; // <-- ❗ E GARANTE QUE ESTEJA OCULTO
  }
}

function handleChosenDXF(file) {
  selectedDXF = file;
  dropDXF.querySelector('.hint').textContent = `Selecionado: ${file.name}`;
  dropDXF.classList.add('chosen');
  showToast(`DXF carregado: ${file.name}`);
  checkReadyToStart();
}

function handleChosenOrtho(file) {
  selectedOrtho = file;
  dropOrtho.querySelector('.hint').textContent = `Selecionado: ${file.name}`;
  dropOrtho.classList.add('chosen');
  showToast(`Ortofoto carregada: ${file.name}`);
  checkReadyToStart();
}

fileInputDXF.addEventListener("change", e => {
  console.log("[DEBUG] Evento 'change' disparado para DXF");
  const file = e.target.files?.[0];
  if (!file) {
    console.log("[DEBUG] DXF: Nenhum arquivo selecionado.");
    return;
  }
  handleChosenDXF(file);
  e.target.value = ""; // <- força o input a "zerar"
});

fileInputOrtho.addEventListener("change", e => {
  console.log("[DEBUG] Evento 'change' disparado para Ortho");
  const file = e.target.files?.[0];
  if (!file) {
    console.log("[DEBUG] Ortho: Nenhum arquivo selecionado.");
    return;
  }
  handleChosenOrtho(file);
  e.target.value = ""; // idem aqui
});

// ---------------------------------------------------------
// 🔹 Drag & Drop para os dois campos
// ---------------------------------------------------------
[dropDXF, dropOrtho].forEach(zone => {
  zone.addEventListener("dragover", e => { 
    e.preventDefault(); 
    zone.style.transform = "scale(1.02)"; 
  });
  zone.addEventListener("dragleave", () => { 
    zone.style.transform = "none"; 
  });
  zone.addEventListener("drop", e => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    console.log(`[DEBUG] Arquivo solto em ${zone.id}`);
    if (zone.id === "dropzone-dxf") handleChosenDXF(file);
    else handleChosenOrtho(file);
    zone.style.transform = "none";
  });
});

function getCSRFToken() {
  return document.querySelector('meta[name="csrf-token"]').getAttribute("content");
}

// ---------------------------------------------------------
// 🔹 Envio de arquivos
// ---------------------------------------------------------
async function enviarArquivosParaServidor() {
  if (!selectedDXF) {
    showToast("❌ Selecione ao menos o arquivo DXF!");
    return false;
  }
  // A verificação de 'ambos obrigatórios' agora está só no 'checkReadyToStart'
  // O envio só acontece se o botão 'startBtn' estiver visível.

  const formData = new FormData();
  formData.append("arquivo", selectedDXF);
  // Garante que a ortofoto só é enviada se existir
  if (selectedOrtho) formData.append("ortofoto", selectedOrtho);

  showToast("⏳ Processando... isso pode levar alguns segundos.");
  setLoading(startBtn, "Processando...");

  try {
    const response = await fetch("/criar_projeto_qgis/", {
      method: "POST",
      headers: { "X-CSRFToken": getCSRFToken() },
      body: formData,
      credentials: "include"
    });

    const data = await response.json();
    if (data.status === "sucesso") {
      projetoPath = data.projeto_path;
      return true;
    } else {
      showToast("❌ " + data.mensagem);
      clearLoading(startBtn);
     return false;
    }
  } catch (err) {
    console.error(err);
    showToast("❌ Erro inesperado durante o processamento.");
    clearLoading(startBtn);
   return false;
 }
}

// ---------------------------------------------------------
// 🔹 Monitora progresso geral
// ---------------------------------------------------------
async function monitorarProgresso() {
  const barFill = document.getElementById("barFill");
  const stageTitle = document.getElementById("stageTitle");
  const percentLabel = document.getElementById("percentLabel");
  const detailLine = document.getElementById("detailLine");
  const stageChip = document.getElementById("stageChip");

  const etapasTotal = 17;
  monitoramentoAtivo = true;

  async function atualizar() {
    if (!monitoramentoAtivo) return;

    try {
      // Adicionando cache-busting para garantir que não haja cache
      const cacheBuster = new Date().getTime();
      const res = await fetch(`/progresso/?v=${cacheBuster}`, {
        cache: "no-store",
        headers: { "Cache-Control": "no-store", "Pragma": "no-cache" }
      });
      const data = await res.json();

      const etapa = data.etapa || 0;
      const mensagem = data.mensagem || "Aguardando...";
      const porcentagem = Math.min((etapa / etapasTotal) * 100, 100);

      // Atualiza UI
      barFill.style.width = `${porcentagem}%`;
      percentLabel.textContent = `${Math.round(porcentagem)}%`;
      stageTitle.textContent = mensagem;
      detailLine.textContent = mensagem;
      stageChip.textContent = `Etapa ${Math.min(etapa, etapasTotal)} de ${etapasTotal}`;

      if (etapa === 98) {
        showToast("⚠️ Falha ao buscar ruas no OpenStreetMap.");
        exibirBotaoRetryOverpass();
        monitoramentoAtivo = false;
        return;
      }

      if (etapa < etapasTotal && etapa !== 99) {
        setTimeout(atualizar, 700);
      } else if (etapa >= etapasTotal) {
        barFill.style.width = "100%";
        percentLabel.textContent = "100%";
        showToast("✅ Projeto criado com sucesso!");
        monitoramentoAtivo = false;
        finalizarInterface();
      } else if (etapa === 99) {
        showToast("❌ Ocorreu um erro no backend!");
        monitoramentoAtivo = false;
        finalizarInterface(true);
      }
    } catch (e) {
      console.error("Erro ao obter progresso:", e);
    }
  }

  atualizar();
}

// ---------------------------------------------------------
// 🔹 Retry Overpass
// ---------------------------------------------------------
function exibirBotaoRetryOverpass() {
  const footer = document.querySelector(".footer");
  if (document.getElementById("retryOverpassBtn")) return;

  const retryBtn = document.createElement("button");
  retryBtn.id = "retryOverpassBtn";
  retryBtn.className = "btn ghost";
  retryBtn.textContent = "🔁 Repetir busca de ruas";

  retryBtn.onclick = async () => {
    setLoading(retryBtn, "Repetindo...");
    showToast("🛰️ Tentando novamente conexão com o OpenStreetMap...");
    try {
      const res = await fetch("/tentar_overpass/", {
        method: "POST",
        headers: { "X-CSRFToken": getCSRFToken() },
        credentials: "include"
      });
      const data = await res.json();

      if (data.status === "sucesso") {
        showToast("✅ Ruas extraídas com sucesso! Continuando...");
        retryBtn.remove();
        monitorarProgresso();
      } else {
        showToast("⚠️ Falha ao repetir: " + (data.mensagem || "Erro desconhecido"));
        clearLoading(retryBtn);
      }
    } catch (err) {
      console.error(err);
      showToast("❌ Erro ao comunicar com o servidor para retry.");
      clearLoading(retryBtn);
    }
  };

  footer.appendChild(retryBtn);
}

// ---------------------------------------------------------
// 🔹 Finaliza interface após execução
// ---------------------------------------------------------
function finalizarInterface(erro = false) {
  clearLoading(startBtn); // restaura botão só agora
  startBtn.style.display = "none";

  if (!erro) {
    viewBtn.style.display = "inline-flex";
    btnBaixarEnviar.style.display = "inline-flex";
    btnExportQField.style.display = "inline-flex";
    resetBtn.style.display = "inline-flex";
  } else {
    resetBtn.style.display = "inline-flex";
  }
}
// ---------------------------------------------------------
// 🔹 Iniciar pipeline
// ---------------------------------------------------------
startBtn.addEventListener("click", async () => {
  if (startBtn.disabled) return;

  console.log("[DEBUG] 🚀 Botão 'Iniciar' clicado.");
  monitoramentoAtivo = false; // mata qualquer monitor anterior (por segurança)

  // Mostra área de progresso e zera UI
  progressArea.style.display = "grid";
  const barFill = document.getElementById("barFill");
  const percentLabel = document.getElementById("percentLabel");
  const stageTitle = document.getElementById("stageTitle");
  const detailLine = document.getElementById("detailLine");
  const stageChip = document.getElementById("stageChip");

  barFill.style.width = "0%";
  percentLabel.textContent = "0%";
  stageTitle.textContent = "Preparando ambiente…";
  detailLine.textContent = "Aguardando início…";
  stageChip.textContent = "Etapa 0 de 17";

  startBtn.disabled = true;
  showToast("🚀 Iniciando processamento...");

  const ok = await enviarArquivosParaServidor();
  if (ok) {
    // dispara monitor assim que o backend respondeu
    monitorarProgresso();
  } else {
    // Se falhar o envio, reabilita o botão
    startBtn.disabled = false;
    clearLoading(startBtn);
    console.log("[DEBUG] Falha no envio, botão 'Iniciar' reabilitado.");
  }
});

// ---------------------------------------------------------
// 🔹 Reset tudo
// ---------------------------------------------------------
resetBtn.addEventListener("click", () => {
  console.log("🔃 Reset via reload de página");
  location.reload(); // reproduz exatamente o comportamento de um refresh
});


// ---------------------------------------------------------
// 🔹 Ao carregar a página, zera backend e UI
// ---------------------------------------------------------
window.addEventListener("load", async () => {
  try {
    await fetch("/resetar_progresso/", { method: "POST", credentials: "include" });
    console.log("Backend resetado ao carregar a página.");
  } catch (e) {
    console.warn("Falha ao resetar progresso inicial:", e);
  }

  // estado inicial da UI
  resetBtn.style.display = "none";
  viewBtn.style.display = "none";
  btnExportQField.style.display = "none";
  btnBaixarEnviar.style.display = "none";
  
  // Esta chamada agora cuida de esconder o startBtn E a progressArea
  checkReadyToStart(); 
});

async function monitorarProgressoQField() {
  console.log("[DEBUG] Monitoramento de envio QField iniciado...");
  let tentativasSemResposta = 0;
  const maxTentativas = 10; // evita loop infinito se backend parar de responder

  const interval = setInterval(async () => {
    try {
      const cacheBuster = new Date().getTime();
      const res = await fetch(`/progresso_qfield/?v=${cacheBuster}`, {
        cache: "no-store",
        headers: { "Cache-Control": "no-store", "Pragma": "no-cache" },
        credentials: "include"
      });

      if (!res.ok) {
        console.warn("[DEBUG] Falha na requisição de progresso:", res.status);
        tentativasSemResposta++;
        if (tentativasSemResposta >= maxTentativas) {
          clearInterval(interval);
          showToast("⚠️ Falha ao obter progresso do QField Cloud.");
        }
        return;
      }

      const data = await res.json();
      if (data.mensagem) {
        console.log(`[QField] ${data.mensagem}`);
        showToast(data.mensagem);
      }

      if (data.mensagem?.includes("✅ Upload concluído")) {
        clearInterval(interval);
        showToast("✅ Upload completo no QField Cloud!");
        clearLoading(btnExportQField);
        console.log("[DEBUG] Monitoramento QField encerrado com sucesso.");
      }

    } catch (err) {
      console.error("[DEBUG] Erro no monitoramento QField:", err);
      clearInterval(interval);
      clearLoading(btnExportQField);
      showToast("❌ Erro ao monitorar progresso do QField.");
    }
  }, 1500); // intervalo levemente maior para evitar sobrecarga no servidor
}

btnExportQField.addEventListener("click", async () => {
  if (!projetoPath) {
    showToast("❌ Nenhum projeto QGIS disponível para exportar.");
    return;
  }

  setLoading(btnExportQField, "Enviando...");
  showToast("⏳ Enviando projeto para QField Cloud...");

  try {
    // inicia monitoramento em paralelo
    monitorarProgressoQField();

    const res = await fetch("/exportar-qfield/", {
      method: "POST",
      headers: {
        "X-CSRFToken": getCSRFToken(),
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ projeto_path: projetoPath }),
      credentials: "include"
    });

    const data = await res.json();

    if (data.status === "sucesso") {
      showToast("✅ Exportação iniciada no servidor!");
    } else {
      showToast("❌ Falha ao exportar: " + (data.mensagem || "Erro desconhecido."));
    }
  } catch (err) {
    console.error("[DEBUG] Erro de conexão ao exportar:", err);
    showToast("❌ Erro de conexão ao exportar para QField.");
  } finally {
    // await new Promise(r => setTimeout(r, 200));
    // clearLoading(btnExportQField);
  }
});


viewBtn.addEventListener("click", async (e) => {
  e.preventDefault();

  if (!projetoPath) {
    showToast("❌ Nenhum projeto disponível para download.");
    return;
  }

  setLoading(viewBtn, "Baixando...");
  showToast("⏳ Preparando o pacote para download...");

  try {
    const response = await fetch(`/download_pacote/?path=${encodeURIComponent(projetoPath)}`, {
      method: "GET",
      credentials: "include"
    });

    if (!response.ok) throw new Error("Falha ao gerar o pacote.");

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "projeto_qgis.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);

    showToast("✅ Projeto baixado com sucesso!");
  } catch (err) {
    console.error("[DEBUG] Erro ao baixar o projeto:", err);
    showToast("❌ Erro ao baixar o projeto QGIS.");
  } finally {
    await new Promise(r => setTimeout(r, 200));
    clearLoading(viewBtn);
  }
});

btnBaixarEnviar.addEventListener("click", async () => {
  if (!projetoPath) {
    showToast("❌ Nenhum projeto QGIS disponível para baixar e enviar.");
    return;
  }

  setLoading(btnBaixarEnviar, "Processando...");
  showToast("⏳ Gerando pacote e enviando para QField Cloud...");

  try {
    // Dispara o monitoramento de progresso do upload
    monitorarProgressoQField();

    // Faz a requisição ao endpoint combinado
    const response = await fetch("/baixar_e_enviar_qfieldcloud/", {
      method: "GET",
      credentials: "include"
    });

    if (!response.ok) throw new Error("Falha ao gerar ou enviar o pacote.");

    // Baixa o arquivo ZIP localmente
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "pacote_projeto_qgis.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);

    showToast("✅ Projeto baixado e enviado para o QField Cloud com sucesso!");
  } catch (err) {
    console.error("[DEBUG] Erro ao baixar e enviar:", err);
    showToast("❌ Falha ao executar a operação combinada.");
  } finally {
    clearLoading(btnBaixarEnviar);
  }
});
