import threading
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import os
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from pathlib import Path
from .pipeline import (
    dxf_to_shp, corrigir_e_snap, linhas_para_poligonos, dissolve_para_quadras,
    singlepart_quadras, atribuir_letras_quadras, gerar_pontos_rotulo, join_lotes_quadras,
    numerar_lotes, corrigir_geometrias, buffer_lotes, extrair_ruas_overpass, create_final_gpkg,
    atribuir_ruas_e_esquinas_precision, atribuir_ruas_frente, calcular_medidas_e_azimutes, gerar_memoriais_em_lote,
    gerar_confrontacoes
)
from io import BytesIO
import zipfile
from django.contrib.sessions.models import Session
import time


def atualizar_progresso_thread(session_key, etapa, mensagem):
    try:
        session = Session.objects.get(session_key=session_key)
        data = session.get_decoded()
        data["progresso"] = {"etapa": etapa, "mensagem": mensagem}
        session.session_data = Session.objects.encode(data)
        session.save()
        print(f"📊 [{etapa}] {mensagem}")
    except Session.DoesNotExist:
        print(f"⚠️ Sessão {session_key} não encontrada (possível expiração). Progresso não salvo.")


def atualizar_progresso(request, etapa, mensagem):
    progresso = {"etapa": etapa, "mensagem": mensagem}
    request.session["progresso"] = progresso
    request.session.modified = True
    print(f"📊 [{etapa}] {mensagem}")

@never_cache
def progresso(request):
    progresso = request.session.get("progresso", {"etapa": 0, "mensagem": "Aguardando início"})
    resp = JsonResponse(progresso)
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp

def home(request):
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["aguardando_ruas"] = False
    request.session["base_dir"] = None
    request.session.modified = True
    return render(request, 'automacoes_memoriais/index.html')

@csrf_exempt
def resetar_progresso(request):
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["aguardando_ruas"] = False
    request.session["base_dir"] = None
    request.session.modified = True
    request.session.save()

    print("🔁 Progresso e sessão zerados (isolado por usuário)")
    return JsonResponse({"status": "ok", "progresso": request.session["progresso"]})

def executar_pipeline(upload_dir, dxf_path, session_key):
    try:
        paths = {
            "linhas": upload_dir / "lotes_linhas" / "lotes_linhas.shp",
            "linhas_fix": upload_dir / "temp" / "linhas_fix.shp",
            "linhas_snap": upload_dir / "temp" / "linhas_snap.shp",
            "lotes_poly": upload_dir / "lotes_poligonos" / "lotes_poligonos.shp",
            "lotes_fix": upload_dir / "lotes_poligonos" / "lotes_poligonos_fix.shp",
            "lotes_buffer": upload_dir / "lotes_poligonos" / "lotes_buffer.shp",
            "quadras_raw": upload_dir / "quadras" / "quadras_dissolve.shp",
            "quadras_single": upload_dir / "quadras" / "quadras.shp",
            "quadras_single2": upload_dir / "quadras" / "quadras_m2s.shp",
            "quadras_pts": upload_dir / "quadras" / "quadras_rotulo_pt.gpkg",
            "lotes_join": upload_dir / "lotes_poligonos" / "lotes_com_quadra.shp",
            "arquivo_final": upload_dir / "final" / "final.shp"
        }

        for p in paths.values():
            p.parent.mkdir(parents=True, exist_ok=True)

        atualizar_progresso_thread(session_key, 2, "🔧 Convertendo DXF em camadas vetoriais...")
        linhas = dxf_to_shp(dxf_path, paths["linhas"])

        atualizar_progresso_thread(session_key, 3, "🧩 Corrigindo e aplicando snap...")
        linhas_fix = corrigir_e_snap(linhas, paths)

        atualizar_progresso_thread(session_key, 4, "🏠 Gerando polígonos de lotes...")
        lotes_poly = linhas_para_poligonos(linhas_fix, paths["lotes_poly"])

        atualizar_progresso_thread(session_key, 5, "🧼 Corrigindo geometrias dos lotes...")
        lotes_fix = corrigir_geometrias(lotes_poly, paths["lotes_fix"])

        atualizar_progresso_thread(session_key, 6, "🗂️ Gerando buffers dos lotes...")
        lotes_buffer = buffer_lotes(lotes_fix, paths["lotes_buffer"])

        atualizar_progresso_thread(session_key, 7, "🧩 Dissolvendo lotes para criar polígonos das quadras...")
        quadras_raw = dissolve_para_quadras(lotes_buffer, paths["quadras_raw"])

        atualizar_progresso_thread(session_key, 8, "🧩 Criando polígonos das quadras...")
        quadras = singlepart_quadras(quadras_raw, paths["quadras_single2"])

        atualizar_progresso_thread(session_key, 9, "🧩 Atribuindo letras às quadras...")
        quadras = atribuir_letras_quadras(quadras, paths["quadras_single"])

        atualizar_progresso_thread(session_key, 10, "🗂️ Gerando pontos de rótulo das quadras...")
        gerar_pontos_rotulo(quadras, paths["quadras_pts"])

        atualizar_progresso_thread(session_key, 11, "🏠 Juntando lotes e quadras...")
        lotes_join = join_lotes_quadras(lotes_fix, quadras, paths["lotes_join"])

        atualizar_progresso_thread(session_key, 12, "🧩 Numerando lotes...")
        numerar_lotes(lotes_join, paths["arquivo_final"])

        atualizar_progresso_thread(session_key, 13, "🧩 Extraindo ruas do OpenStreetMap...")
        try:
            extrair_ruas_overpass(quadras, upload_dir)
        except RuntimeError as e:
            atualizar_progresso_thread(session_key, 98, f"⚠️ Falha no Overpass API: {e}")
            session = Session.objects.get(session_key=session_key)
            data = session.get_decoded()
            data["aguardando_ruas"] = True
            session.session_data = Session.objects.encode(data)
            session.save()
            return

        session = Session.objects.get(session_key=session_key)
        data = session.get_decoded()
        data["aguardando_ruas"] = False
        session.session_data = Session.objects.encode(data)
        session.save()

        atualizar_progresso_thread(session_key, 14, "🏷️ Atribuindo ruas e detectando lotes de esquina...")
        atribuir_ruas_frente(upload_dir)

        atualizar_progresso_thread(session_key, 15, "📐 Gerando confrontações dos lotes...")
        gerar_confrontacoes(upload_dir)

        atualizar_progresso_thread(session_key, 16, "📏 Calculando medidas e azimutes...")
        calcular_medidas_e_azimutes(upload_dir)

        atualizar_progresso_thread(session_key, 17, "📝 Gerando memoriais das quadras...")
        gerar_memoriais_em_lote(upload_dir)

        atualizar_progresso_thread(session_key, 18, "🚀 Pipeline concluído com sucesso!")

    except Exception as e:
        atualizar_progresso_thread(session_key, 99, f"❌ Erro geral: {e}")




