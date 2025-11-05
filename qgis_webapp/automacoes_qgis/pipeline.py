from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsVectorFileWriter, QgsField,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsCoordinateTransformContext, QgsRasterLayer
)
from qgis.PyQt.QtCore import QVariant
from qgis.analysis import QgsNativeAlgorithms
from processing.core.Processing import Processing
import processing
from pathlib import Path
from collections import defaultdict
from shapely.geometry import LineString, shape
from shapely.ops import unary_union
import requests
import geopandas as gpd
import json
import subprocess
import os


Processing.initialize()
QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

# ==================== BOOT ====================
# def init_qgis():
#     qgs = QgsApplication([], False)
#     qgs.initQgis()
#     Processing.initialize()
#     if not any(isinstance(p, QgsNativeAlgorithms) for p in QgsApplication.processingRegistry().providers()):
#         QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
#     return qgs


# ==================== HELPERS ====================
def save_layer(layer: QgsVectorLayer, file_path: Path, driver="ESRI Shapefile", layer_name=None):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = driver
    opts.fileEncoding = "UTF-8"
    if layer_name:
        opts.layerName = layer_name
    ctx = QgsProject.instance().transformContext()
    err, msg = QgsVectorFileWriter.writeAsVectorFormatV2(layer, str(file_path), ctx, opts)
    if err != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Falha ao salvar '{file_path}': {msg}")
    return file_path


