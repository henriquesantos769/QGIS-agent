from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsVectorFileWriter, QgsField,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsCoordinateTransformContext, QgsRasterLayer, QgsWkbTypes, QgsSpatialIndex,
    QgsGeometry, QgsPointXY,
    QgsProject, QgsFeature
)
from qgis.PyQt.QtCore import QVariant
from qgis.analysis import QgsNativeAlgorithms
from processing.core.Processing import Processing
import processing
from pathlib import Path
from collections import defaultdict
from shapely.geometry import LineString, shape
from shapely.ops import unary_union
from shapely.ops import nearest_points
import requests
import geopandas as gpd
import json
import numpy as np
import subprocess
import os
import math
import pandas as pd

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

def calcular_azimute(p1, p2):
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    ang = math.degrees(math.atan2(dx, dy))
    return (ang + 360) % 360

def gerar_vertices_quadras(
    upload_dir: Path,
    quadras_dissolve_gpkg: str = "quadras_dissolve.gpkg",
    out_path: Path = None,
):
    """
    Gera uma camada POINT com os vértices das quadras a partir do quadras_dissolve.

    Regras (compatível com teu memorial):
      - P01 = vértice mais ao norte (maior Y)
      - sequência P02..Pn seguindo a ordem do anel externo da geometria (sem inverter sentido)

    Campos:
      - quadra (String)
      - vertice (String)  -> P01, P02...
      - x (Double)
      - y (Double)
    """

    from qgis.core import (
        QgsVectorLayer, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
        QgsPointXY, QgsField, QgsFields, QgsWkbTypes
    )
    from PyQt5.QtCore import QVariant

    # -----------------------------
    # paths
    # -----------------------------
    quadras_path = upload_dir / "quadras" / quadras_dissolve_gpkg
    if out_path is None:
        out_path = upload_dir / "quadras" / "quadras_vertices.gpkg"

    quadras = QgsVectorLayer(str(quadras_path), "quadras_dissolve", "ogr")
    if not quadras.isValid():
        raise RuntimeError(f"Camada inválida: {quadras_path}")

    crs = quadras.crs()

    # -----------------------------
    # cria layer em memória (POINT)
    # -----------------------------
    mem = QgsVectorLayer(f"Point?crs={crs.authid()}", "quadras_vertices_tmp", "memory")
    pr = mem.dataProvider()

    pr.addAttributes([
        QgsField("quadra", QVariant.String),
        QgsField("vertice", QVariant.String),
        QgsField("x", QVariant.Double),
        QgsField("y", QVariant.Double),
    ])
    mem.updateFields()

    # -----------------------------
    # helper: pega anel externo
    # -----------------------------
    def extrair_anel_externo(geom: QgsGeometry):
        """
        Retorna lista de QgsPointXY do anel externo (sem o ponto repetido final).
        Suporta Polygon e MultiPolygon.
        """
        if geom is None or geom.isEmpty():
            return []

        if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
            return []

        if geom.isMultipart():
            mp = geom.asMultiPolygon()
            if not mp or not mp[0] or not mp[0][0]:
                return []
            ring = mp[0][0]  # primeira parte, anel externo
        else:
            p = geom.asPolygon()
            if not p or not p[0]:
                return []
            ring = p[0]  # anel externo

        pts = [QgsPointXY(pt.x(), pt.y()) for pt in ring]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        return pts

    # -----------------------------
    # gera pontos P01..Pn
    # -----------------------------
    feats_out = []

    for ft in quadras.getFeatures():
        geom = ft.geometry()
        pts = extrair_anel_externo(geom)
        if len(pts) < 3:
            continue

        quadra_val = ft["quadra"]
        quadra_val = str(quadra_val) if quadra_val is not None else ""

        # P01 = mais ao norte (maior Y)
        idx_inicio = max(range(len(pts)), key=lambda i: pts[i].y())

        # reordena circularmente (mesma ideia do memorial)
        pts_ord = pts[idx_inicio:] + pts[:idx_inicio]

        for i, p in enumerate(pts_ord, start=1):
            f = QgsFeature(mem.fields())
            f.setGeometry(QgsGeometry.fromPointXY(p))
            f["quadra"] = quadra_val
            f["vertice"] = f"P{str(i).zfill(2)}"
            f["x"] = float(p.x())
            f["y"] = float(p.y())
            feats_out.append(f)

    pr.addFeatures(feats_out)
    mem.updateExtents()

    # -----------------------------
    # salva em GPKG usando teu save_layer
    # -----------------------------
    # (se já existir, remove pra não acumular)
    if out_path.exists():
        out_path.unlink()

    save_layer(mem, out_path, driver="GPKG", layer_name="quadras_vertices")

    layer_vertices = QgsVectorLayer(str(out_path), "quadras_vertices", "ogr")
    if not layer_vertices.isValid():
        raise RuntimeError(f"Falha ao carregar saída: {out_path}")

    QgsProject.instance().addMapLayer(layer_vertices)

    print(f"✅ Camada de vértices criada: {out_path}")
    return layer_vertices

