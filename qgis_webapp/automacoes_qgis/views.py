import threading
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import os
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from pathlib import Path
from .criar_projeto_qgis import create_final_project
from pathlib import Path
from .pipeline import (
    dxf_to_shp, corrigir_e_snap, linhas_para_poligonos, dissolve_para_quadras,
    singlepart_quadras, atribuir_letras_quadras, gerar_pontos_rotulo, join_lotes_quadras,
    numerar_lotes, corrigir_geometrias, buffer_lotes, extrair_ruas_overpass, create_final_gpkg,
    converter_ecw_para_tif_reduzido
)
from .qgis_setup import init_qgis
from io import BytesIO
import zipfile
import shutil
from qfieldcloud_sdk import sdk
from dotenv import load_dotenv
from qgis.core import (
        QgsVectorLayer
)
from django.contrib.sessions.models import Session
import time

init_qgis()
load_dotenv()

def atualizar_progresso_thread(session_key, etapa, mensagem):
    """Atualiza o progresso diretamente na sessão, sem depender do objeto request."""
    session = Session.objects.get(session_key=session_key)
    data = session.get_decoded()
    data["progresso"] = {"etapa": etapa, "mensagem": mensagem}
    session.session_data = Session.objects.encode(data)
    session.save()
    print(f"📊 [{etapa}] {mensagem}")

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
    return render(request, 'automacoes_qgis/index.html')

@csrf_exempt
def resetar_progresso(request):
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["aguardando_ruas"] = False
    request.session["base_dir"] = None
    request.session.modified = True
    request.session.save()

    print("🔁 Progresso e sessão zerados (isolado por usuário)")
    return JsonResponse({"status": "ok", "progresso": request.session["progresso"]})

def executar_pipeline(upload_dir, dxf_path, ortho_path, session_key):
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

        atualizar_progresso_thread(session_key, 3, "🔧 Convertendo DXF em camadas vetoriais...")
        linhas = dxf_to_shp(dxf_path, paths["linhas"])

        atualizar_progresso_thread(session_key, 4, "🧩 Corrigindo e aplicando snap...")
        linhas_fix = corrigir_e_snap(linhas, paths)

        atualizar_progresso_thread(session_key, 5, "🏠 Gerando polígonos de lotes...")
        lotes_poly = linhas_para_poligonos(linhas_fix, paths["lotes_poly"])

        atualizar_progresso_thread(session_key, 6, "🧼 Corrigindo geometrias dos lotes...")
        lotes_fix = corrigir_geometrias(lotes_poly, paths["lotes_fix"])

        atualizar_progresso_thread(session_key, 7, "🗂️ Gerando buffers dos lotes...")
        lotes_buffer = buffer_lotes(lotes_fix, paths["lotes_buffer"])

        atualizar_progresso_thread(session_key, 8, "🧩 Dissolvendo lotes para criar polígonos das quadras...")
        quadras_raw = dissolve_para_quadras(lotes_buffer, paths["quadras_raw"])

        atualizar_progresso_thread(session_key, 9, "🧩 Criando polígonos das quadras...")
        quadras = singlepart_quadras(quadras_raw, paths["quadras_single2"])

        atualizar_progresso_thread(session_key, 10, "🧩 Atribuindo letras às quadras...")
        quadras = atribuir_letras_quadras(quadras, paths["quadras_single"])

        atualizar_progresso_thread(session_key, 11, "🗂️ Gerando pontos de rótulo das quadras...")
        gerar_pontos_rotulo(quadras, paths["quadras_pts"])

        atualizar_progresso_thread(session_key, 12, "🏠 Juntando lotes e quadras...")
        lotes_join = join_lotes_quadras(lotes_fix, quadras, paths["lotes_join"])

        atualizar_progresso_thread(session_key, 13, "🧩 Numerando lotes...")
        numerar_lotes(lotes_join, paths["arquivo_final"])

        atualizar_progresso_thread(session_key, 14, "🧩 Extraindo ruas do OpenStreetMap...")
        try:
            extrair_ruas_overpass(quadras, upload_dir)
        except RuntimeError as e:
            atualizar_progresso_thread(session_key, 98, f"⚠️ Falha no Overpass API: {e}")
            # Salva flag "aguardando_ruas" diretamente na sessão
            session = Session.objects.get(session_key=session_key)
            data = session.get_decoded()
            data["aguardando_ruas"] = True
            session.session_data = Session.objects.encode(data)
            session.save()
            return  # encerra a thread

        # Se deu certo, continua normalmente
        session = Session.objects.get(session_key=session_key)
        data = session.get_decoded()
        data["aguardando_ruas"] = False
        session.session_data = Session.objects.encode(data)
        session.save()

        atualizar_progresso_thread(session_key, 15, "🧩 Criando GeoPackage...")
        create_final_gpkg(paths["arquivo_final"])

        atualizar_progresso_thread(session_key, 16, "🗺️ Criando projeto QGIS final...")
        create_final_project(upload_dir, ortho_path=ortho_path)

        atualizar_progresso_thread(session_key, 17, "✅ Projeto QGIS criado com sucesso!")

    except Exception as e:
        atualizar_progresso_thread(session_key, 99, f"❌ Erro geral: {e}")