def num_to_letters(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ==================== PIPELINE FUNCTIONS ====================
def dxf_to_shp(dxf_path: Path, out_path: Path):
    uri_lines = f"{dxf_path}|layername=entities|geometrytype=LineString"
    layer = QgsVectorLayer(uri_lines, "lotes_linhas", "ogr")
    if not layer.isValid():
        raise Exception("❌ Camada de linhas inválida.")
    save_layer(layer, out_path)
    print("Linhas salvas:", out_path)
    return layer


def corrigir_e_snap(linhas: QgsVectorLayer, paths):
    res_fix_lines = processing.run("native:fixgeometries", {
        "INPUT": linhas, "OUTPUT": str(paths["linhas_fix"])
    })
    linhas_fix = QgsVectorLayer(res_fix_lines["OUTPUT"], "linhas_fix", "ogr")

    res_snap = processing.run("native:snapgeometries", {
        "INPUT": linhas_fix, "REFERENCE_LAYER": linhas_fix,
        "TOLERANCE": 0.5, "BEHAVIOR": 0,
        "OUTPUT": str(paths["linhas_snap"])
    })
    linhas_snap = QgsVectorLayer(res_snap["OUTPUT"], "linhas_snap", "ogr")
    print("Linhas corrigidas e ajustadas:", linhas_snap.featureCount())
    return linhas_snap


def linhas_para_poligonos(linhas_snap, out_path):
    res_poly = processing.run("qgis:linestopolygons", {
        "INPUT": linhas_snap, "OUTPUT": str(out_path)
    })
    return QgsVectorLayer(res_poly["OUTPUT"], "lotes_poligonos", "ogr")


def corrigir_geometrias(layer_in, out_path):
    res_fix = processing.run("native:fixgeometries", {
        "INPUT": layer_in, "OUTPUT": str(out_path)
    })
    layer_out = QgsVectorLayer(res_fix["OUTPUT"], "corrigido", "ogr")
    print("Geometrias corrigidas:", layer_out.featureCount())
    return layer_out


def buffer_lotes(lotes_fix, out_path):
    res_buffer = processing.run("native:buffer", {
        "INPUT": lotes_fix, "DISTANCE": 0.05,
        "SEGMENTS": 5, "OUTPUT": str(out_path)
    })
    buffer_layer = QgsVectorLayer(res_buffer["OUTPUT"], "lotes_buffer", "ogr")
    print("Buffer aplicado:", buffer_layer.featureCount())
    return buffer_layer


def dissolve_para_quadras(buffer_layer, out_path):
    res_diss = processing.run("native:dissolve", {
        "INPUT": buffer_layer, "FIELD": [],
        "SEPARATE_DISJOINT": True, "OUTPUT": str(out_path)
    })
    return QgsVectorLayer(res_diss["OUTPUT"], "quadras_raw", "ogr")


def singlepart_quadras(quadras_raw, out_path):
    res_single = processing.run("native:multiparttosingleparts", {
        "INPUT": quadras_raw, "OUTPUT": str(out_path)
    })
    quadras = QgsVectorLayer(res_single["OUTPUT"], "quadras", "ogr")
    print("Quadras criadas:", quadras.featureCount())
    return quadras


def atribuir_letras_quadras(quadras, out_path):
    pr = quadras.dataProvider()
    if "quadra" not in [f.name() for f in quadras.fields()]:
        pr.addAttributes([QgsField("quadra", QVariant.String, len=8)])
        quadras.updateFields()

    idx = quadras.fields().indexOf("quadra")
    quadras.startEditing()
    feats = list(quadras.getFeatures())
    feats.sort(key=lambda f: f.geometry().centroid().asPoint().x())
    for i, ft in enumerate(feats, start=1):
        quadras.changeAttributeValue(ft.id(), idx, i)
    quadras.commitChanges()
    save_layer(quadras, out_path)
    print("Letras atribuídas às quadras:", out_path)
    return quadras


def gerar_pontos_rotulo(quadras, out_path):
    res_pt = processing.run("qgis:pointonsurface", {
        "INPUT": quadras, "ALL_PARTS": False, "OUTPUT": str(out_path)
    })
    pts = QgsVectorLayer(res_pt["OUTPUT"], "quadras_rotulo_pt", "ogr")
    print("Pontos de rótulo:", pts.featureCount())
    return pts


def join_lotes_quadras(lotes_fix, quadras, out_path):
    res_join = processing.run("native:joinattributesbylocation", {
        "INPUT": lotes_fix, "JOIN": quadras,
        "PREDICATE": [6, 0], "JOIN_FIELDS": ["quadra"],
        "METHOD": 0, "DISCARD_NONMATCHING": True,
        "OUTPUT": str(out_path)
    })
    return QgsVectorLayer(res_join["OUTPUT"], "lotes_com_quadra", "ogr")


def numerar_lotes(lotes_join, out_path):
    pr = lotes_join.dataProvider()
    if "lote_num" not in [f.name() for f in lotes_join.fields()]:
        pr.addAttributes([QgsField("lote_num", QVariant.Int)])
        lotes_join.updateFields()

    idx_lote = lotes_join.fields().indexOf("lote_num")
    lotes_join.startEditing()

    grouped = defaultdict(list)
    for feat in lotes_join.getFeatures():
        grouped[feat["quadra"]].append(feat)

    for quadra, feats in grouped.items():
        feats.sort(key=lambda f: f.geometry().centroid().asPoint().y(), reverse=True)
        for i, f in enumerate(feats, start=1):
            lotes_join.changeAttributeValue(f.id(), idx_lote, i)

    lotes_join.commitChanges()
    save_layer(lotes_join, out_path)
    print("Numeração dos lotes concluída:", out_path)
    return lotes_join


def extrair_ruas_overpass(quadras, out_dir):
    print("🌐 Baixando ruas do OSM com base no polígono das quadras...")

    if not quadras.crs().isValid():
        quadras.setCrs(QgsCoordinateReferenceSystem("EPSG:31983"))

    crs_src = quadras.crs()
    crs_dest = QgsCoordinateReferenceSystem("EPSG:4326")
    transformer = QgsCoordinateTransform(crs_src, crs_dest, QgsProject.instance().transformContext())

    geoms = []
    for f in quadras.getFeatures():
        g = f.geometry()
        g.transform(transformer)
        geoms.append(shape(json.loads(g.asJson())))

    union_poly = unary_union(geoms)
    if union_poly.geom_type != "Polygon":
        union_poly = union_poly.convex_hull

    coords_str = " ".join([f"{lat} {lon}" for lon, lat in union_poly.exterior.coords])
    query = f"""
    [out:json][timeout:180];
    way["highway"](poly:"{coords_str}");
    out tags geom;
    """

    # 🛰️ Servidores alternativos Overpass
    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.ru/api/interpreter",
        "https://overpass.nchc.org.tw/api/interpreter",
    ]

    resp = None
    success = False

    for url in overpass_servers:
        print(f"🔄 Tentando servidor: {url}")
        for attempt in range(3):  # tenta até 3 vezes por servidor
            try:
                resp = requests.post(url, data={"data": query}, timeout=90)
                if resp.status_code == 200:
                    success = True
                    break
                else:
                    print(f"⚠️ {url} retornou {resp.status_code}, tentando novamente...")
            except requests.exceptions.Timeout:
                print(f"⏰ Timeout no servidor {url} (tentativa {attempt + 1}/3)")
            except Exception as e:
                print(f"❌ Erro em {url}: {e}")

        if success:
            break

    if not success:
        raise RuntimeError(
            "❌ Todos os servidores Overpass falharam. O serviço pode estar temporariamente indisponível."
        )

    data = resp.json()
    elements = data.get("elements", [])
    print(f"✅ Total de vias retornadas: {len(elements)}")

    features = []
    for el in elements:
        if el["type"] == "way" and "geometry" in el:
            coords = [(n["lon"], n["lat"]) for n in el["geometry"]]
            if len(coords) >= 2:
                features.append({
                    "geometry": LineString(coords),
                    "name": el.get("tags", {}).get("name"),
                    "highway": el.get("tags", {}).get("highway"),
                    "surface": el.get("tags", {}).get("surface")
                })

    if features:
        gdf = gpd.GeoDataFrame(features, geometry="geometry", crs="EPSG:4326")
        gdf = gdf.to_crs(quadras.crs().authid())

        ruas_dir = out_dir / "ruas"
        ruas_dir.mkdir(parents=True, exist_ok=True)
        ruas_path = ruas_dir / "ruas_osm_detalhadas.gpkg"
        gdf.to_file(ruas_path, driver="GPKG", encoding="utf-8")
        print(f"✅ Camada de ruas detalhadas exportada: {ruas_path} (feições: {len(gdf)})")
    else:
        print("⚠️ Nenhuma via retornada. Tente expandir a área.")