def detectar_fuso_utm(path_dxf: str):
    MAPA_SIRGAS = {
        21: 31981,
        22: 31982,
        23: 31983,
        24: 31984,  # 🌍 Seu caso
        25: 31985
    }

    gdf = gpd.read_file(path_dxf)
    if gdf.empty:
        raise Exception("DXF sem geometrias.")

    resultados = []
    for zona in [22, 23, 24, 25]:
        epsg = 32700 + zona  # WGS84 / UTM zona S
        try:
            gdf_tmp = gdf.set_crs(epsg=epsg).to_crs(4326)
            c = gdf_tmp.geometry.unary_union.centroid
            resultados.append((zona, epsg, c.x, c.y))
        except Exception as e:
            resultados.append((zona, epsg, str(e), None))

    for zona, epsg, lon, lat in resultados:
        print(f"Zona {zona} → EPSG:{epsg} → lon={lon}, lat={lat}")

    # escolha a zona onde lon está entre -75 e -30 (Brasil)
    zona_ok = min(
        [r for r in resultados if isinstance(r[2], (int, float, float))],
        key=lambda r: abs(r[2] + 39)  # aproxima de -39° (Bahia)
    )

    fuso_detectado = zona_ok[0]           
    epsg_sirgas = MAPA_SIRGAS[fuso_detectado]

    return fuso_detectado, epsg_sirgas

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

def dxf_text_to_gpkg(dxf_path: Path, out_gpkg: Path, layer_name="dxf_textos"):
    uri_text = f"{dxf_path}|layername=entities|geometrytype=Point"
    layer = QgsVectorLayer(uri_text, layer_name, "ogr")

    if not layer.isValid():
        raise Exception("❌ Camada de textos (TEXT) inválida.")

    save_layer(
        layer,
        out_gpkg,
        driver="GPKG",
        layer_name=layer_name
    )

    print("Textos DXF (TEXT) salvos em GPKG:", out_gpkg)
    return layer

