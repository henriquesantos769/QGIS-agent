import subprocess
import sys
import json
import zipfile
import os
from pathlib import Path
from datetime import datetime
from io import BytesIO

from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.conf import settings
from django.http import HttpResponse, JsonResponse

from .export_utils import (gerar_planilha_area_quadras_xlsx, gerar_planilha_area_quadras_prepare,
                           exportar_tabela_coordenadas_quadras, gerar_tabela_coordenadas_excel,
                           exportar_tabela_coordenadas_perimetro)

# ---------------------------------------------------------
# 📊 Progresso (session-based)
# ---------------------------------------------------------
def atualizar_progresso(request, etapa, mensagem):
    request.session["progresso"] = {
        "etapa": etapa,
        "mensagem": mensagem,
    }
    request.session.modified = True
    print(f"📊 [{etapa}] {mensagem}")


@never_cache
def progresso(request):
    base_dir = request.session.get("base_dir")

    # fallback inicial
    if not base_dir:
        return JsonResponse({"etapa": 0, "mensagem": "Aguardando início"})

    progress_file = Path(base_dir) / "progress.json"

    if not progress_file.exists():
        return JsonResponse({
            "etapa": 1,
            "mensagem": "Processamento iniciado..."
        })

    try:
        data = json.loads(progress_file.read_text(encoding="utf-8"))
        return JsonResponse(data)
    except Exception:
        return JsonResponse({
            "etapa": 99,
            "mensagem": "Erro ao ler progresso"
        })


# ---------------------------------------------------------
# 🏠 Home
# ---------------------------------------------------------
def home(request):
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["base_dir"] = None
    request.session.modified = True
    return render(request, "automacoes_memoriais/index.html")


# ---------------------------------------------------------
# 🔄 Reset
# ---------------------------------------------------------
@csrf_exempt
def resetar_progresso(request):
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["base_dir"] = None
    request.session.modified = True
    request.session.save()
    print("🔁 Progresso resetado para esta sessão")
    return JsonResponse({"status": "ok"})


# ---------------------------------------------------------
# 🚀 Gerar memoriais (ZIP do projeto QGIS)
# ---------------------------------------------------------
@csrf_exempt
def gerar_memoriais(request):
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["base_dir"] = None
    request.session.modified = True
    request.session.save()

    atualizar_progresso(request, 0, "Iniciando processamento...")

    if request.method != "POST" or "arquivo" not in request.FILES:
        return JsonResponse({
            "status": "erro",
            "mensagem": "Nenhum projeto QGIS enviado.",
        })

    arquivo = request.FILES["arquivo"]

    if not arquivo.name.lower().endswith(".zip"):
        return JsonResponse({
            "status": "erro",
            "mensagem": "Envie um projeto QGIS compactado (.zip).",
        })

    # -----------------------------------------------------
    # 📁 Cria diretório do job
    # -----------------------------------------------------
    unique_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir = (
        Path(settings.MEDIA_ROOT)
        / "uploads_memoriais"
        / f"job_{unique_id}"
    )
    upload_dir.mkdir(parents=True, exist_ok=True)

    zip_path = upload_dir / arquivo.name

    atualizar_progresso(request, 1, "📂 Salvando projeto QGIS...")
    with open(zip_path, "wb") as f:
        for chunk in arquivo.chunks():
            f.write(chunk)

    # -----------------------------------------------------
    # 📦 Extrai ZIP
    # -----------------------------------------------------
    atualizar_progresso(request, 2, "📦 Extraindo projeto QGIS...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(upload_dir)

    # -----------------------------------------------------
    # 🔎 Localiza .qgs / .qgz
    # -----------------------------------------------------
    projetos = list(upload_dir.rglob("*.qgs")) + list(upload_dir.rglob("*.qgz"))
    if not projetos:
        return JsonResponse({
            "status": "erro",
            "mensagem": "Nenhum arquivo .qgs ou .qgz encontrado no ZIP.",
        })

    project_path = projetos[0]

    request.session["base_dir"] = str(upload_dir)
    request.session.modified = True

    # -----------------------------------------------------
    # ⚙️ Subprocesso GIS (script isolado)
    # -----------------------------------------------------
    atualizar_progresso(request, 3, "⚙️ Iniciando processamento GIS...")

    script_path = Path(__file__).resolve().parent / "qgis_process.py"
    log_path = upload_dir / "process.log"

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"

    subprocess.Popen(
        [
            sys.executable,
            str(script_path),
            str(project_path),
            str(upload_dir),
            request.session.session_key,
        ],
        stdout=open(log_path, "a", encoding="utf-8"),
        stderr=open(log_path, "a", encoding="utf-8"),
        cwd=str(upload_dir),
        env=env,
    )

    return JsonResponse({
        "status": "sucesso",
        "mensagem": "🚀 Processamento iniciado. Acompanhe o progresso.",
    })


# ---------------------------------------------------------
# ⬇️ Download dos memoriais
# ---------------------------------------------------------
@csrf_exempt
def baixar_memoriais(request):
    base_dir = request.session.get("base_dir")
    json_path = gerar_planilha_area_quadras_prepare(base_dir)
    xlsx = gerar_planilha_area_quadras_xlsx(json_path)
    json_path_tabela_coordenadas = exportar_tabela_coordenadas_quadras(base_dir)
    xlsx_tabela_coordenadas = gerar_tabela_coordenadas_excel(json_path_tabela_coordenadas)
    print("XLSX gerado:", xlsx)
    print("XLSX tabela coordenadas gerado:", xlsx_tabela_coordenadas)
    json_path_tabela_coordenadas_perimetro = exportar_tabela_coordenadas_perimetro(base_dir)
    xlsx_tabela_coordenadas_perimetro = gerar_tabela_coordenadas_excel(json_path_tabela_coordenadas_perimetro)
    print("XLSX tabela coordenadas perimetro gerado:", xlsx_tabela_coordenadas_perimetro)   

    if not base_dir:
        return JsonResponse({
            "status": "erro",
            "mensagem": "Nenhum processamento encontrado para esta sessão.",
        })

    memoriais_dir = Path(base_dir) / "memoriais"
    if not memoriais_dir.exists():
        return JsonResponse({
            "status": "erro",
            "mensagem": "Memoriais ainda não foram gerados.",
        })

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in memoriais_dir.glob("*.docx"):
            zipf.write(file, arcname=file.name)

        for file in memoriais_dir.glob("*.xlsx"):
            zipf.write(file, arcname=file.name)

    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="memoriais.zip"'
    return response