# -------------------------------
# CRIAÇÃO DO PROJETO QGIS
# -------------------------------
@csrf_exempt
def criar_projeto_qgis(request):
    global QFIELD_PROGRESS  # esse ainda é global, porque a exportação QFieldCloud é separada

    # 🔒 Reinicia progresso apenas da sessão atual
    request.session["progresso"] = {"etapa": 0, "mensagem": "Aguardando início"}
    request.session["aguardando_ruas"] = False
    request.session["base_dir"] = None
    request.session.modified = True

    request.session.save()

    QFIELD_PROGRESS = {"etapa": 0, "mensagem": ""}
    print("🚀 Novo processamento iniciado (isolado por sessão)")

    atualizar_progresso(request, 0, "Iniciando criação do projeto...")

    if request.method != "POST" or not request.FILES.get("arquivo"):
        return JsonResponse({"status": "erro", "mensagem": "Nenhum arquivo enviado."})

    # 📂 Salvar arquivos enviados
    arquivo = request.FILES["arquivo"]
    ortofoto_file = request.FILES.get("ortofoto")

    from datetime import datetime
    unique_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir = Path(settings.MEDIA_ROOT) / "uploads" / f"{Path(arquivo.name).stem}_{unique_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dxf_path = upload_dir / arquivo.name

    request.session["base_dir"] = str(upload_dir)
    request.session.modified = True

    atualizar_progresso(request, 1, "📂 Salvando arquivos enviados...")
    with open(dxf_path, "wb+") as destino:
        for chunk in arquivo.chunks():
            destino.write(chunk)

    ortho_path = None
    if ortofoto_file:
        ortho_dir = upload_dir / "ortofoto"
        ortho_dir.mkdir(parents=True, exist_ok=True)
        ortho_path = ortho_dir / ortofoto_file.name
        with open(ortho_path, "wb+") as destino:
            for chunk in ortofoto_file.chunks():
                destino.write(chunk)

        if ortho_path.suffix.lower() == ".ecw":
            try:
                atualizar_progresso(request, 2.5, "🧩 Convertendo ortofoto ECW para TIFF reduzido (pode demorar)...")
                # ortho_path = converter_ecw_para_tif_reduzido(ortho_path, escala=96)
                ortho_path = converter_ecw_para_tif_reduzido(ortho_path, escala=70)
                print(f"✅ Ortofoto convertida automaticamente: {ortho_path.name}")
            except Exception as e:
                print(f"⚠️ Erro ao converter ECW: {e}")

    # 🔄 Inicia o processamento em thread (não bloqueia o servidor)
    print("Sessão antes da thread:", request.session.get("progresso"))
    threading.Thread(
        target=executar_pipeline,
        args=(upload_dir, dxf_path, ortho_path, request.session.session_key),
        daemon=True
    ).start()

    return JsonResponse({
        "status": "sucesso",
        "mensagem": "🚀 Processamento iniciado. Acompanhe o progresso.",
        "projeto_path": f"/media/uploads/{arquivo.name}/project.qgz"
    })

def continuar_pipeline_pos_ruas(upload_dir, ortho_path, paths, request):
    """Executa a parte final da pipeline (após ruas serem baixadas)"""
    try:
        atualizar_progresso(request, 15, "🧩 Criando GeoPackage...")
        create_final_gpkg(paths["arquivo_final"])

        atualizar_progresso(request, 16, "🗺️ Criando projeto QGIS final...")
        create_final_project(upload_dir, ortho_path=ortho_path)

        atualizar_progresso(request, 17, "✅ Projeto QGIS criado com sucesso!")
        request.session["base_dir"] = str(upload_dir)
        request.session["aguardando_ruas"] = False
    except Exception as e:
        atualizar_progresso(request, 99, f"❌ Erro pós-Overpass: {e}")