def gerar_pontos_area_lotes(lotes_layer: QgsVectorLayer, out_path: Path):
    """
    Cria uma camada de pontos (centro dos lotes)
    contendo a área REAL do polígono correspondente.
    """

    if not lotes_layer or not lotes_layer.isValid():
        raise ValueError("Camada de lotes inválida.")

    # --------------------------------------------------
    # 1) Gera pontos internos
    # --------------------------------------------------
    pts = processing.run(
        "qgis:pointonsurface",
        {
            "INPUT": lotes_layer,
            "ALL_PARTS": False,
            "OUTPUT": "memory:"
        }
    )["OUTPUT"]

    # --------------------------------------------------
    # 2) Adiciona campo de área
    # --------------------------------------------------
    pr = pts.dataProvider()
    if "area_m2" not in [f.name() for f in pts.fields()]:
        pr.addAttributes([QgsField("area_m2", QVariant.Double)])
        pts.updateFields()

    idx_area = pts.fields().indexOf("area_m2")

    # --------------------------------------------------
    # 3) Criar índice espacial dos polígonos
    # --------------------------------------------------
    lotes_index = QgsSpatialIndex(lotes_layer.getFeatures())

    # --------------------------------------------------
    # 4) Transferir área correta do polígono
    # --------------------------------------------------
    pts.startEditing()

    for p in pts.getFeatures():
        geom_p = p.geometry()

        # busca candidatos
        candidatos = lotes_index.intersects(geom_p.boundingBox())

        area = 0.0
        for fid in candidatos:
            feat = lotes_layer.getFeature(fid)
            if feat.geometry().contains(geom_p):
                area = feat.geometry().area()
                break

        pts.changeAttributeValue(p.id(), idx_area, area)

    pts.commitChanges()

    # --------------------------------------------------
    # 5) Salvar camada
    # --------------------------------------------------
    save_layer(
        pts,
        file_path=out_path,
        driver="GPKG",
        layer_name="lotes_rotulo_area"
    )

    print(f"✅ Camada de rótulos de área criada: {out_path}")
    return pts

def criar_camada_linhas(
    file_path,
    crs_epsg="EPSG:31983",
    layer_name="limites_lotes"
):
    """
    Cria uma camada LineString com:
    - id (auto incremental)
    - name (texto)

    Salva no caminho informado via save_layer().
    """

    # --------------------------------------------------
    # 1) Criar camada temporária em memória
    # --------------------------------------------------
    layer = QgsVectorLayer(
        f"LineString?crs={crs_epsg}",
        layer_name,
        "memory"
    )

    if not layer.isValid():
        raise RuntimeError("❌ Falha ao criar camada de linhas.")

    provider = layer.dataProvider()

    # --------------------------------------------------
    # 2) Campos
    # --------------------------------------------------
    provider.addAttributes([
        QgsField("name", QVariant.String),
    ])
    layer.updateFields()

    # --------------------------------------------------
    # 3) Gerador automático de ID
    # --------------------------------------------------
    layer.startEditing()
    for i, f in enumerate(layer.getFeatures(), start=1):
        f["id"] = i
        layer.updateFeature(f)
    layer.commitChanges()

    # --------------------------------------------------
    # 4) Salvar usando sua função
    # --------------------------------------------------
    save_layer(layer, file_path, driver="GPKG", layer_name=layer_name)

    # --------------------------------------------------
    # 5) Recarregar camada salva
    # --------------------------------------------------
    final_layer = QgsVectorLayer(str(file_path), layer_name, "ogr")
    if not final_layer.isValid():
        raise RuntimeError("❌ Camada salva mas não pôde ser recarregada.")

    QgsProject.instance().addMapLayer(final_layer)

    return final_layer