def create_final_gpkg(layer_path: Path) -> Path:
    """
    Cria uma cópia GeoPackage chamada 'final_gpkg.gpkg' a partir da camada shapefile 'final.shp'.
    Retorna o caminho do novo arquivo .gpkg.
    """
    if not layer_path.exists():
        print(f"❌ Arquivo não encontrado: {layer_path}")
        return layer_path

    if layer_path.suffix.lower() != ".shp":
        print(f"⚠️ {layer_path.name} não é um shapefile, ignorando conversão.")
        return layer_path

    gpkg_path = layer_path.parent / "final_gpkg.gpkg"
    print(f"♻️ Gerando camada GeoPackage: {gpkg_path.name}")

    layer = QgsVectorLayer(str(layer_path), "final_gpkg", "ogr")
    if not layer.isValid():
        print(f"❌ Falha ao abrir {layer_path.name} para conversão.")
        return layer_path

    # Configura opções de gravação
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "final_gpkg"
    options.fileEncoding = "UTF-8"

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer,
        str(gpkg_path),
        QgsCoordinateTransformContext(),
        options
    )

    return gpkg_path

def adicionar_ortofoto(ortho_path: Path, layer_name: str, crs_alvo=None):
    """Adiciona uma ortofoto (ECW, TIFF, etc.) ao projeto QGIS."""
    if not ortho_path.exists():
        print(f"⚠️ Ortofoto não encontrada: {ortho_path}")
        return None

    rlayer = QgsRasterLayer(str(ortho_path), layer_name)
    if not rlayer.isValid():
        print(f"❌ Falha ao carregar ortofoto: {ortho_path}")
        return None

    if crs_alvo:
        rlayer.setCrs(QgsCoordinateReferenceSystem(crs_alvo))

    QgsProject.instance().addMapLayer(rlayer, False)
    print(f"🖼️ Ortofoto adicionada: {layer_name} ({ortho_path.name})")
    return rlayer

def converter_ecw_para_tif_reduzido(ecw_path: Path, escala: int = 25, limite_mb: int = 800) -> Path:
    """
    Converte uma ortofoto ECW em GeoTIFF reduzido, já comprimido e otimizado para QField.
    - escala: percentual da resolução original (25 = ¼ da resolução)
    - limite_mb: tamanho máximo aproximado desejado
    """
    if not ecw_path.exists() or ecw_path.suffix.lower() != ".ecw":
        raise ValueError(f"Arquivo inválido: {ecw_path}")

    output_path = ecw_path.with_name(ecw_path.stem + "_reduzido.tif")

    print(f"🎞️ Convertendo {ecw_path.name} → {output_path.name} ({escala}% da resolução)...")

    cmd = [
        "gdal_translate",
        "-of", "GTiff",
        "-outsize", f"{escala}%", f"{escala}%",
        "-co", "COMPRESS=JPEG",
        "-co", "JPEG_QUALITY=85",
        "-co", "TILED=YES",
        "-co", "BIGTIFF=IF_SAFER",
        str(ecw_path),
        str(output_path)
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro na conversão GDAL: {e.stderr}")
        raise RuntimeError("Falha ao converter ECW para TIFF reduzido.")

    tamanho_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✅ TIFF criado: {output_path} ({tamanho_mb:.1f} MB)")

    # Se ainda ficou grande, reduz mais (de forma adaptativa)
    if tamanho_mb > limite_mb:
        nova_escala = max(int(escala * (limite_mb / tamanho_mb) ** 0.5), 10)
        print(f"⚠️ Ainda acima de {limite_mb}MB → reduzindo novamente para {nova_escala}%...")
        output_reduced = ecw_path.with_name(ecw_path.stem + f"_{nova_escala}p.tif")

        subprocess.run([
            "gdal_translate",
            "-of", "GTiff",
            "-outsize", f"{nova_escala}%", f"{nova_escala}%",
            "-co", "COMPRESS=JPEG",
            "-co", "JPEG_QUALITY=55",
            "-co", "TILED=YES",
            "-co", "BIGTIFF=IF_SAFER",
            str(ecw_path),
            str(output_reduced)
        ], check=True)

        output_path.unlink(missing_ok=True)
        output_path = output_reduced
        tamanho_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"✅ TIFF reduzido para {tamanho_mb:.1f} MB")

    # Cria overviews (pyramids) para navegação rápida
    try:
        subprocess.run([
            "gdaladdo", "-r", "average", str(output_path), "2", "4", "8", "16", "32", "64"
        ], check=True)
        print("🧱 Overviews criados com sucesso.")
    except Exception as e:
        print(f"⚠️ Falha ao criar overviews: {e}")

    return output_path