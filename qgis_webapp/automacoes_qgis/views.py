# automacoes_qgis/views.py
from django.shortcuts import render, redirect
from django.conf import settings
import folium
import geopandas as gpd
import os
from django.http import HttpResponse, FileResponse, JsonResponse
from pathlib import Path
from .ler_e_separar import load_and_split_dxf
from .linhas_para_poligonos import convert_lines_to_polygons
from .unir_atributos_byloc_lotes import join_by_location_summary_lotes
from .unir_atributos_byloc_quadras import join_by_location_summary_quadras
from .unir_atributos_byloc_final import join_by_location_summary_final
from .criar_projeto_qgis import create_project
from pathlib import Path
from io import BytesIO
import zipfile


def upload_dxf(request):
    """Executa todo o fluxo de forma síncrona (rápido)."""
    progresso = []
    mensagem_final = None
    request.session["etapa"] = 0

    if request.method == "POST" and request.FILES.get("arquivo"):
        arquivo = request.FILES["arquivo"]

        # Diretório temporário
        upload_dir = os.path.join(settings.BASE_DIR, "media", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        caminho_arquivo = os.path.join(upload_dir, arquivo.name)

        # Salva o arquivo DXF
        with open(caminho_arquivo, "wb+") as destino:
            for chunk in arquivo.chunks():
                destino.write(chunk)

        try:
            # Etapa 1 - Ler e separar DXF
            progresso.append("📂 Lendo e separando DXF...")
            load_and_split_dxf(caminho_arquivo, upload_dir)
            request.session["etapa"] = 1
            progresso.append("✅ DXF separado com sucesso.")

            # Etapa 2 - Linhas para polígonos
            progresso.append("🔷 Convertendo linhas para polígonos...")
            convert_lines_to_polygons(upload_dir)
            request.session["etapa"] = 2
            progresso.append("✅ Linhas convertidas e geometrias corrigidas.")

            # Etapa 3 - Unir atributos (lotes)
            progresso.append("🧩 Unindo atributos dos Lotes...")
            join_by_location_summary_lotes(upload_dir)
            request.session["etapa"] = 3
            progresso.append("✅ Atributos dos Lotes unidos.")

            # Etapa 4 - Unir atributos (quadras)
            progresso.append("🧱 Unindo atributos das Quadras...")
            join_by_location_summary_quadras(upload_dir)
            request.session["etapa"] = 4
            progresso.append("✅ Atributos das Quadras unidos.")

            # Etapa 5 - Unir final
            progresso.append("🗂️ Unindo atributos finais...")
            join_by_location_summary_final(upload_dir)
            request.session["etapa"] = 5
            progresso.append("✅ Atributos finais unidos com sucesso.")

            request.session["base_dir"] = upload_dir
            mensagem_final = "🎉 Processamento concluído com sucesso!"

        except Exception as e:
            mensagem_final = f"❌ Erro durante o processamento: {str(e)}"

    return render(request, "automacoes_qgis/upload.html", {
        "mensagem_final": mensagem_final,
        "progresso": progresso
    })


def converter_para_qgis(request):
    base_dir = request.session.get("base_dir")
    mensagem = None
    arquivo_qgz = None

    if not base_dir:
        mensagem = "⚠️ Nenhum diretório de trabalho encontrado. Faça o upload primeiro."
    else:
        try:
            resultado = create_project(base_dir)
            request.session["etapa"] = 6
            mensagem = resultado
            arquivo_qgz = Path(base_dir) / "projeto_final_rotulado.qgz"
        except Exception as e:
            mensagem = f"❌ Erro ao criar o projeto QGIS: {e}"

    return render(request, "automacoes_qgis/final.html", {
        "mensagem": mensagem,
        "arquivo_qgz": arquivo_qgz
    })

def download_pacote_zip(request):
    """Compacta o diretório do job (projeto + shapefiles) e envia como .zip."""
    base_dir = request.session.get("base_dir")
    if not base_dir:
        return HttpResponse("Nenhum diretório encontrado.")

    base_path = Path(base_dir)
    qgz = base_path / "projeto_final_rotulado.qgz"
    if not qgz.exists():
        return HttpResponse("Projeto QGIS não encontrado. Gere o projeto antes.")

    # Compacta tudo que está dentro de base_dir (mantendo caminhos relativos)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base_dir):
            for fname in files:
                full = Path(root) / fname
                # caminho dentro do zip relativo à pasta base_dir
                arcname = str(full.relative_to(base_path))
                zf.write(full, arcname)

    buffer.seek(0)
    resp = FileResponse(buffer, as_attachment=True,
                        filename="pacote_projeto_qgis.zip",
                        content_type="application/zip")
    # (opcional) tamanho para alguns navegadores
    resp["Content-Length"] = buffer.getbuffer().nbytes
    return resp


def visualizar_shp(request):
    base_dir = request.session.get("base_dir")
    if not base_dir:
        return HttpResponse("<h3>Nenhum diretório de trabalho encontrado. Faça o upload primeiro.</h3>")

    shp_files = []
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".shp"):
                rel_path = os.path.relpath(os.path.join(root, file), base_dir)
                shp_files.append(rel_path)

    if request.method == "POST":
        arquivo = request.POST.get("shapefile")
        if arquivo:
            shp_path = os.path.join(base_dir, arquivo)

            try:
                gdf = gpd.read_file(shp_path)

                if gdf.crs is None:
                    gdf.set_crs(epsg=31982, inplace=True)

                gdf = gdf.to_crs(epsg=4326)
                bounds = gdf.total_bounds
                m = folium.Map()
                m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

                folium.GeoJson(
                    gdf,
                    name=arquivo,
                    tooltip=folium.GeoJsonTooltip(fields=gdf.columns[:3].tolist())
                ).add_to(m)

                folium.LayerControl().add_to(m)
                mapa_html = m._repr_html_()

                return render(request, "automacoes_qgis/ver_mapa.html", {
                    "mapa": mapa_html,
                    "shapefile": arquivo
                })
            except Exception as e:
                return HttpResponse(f"<h3>Erro ao abrir o shapefile: {e}</h3>")

    return render(request, "automacoes_qgis/visualizar.html", {"shp_files": shp_files})


def voltar_para_etapa(request):
    etapa = request.session.get("etapa", 0)
    etapas_rotas = {
        0: "upload_dxf",
        1: "upload_dxf",
        2: "linhas_poligonos",
        3: "unir_lotes",
        4: "unir_quadras",
        5: "unir_final",
        6: "pagina_final",
    }
    destino = etapas_rotas.get(etapa, "upload_dxf")
    return redirect(destino)


def status_progresso(request):
    etapa = request.session.get("etapa", 0)
    status_textos = {
        0: "Aguardando início...",
        1: "📂 Lendo e separando DXF...",
        2: "🔷 Convertendo linhas → polígonos...",
        3: "🧩 Unindo atributos (Lotes)...",
        4: "🧱 Unindo atributos (Quadras)...",
        5: "🗂️ Unindo atributos finais...",
        6: "🎉 Processamento concluído!",
        -1: "❌ Erro durante o processamento."
    }
    progresso_pct = int((max(etapa, 0) / 6) * 100)
    return JsonResponse({
        "etapa": etapa,
        "texto": status_textos.get(etapa, "Desconhecido"),
        "progresso": progresso_pct
    })