def gerar_segmentos_lotes(lotes_layer: QgsVectorLayer, output_path: Path, crs=None):
    """
    Gera uma camada de segmentos (frentes) a partir da camada de lotes
    e salva em GPKG usando a função save_layer() do projeto.
    """
    if not lotes_layer or not lotes_layer.isValid():
        raise RuntimeError("Camada de lotes inválida em gerar_segmentos_lotes().")

    print("🔧 Gerando camada de segmentos dos lotes...")

    def _to_int(value):
        if value is None:
            return None
        # trata QVariant
        if hasattr(value, "toString"):
            value = value.toString()
        # tenta converter literal
        try:
            return int(value)
        except:
            return None

    if crs is None:
        crs = lotes_layer.crs().authid()

    seg_layer = QgsVectorLayer(f"LineString?crs={crs}", "frentes_segmentos", "memory")
    prov = seg_layer.dataProvider()

    prov.addAttributes([
        QgsField("lote_num", QVariant.Int),
        QgsField("segment_id", QVariant.Int),
        QgsField("comprimento", QVariant.Double),
        QgsField("azimute", QVariant.Double),
    ])
    seg_layer.updateFields()

    for lot_feat in lotes_layer.getFeatures():
        geom: QgsGeometry = lot_feat.geometry()
        if geom is None or geom.isEmpty():
            continue

        # pega id do lote (ajuste se o nome do campo for outro)
        lote_num = lot_feat["lote_num"]

        rings = []

        # Garantir que estamos tratando polígonos
        if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
            # se aparecer linha/ponto aqui, ignoramos
            continue

        if QgsWkbTypes.isMultiType(geom.wkbType()):
            # MultiPolígono: lista de polígonos, cada um com seus anéis
            multipoly = geom.asMultiPolygon()
            for poly in multipoly:
                for ring in poly:  # ring = lista de vértices
                    rings.append(ring)
        else:
            # Polígono simples: lista de anéis
            poly = geom.asPolygon()
            for ring in poly:
                rings.append(ring)

        # agora percorremos todos os anéis do lote
        seg_index = 0  # segment_id por lote
        for ring in rings:
            n = len(ring)
            if n < 2:
                continue

            # em asPolygon/asMultiPolygon, o primeiro ponto normalmente se repete no final
            # então usamos até n-1 para não duplicar o segmento de fechamento
            for i in range(n - 1):
                p1 = QgsPointXY(ring[i])
                p2 = QgsPointXY(ring[i + 1])
                seg_geom = QgsGeometry.fromPolylineXY([p1, p2])

                comprimento = seg_geom.length()
                az = calcular_azimute(p1, p2)

                feat = QgsFeature(seg_layer.fields())
                feat.setAttribute("lote_num", _to_int(lote_num))
                feat.setAttribute("segment_id", seg_index)
                feat.setAttribute("comprimento", float(comprimento))
                feat.setAttribute("azimute", float(az))
                feat.setGeometry(seg_geom)

                prov.addFeature(feat)
                seg_index += 1

    seg_layer.updateExtents()

    # 💾 Salvar em GPKG usando seu helper
    print(f"💾 Salvando camada de segmentos em: {output_path}")
    save_layer(
        seg_layer,
        output_path,
        driver="GPKG",
        layer_name="frentes_segmentos"
    )

    print("✅ Camada de segmentos gerada e salva.")
    return seg_layer


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


def atribuir_letras_quadras(quadras, out_path, driver="GPKG"):
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
    save_layer(quadras, out_path, driver=driver)
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