@csrf_exempt
def tentar_overpass(request=None):
    global PROGRESSO

    base_dir = request.session.get("base_dir")
    if not base_dir:
        return JsonResponse({"status": "erro", "mensagem": "Nenhum projeto ativo encontrado."})

    upload_dir = Path(base_dir)
    quadras_path = upload_dir / "quadras" / "quadras.shp"

    if not quadras_path.exists():
        return JsonResponse({"status": "erro", "mensagem": "Quadras não encontradas."})

    try:
        atualizar_progresso(request, 14, "🔁 Tentando novamente extrair ruas...")
        quadras = QgsVectorLayer(str(quadras_path), "quadras", "ogr")

        extrair_ruas_overpass(quadras, upload_dir)
        atualizar_progresso(request, 15, "✅ Ruas obtidas com sucesso!")

        # continua o pipeline
        request.session["aguardando_ruas"] = False
        continuar_pipeline_pos_ruas(upload_dir, None, {}, request)

        return JsonResponse({"status": "sucesso", "mensagem": "Ruas extraídas e pipeline retomado."})

    except RuntimeError as e:
        atualizar_progresso(request, 98, f"⚠️ Nova falha no Overpass: {e}")
        return JsonResponse({"status": "falha_overpass", "mensagem": str(e)})


    except RuntimeError as e:
        atualizar_progresso(request, 98, f"⚠️ Nova falha no Overpass: {e}")
        return JsonResponse({
            "status": "falha_overpass",
            "mensagem": str(e)
        })

    except Exception as e:
        atualizar_progresso(request, 99, f"❌ Erro inesperado ao repetir Overpass: {e}")
        return JsonResponse({
            "status": "erro",
            "mensagem": str(e)
        })

def download_pacote_zip(request):
    """
    Empacota o projeto QGIS (project.qgs + shapefiles) para QField
    e envia como arquivo .zip para download.
    """
    base_dir = request.session.get("base_dir")
    if not base_dir:
        return HttpResponse("Nenhum diretório base encontrado na sessão. Gere o projeto antes.")

    upload_dir = Path(base_dir)
    project_file = upload_dir / "project_cloud.qgs"
    if not project_file.exists():
        return HttpResponse("Projeto QGIS não encontrado. Gere o projeto antes.")

    export_folder = upload_dir / "qfield_export"
    include_data_folders = ["final", "ruas", "quadras", "ortofoto"]

    try:
        package_project_for_qfield(
            project_file=project_file,
            export_folder=export_folder,   
            include_data_folders=include_data_folders
        )
    except Exception as e:
        import traceback
        print("❌ Erro ao empacotar:", traceback.format_exc())
        return JsonResponse({
            "status": "erro",
            "mensagem": f"Falha ao empacotar o projeto: {str(e)}"
        })

    # Compacta tudo dentro de qfield_export/
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(export_folder):
            for fname in files:
                if not fname.endswith((".gpkg", ".qgs", ".tif", ".vrt")):
                    continue
                full = Path(root) / fname
                arcname = str(full.relative_to(export_folder))
                zf.write(full, arcname)

    buffer.seek(0)

    # Retorna o ZIP como resposta HTTP (compatível com navegadores)
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="pacote_projeto_qgis.zip"'
    response["Content-Length"] = len(buffer.getvalue())
    return response

def package_project_for_qfield(project_file: Path, export_folder: Path, include_data_folders: list = None):
    if include_data_folders is None:
        include_data_folders = []

    export_folder.mkdir(parents=True, exist_ok=True)

    shutil.copy2(project_file, export_folder / project_file.name)

    for rel in include_data_folders:
        src = project_file.parent / rel
        dst = export_folder / rel
        if src.exists() and src.is_dir():
            shutil.copytree(src, dst)
        else:
            # 🔧 Tenta encontrar arquivos que comecem com o nome da pasta
            pattern = f"{rel} *"
            for file in project_file.parent.glob(pattern):
                dst_dir = export_folder / rel
                dst_dir.mkdir(exist_ok=True)
                shutil.copy2(file, dst_dir / file.name.replace(f"{rel} ", ""))
                print(f"📦 Movido: {file} → {dst_dir / file.name.replace(f'{rel} ', '')}")

    print(f"📦 Projeto empacotado em: {export_folder}")
    return export_folder