# -------------------------------
# CRIAÇÃO DO PROJETO QGIS
# -------------------------------
@csrf_exempt
def gerar_memoriais(request):
    # Reinicia progresso desta sessão
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["aguardando_ruas"] = False
    request.session["base_dir"] = None
    request.session.modified = True
    request.session.save()

    print("🚀 Novo processamento de memoriais iniciado (isolado por sessão).")

    atualizar_progresso(request, 0, "Iniciando processamento...")

    # Verifica envio
    if request.method != "POST" or not request.FILES.get("arquivo"):
        return JsonResponse({"status": "erro", "mensagem": "Nenhum arquivo enviado."})

    arquivo = request.FILES["arquivo"]

    # Valida extensão
    ext = arquivo.name.lower().split(".")[-1]
    if ext not in ["dxf", "dwg"]:
        return JsonResponse({"status": "erro", "mensagem": "Envie um arquivo DXF ou DWG válido."})

    # Cria diretório único
    from datetime import datetime
    unique_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir = Path(settings.MEDIA_ROOT) / "uploads_memoriais" / f"{Path(arquivo.name).stem}_{unique_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dxf_path = upload_dir / arquivo.name

    request.session["base_dir"] = str(upload_dir)
    request.session.modified = True

    # Salva arquivo
    atualizar_progresso(request, 1, "📂 Salvando arquivos enviados...")
    with open(dxf_path, "wb+") as destino:
        for chunk in arquivo.chunks():
            destino.write(chunk)

    # Inicia thread de processamento
    threading.Thread(
        target=executar_pipeline,
        args=(upload_dir, dxf_path, request.session.session_key),
        daemon=True
    ).start()

    return JsonResponse({
        "status": "sucesso",
        "mensagem": "🚀 Processamento iniciado. Acompanhe o progresso.",
        "memoriais_path": f"/media/uploads_memoriais/{Path(arquivo.name).stem}_{unique_id}/memoriais/"
    })

@csrf_exempt
def baixar_memoriais(request):
    base_dir = request.session.get("base_dir")

    if not base_dir:
        return JsonResponse({"status": "erro", "mensagem": "Nenhum processamento foi encontrado para esta sessão."})

    memoriais_dir = Path(base_dir) / "memoriais"

    if not memoriais_dir.exists():
        return JsonResponse({"status": "erro", "mensagem": "Memoriais ainda não foram gerados."})

    # Cria ZIP em memória
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in memoriais_dir.glob("*.docx"):
            zipf.write(file, arcname=file.name)

    buffer.seek(0)

    response = HttpResponse(
        buffer,
        content_type="application/zip"
    )
    response["Content-Disposition"] = 'attachment; filename="memoriais.zip"'

    return response