def numerar_lotes(lotes_join: QgsVectorLayer, out_path: Path):
    """
    Numera os lotes dentro de cada quadra usando ângulo polar a partir
    do centróide da quadra. Estável, replicável e ideal para memoriais.

    Mantém o mesmo campo `lote_num` do pipeline atual.
    """
    def is_polygon_valid(geom):
        if geom is None:
            return False
        if geom.type() != QgsWkbTypes.PolygonGeometry:
            return False
        if not geom.isGeosValid():   # evita polígonos degenerados
            return False
        if geom.area() < 1e-2:       # evita pedaços minúsculos / lixo
            return False
        return True

    pr = lotes_join.dataProvider()

    # Garante o campo lote_num
    if "lote_num" not in [f.name() for f in lotes_join.fields()]:
        pr.addAttributes([QgsField("lote_num", QVariant.Int)])
        lotes_join.updateFields()

    idx_lote = lotes_join.fields().indexOf("lote_num")

    # Agrupa features por quadra
    grouped = defaultdict(list)
    for feat in lotes_join.getFeatures():
        if not is_polygon_valid(feat.geometry()):
            continue
        grouped[str(feat["quadra"])].append(feat)

    lotes_join.startEditing()

    for quadra_val, feats in grouped.items():

        # ---------------------------
        # 1. Calcula o centróide da quadra
        # ---------------------------
        # quadra_val é valor do campo, não geom. da quadra;
        # então pegamos os lotes e unimos para formar quadra
        geoms = [f.geometry() for f in feats]
        quadra_union = geoms[0]
        for g in geoms[1:]:
            quadra_union = quadra_union.combine(g)

        centro = quadra_union.centroid().asPoint()

        # ---------------------------
        # 2. Calcula ângulo polar de cada lote
        # ---------------------------
        lotes_com_ang = []
        for f in feats:
            c = f.geometry().centroid().asPoint()
            dx = c.x() - centro.x()
            dy = c.y() - centro.y()

            # Ângulo polar, ajustado para sentido HORÁRIO (como Métrica)
            ang = math.degrees(math.atan2(dy, dx))
            ang = (450 - ang) % 360  # gira e ajusta para 0° no norte, sentido horário

            lotes_com_ang.append((ang, f))

        # ---------------------------
        # 3. Ordena os lotes pelo ângulo
        # ---------------------------
        lotes_com_ang.sort(key=lambda x: x[0])

        # ---------------------------
        # 4. Atribui numeração crescente
        # ---------------------------
        for i, (_, feat) in enumerate(lotes_com_ang, start=1):
            lotes_join.changeAttributeValue(feat.id(), idx_lote, i)

    lotes_join.commitChanges()

    # Mantém a compatibilidade com tua função original
    save_layer(lotes_join, out_path)
    print("📌 Numeração dos lotes concluída (ângulo polar):", out_path)
    return lotes_join

def gerar_pontos_rotulo_lotes(lotes_path: Path, out_path: Path):
    """
    Cria uma camada de pontos (um por lote) para rótulos,
    usando pointOnSurface (garantido dentro do polígono).

    Parâmetros:
    - lotes_path: caminho do arquivo dos lotes (ex: final_gpkg.gpkg)
    - out_path: caminho de saída da camada de rótulos
    """

    # --------------------------------------------------
    # 1) Carrega camada de lotes
    # --------------------------------------------------
    lotes_layer = QgsVectorLayer(str(lotes_path), "lotes_base", "ogr")

    if not lotes_layer.isValid():
        raise ValueError(f"❌ Camada inválida: {lotes_path}")

    # --------------------------------------------------
    # 2) Gerar pontos internos (point on surface)
    # --------------------------------------------------
    res = processing.run(
        "qgis:pointonsurface",
        {
            "INPUT": lotes_layer,
            "ALL_PARTS": False,
            "OUTPUT": "memory:"
        }
    )

    pontos = res["OUTPUT"]

    # --------------------------------------------------
    # 3) Garantir campo 'lote_num'
    # --------------------------------------------------
    pr = pontos.dataProvider()
    fields = [f.name() for f in pontos.fields()]

    if "lote_num" not in fields:
        pr.addAttributes([QgsField("lote_num", QVariant.Int)])
        pontos.updateFields()

    idx_lote = pontos.fields().indexOf("lote_num")

    # --------------------------------------------------
    # 4) Copiar valor do lote original
    # --------------------------------------------------
    pontos.startEditing()

    # mapa id_feature → lote_num
    mapa_lotes = {
        f.id(): f["lote_num"]
        for f in lotes_layer.getFeatures()
    }

    for f in pontos.getFeatures():
        if f.id() in mapa_lotes:
            pontos.changeAttributeValue(f.id(), idx_lote, mapa_lotes[f.id()])

    pontos.commitChanges()

    # --------------------------------------------------
    # 5) Salvar camada
    # --------------------------------------------------
    save_layer(
        layer=pontos,
        file_path=out_path,
        driver="GPKG",
        layer_name="lotes_rotulos"
    )

    print(f"✅ Camada de rótulos criada com sucesso: {out_path}")

    return pontos