def enviar_para_qfieldcloud(request):
    global QFIELD_PROGRESS
    QFIELD_PROGRESS = {"etapa": 0, "mensagem": "Iniciando upload..."}

    username = os.getenv("QFIELD_USER")
    password = os.getenv("QFIELD_PASS")
    base_dir = Path(request.session.get("base_dir", ""))

    if not base_dir.exists():
        return JsonResponse({"status": "erro", "mensagem": "Base do projeto não encontrada."})

    # Detecta ortofoto e gera nome do projeto
    ortho_dir = base_dir / "ortofoto"
    ortho_files = list(ortho_dir.glob("*.tif"))
    if ortho_files:
        ortho_name = ortho_files[0].stem.replace("reduzido", "")
        ortho_name = ortho_name.replace("Ortofoto", "").replace("ortofoto", "").strip().replace(" ", "").replace("_", "")
        project_name = ortho_name or "Projeto_Sem_Nome"
    else:
        project_name = "Projeto_Sem_Ortofoto"

    # 🔹 Caminho base de envio (diretório atual do usuário)
    upload_dir = base_dir

    # 🔹 Login no QFieldCloud
    client = sdk.Client(url="https://app.qfield.cloud/api/v1/")
    client.login(username=username, password=password)

    proj = client.create_project(
        name=project_name,
        owner="OrganizacaoTeste",
        description="Exportado via Django",
        is_public=False
    )
    project_id = proj["id"]

    # 🔹 Lista arquivos relevantes da pasta atual
    pastas_necessarias = ["final", "quadras", "ruas", "ortofoto"]
    exts = {".gpkg", ".tif", ".vrt", ".png", ".qgs"}
    files = []

    for pasta in pastas_necessarias:
        dir_path = upload_dir / pasta
        if dir_path.exists():
            for root, _, fnames in os.walk(dir_path):
                for fname in fnames:
                    fpath = Path(root) / fname
                    if fpath.suffix.lower() in exts:
                        files.append(fpath)

    # inclui projeto e thumbnail
    project_qgs = upload_dir / "project_cloud.qgs"
    if project_qgs.exists():
        files.append(project_qgs)

    files.sort(key=lambda p: (p.suffix.lower() == ".qgs", p.as_posix()))
    total = len(files)
    print(f"📦 {total} arquivos encontrados para upload em {upload_dir}")

    # 🔹 Envio mantendo subpastas
    for i, file_path in enumerate(files, start=1):
        time.sleep(2)
        rel_path = file_path.relative_to(upload_dir).as_posix()
        QFIELD_PROGRESS = {"etapa": i, "mensagem": f"⬆️ Enviando {rel_path} ({i}/{total})"}
        print(f"➡️ Uploadando: {rel_path}")

        try:
            client.upload_file(
                project_id,
                sdk.FileTransferType.PROJECT,
                file_path,
                rel_path,
                show_progress=False,
            )
            print(f"✅ Upload concluído: {rel_path}")
        except Exception as e:
            print(f"⚠️ Falha ao enviar {rel_path}: {e}")

    QFIELD_PROGRESS = {"etapa": total, "mensagem": "✅ Upload concluído!"}
    print("✅ Finalizado!")
    return JsonResponse({"status": "sucesso", "projeto_id": project_id})

@csrf_exempt
def baixar_e_enviar_qfieldcloud(request):
    """
    Gera o pacote ZIP do projeto QGIS e envia ao QFieldCloud.
    Retorna o arquivo ZIP como download e também dispara o upload.
    """
    base_dir = request.session.get("base_dir")
    if not base_dir:
        return JsonResponse({"status": "erro", "mensagem": "Nenhum projeto ativo encontrado."})

    upload_dir = Path(base_dir)
    export_folder = upload_dir / "qfield_export"
    include_data_folders = ["final", "ruas", "quadras", "ortofoto"]

    # Etapa 1: gerar pacote ZIP
    try:
        package_project_for_qfield(
            project_file=upload_dir / "project_cloud.qgs",
            export_folder=export_folder,
            include_data_folders=include_data_folders
        )

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(export_folder):
                for fname in files:
                    if not fname.endswith((".gpkg", ".qgs", ".tif", ".vrt")):
                        continue
                    full = Path(root) / fname
                    arcname = str(full.relative_to(export_folder))
                    zf.write(full, arcname)

        buffer.seek(0)

    except Exception as e:
        import traceback
        print("❌ Erro ao empacotar:", traceback.format_exc())
        return JsonResponse({
            "status": "erro",
            "mensagem": f"Falha ao empacotar: {str(e)}"
        })

    # Etapa 2: enviar para QFieldCloud
    try:
        response_upload = enviar_para_qfieldcloud(request)
        print("✅ Projeto enviado para o QFieldCloud com sucesso.")
    except Exception as e:
        print(f"⚠️ Falha ao enviar para o QFieldCloud: {e}")
        response_upload = JsonResponse({
            "status": "erro",
            "mensagem": f"Falha ao enviar para QFieldCloud: {str(e)}"
        })

    # Etapa 3: retornar o ZIP para download
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="pacote_projeto_qgis.zip"'
    return response


def progresso_qfield(request):
    global QFIELD_PROGRESS
    return JsonResponse(QFIELD_PROGRESS)