def extrair_ruas_overpass(quadras, out_dir, DEFAULT_CRS="EPSG:31983"):
    print("🌐 Baixando ruas do OSM com base no polígono das quadras...")

    if not quadras.crs().isValid():
        quadras.setCrs(QgsCoordinateReferenceSystem(DEFAULT_CRS))
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
    way["highway"~"residential|tertiary|secondary|primary|unclassified|living_street"](poly:"{coords_str}");
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
        # Ainda em EPSG:4326
        gdf = gpd.GeoDataFrame(features, geometry="geometry", crs="EPSG:4326")

        gdf["name"] = gdf["name"].replace("", pd.NA)

        mask_sem_nome = gdf["name"].isna()

        # Quantidade exata de ruas sem nome
        n = mask_sem_nome.sum()

        # Gera somente os nomes necessários
        nomes_padrao = [f"Rua Sem Denominação {i:02d}" for i in range(1, n + 1)]

        # Atribuição correta: tamanhos compatíveis
        gdf.loc[mask_sem_nome, "name"] = nomes_padrao

        # 🔹 Usa as geometrias Shapely das quadras (já em EPSG:4326)
        area_union = unary_union(geoms)  # geoms é lista de Shapely Polygons

        # (Opcional) encolher um pouquinho pra não pegar rua muito longe da borda
        # 0.0003 ~ 30m, ajuste se precisar
        area_union = area_union.buffer(0.0003)

        # 🔹 Filtra só as ruas que realmente intersectam a área das quadras
        gdf = gdf[gdf.intersects(area_union)]

        # Agora reprojeta pro mesmo CRS da camada de quadras
        gdf = gdf.to_crs(quadras.crs().authid())
        gdf["rua_id"] = range(1, len(gdf) + 1)
        
        ruas_dir = out_dir / "ruas"
        ruas_dir.mkdir(parents=True, exist_ok=True)
        ruas_path = ruas_dir / "ruas_osm_detalhadas.gpkg"
        gdf.to_file(ruas_path, driver="GPKG", encoding="utf-8")
        print(f"✅ Camada de ruas detalhadas exportada: {ruas_path} (feições: {len(gdf)})")
    else:
        print("⚠️ Nenhuma via retornada. Tente expandir a área.")


def _bearing_of_segment(line, ref_pt):
    # pega o segmento mais próximo do ponto de referência e calcula o azimute
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    # escolhe o par (u,v) com menor distância ao ref_pt
    best = None; bestd = 1e18
    for i in range(len(coords)-1):
        seg = gpd.GeoSeries.from_wkt([ ]);  # placeholder to please linters
        p1 = np.array(coords[i]);  p2 = np.array(coords[i+1])
        # ponto médio do segmento
        mid = (p1 + p2)/2.0
        d = (mid[0]-ref_pt.x)**2 + (mid[1]-ref_pt.y)**2
        if d < bestd:
            bestd = d; best = (p1,p2)
    (x1,y1),(x2,y2) = best
    ang = np.degrees(np.arctan2(y2-y1, x2-x1)) % 180.0  # direção de via, sem sentido
    return ang

def atribuir_ruas_e_esquinas_precision(
        upload_dir,
        arquivo_final_nome="final.shp",
        epsg_lotes=31983,
        base_buffer=9,
        min_testada=1.0,
        min_delta_graus=30.0
    ):
    """
    Atribui:
      - Rua: todas as ruas que tocam o lote, em uma string separada por vírgula
      - Esquina: True/False baseado em ângulo das vias e múltiplas testadas
    Salva em final/final_gpkg.gpkg.
    """

    if not (upload_dir / "ruas" / "ruas_osm_detalhadas.gpkg").exists():
        lotes = gpd.read_file(upload_dir / "final" / arquivo_final_nome)
        out = upload_dir / "final" / "final_gpkg.gpkg"
        lotes.to_file(out, driver="GPKG", encoding="utf-8")
        print(f"✅ final_gpkg.gpkg gerado com campos Rua e Esquina. Lotes: {len(lotes)}")
        return

    # 1) Carregar dados
    lotes = gpd.read_file(upload_dir / "final" / arquivo_final_nome)
    ruas  = gpd.read_file(upload_dir / "ruas" / "ruas_osm_detalhadas.gpkg")

    # 2) Garantir CRS
    if not lotes.crs:
        lotes.set_crs(epsg=epsg_lotes, inplace=True)

    if not ruas.crs:
        ruas.set_crs(epsg=4326, inplace=True)

    ruas = ruas.to_crs(lotes.crs)

    # 3) Manter somente ruas com nome
    ruas = ruas[ruas["name"].notna()].copy()
    if len(ruas) == 0:
        print("⚠ Nenhuma rua com nome encontrada.")
        lotes["Rua"] = None
        lotes["Esquina"] = False
        out = upload_dir / "final" / "final_gpkg.gpkg"
        lotes.to_file(out, driver="GPKG", encoding="utf-8")
        return out

    # 4) Dissolver ruas por nome + buffer
    ruas_dis = ruas.dissolve(by="name", as_index=False, aggfunc="first")
    ruas_dis["geometry"] = ruas_dis.buffer(base_buffer)
    sidx = ruas_dis.sindex

    # --- helpers internos ---
    def compute_testada(lote_geom, rua_geom):
        borda = lote_geom.boundary
        inter = borda.intersection(rua_geom)
        if inter.is_empty:
            return 0.0
        if inter.geom_type == "LineString":
            return inter.length
        if inter.geom_type == "MultiLineString":
            return sum(g.length for g in inter.geoms)
        return 0.0

    def compute_rua_angle(lote_geom, rua_name):
        eixo = ruas[ruas["name"] == rua_name].union_all()
        ref_pt = nearest_points(lote_geom, eixo)[0]

        if eixo.geom_type == "MultiLineString":
            seg = min(eixo.geoms, key=lambda g: g.distance(lote_geom))
        else:
            seg = eixo

        return _bearing_of_segment(seg, ref_pt)

    # 6) Processar lotes
    ruas_str_final = []
    esquina_final = []

    for _, lote in lotes.iterrows():
        lote_geom = lote.geometry

        # candidatos pelo bbox
        idxs = list(sidx.intersection(lote_geom.bounds))
        cand_ruas = ruas_dis.iloc[idxs]

        touched = []
        angulos = []

        for _, r in cand_ruas.iterrows():
            testada = compute_testada(lote_geom, r.geometry)
            if testada >= min_testada:
                nome = r["name"]
                touched.append(nome)
                ang = compute_rua_angle(lote_geom, nome)
                if ang is not None:
                    angulos.append(ang)

        # nomes únicos ordenados
        touched = sorted(set(touched))

        # Rua: todas as ruas em uma string separada por vírgula
        if len(touched) == 0:
            ruas_str_final.append(None)
        else:
            ruas_str_final.append(", ".join(touched))

        # Esquina: múltiplas ruas com ângulo bem diferente
        if len(angulos) >= 2:
            deltas = []
            for i in range(len(angulos)):
                for j in range(i+1, len(angulos)):
                    d = abs(angulos[i] - angulos[j])
                    d = min(d, 180 - d)
                    deltas.append(d)
            esquina_final.append(max(deltas) >= min_delta_graus)
        else:
            esquina_final.append(False)

    # 7) Guardar nos lotes
    lotes["Rua"] = ruas_str_final
    lotes["Esquina"] = esquina_final

    # 8) Exportar final
    out = upload_dir / "final" / "final_gpkg.gpkg"
    lotes.to_file(out, driver="GPKG", encoding="utf-8")
    print(f"✅ final_gpkg.gpkg gerado com campos Rua e Esquina. Lotes: {len(lotes)}")
    return out

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


