import geopandas as gpd
from .docx_utils import (_fmt_num_br, _fmt_coord, _add_cabecalho_memorial, fmt_coord,
                         fmt_dist, azimute_dms,add_cabecalho_memorial_quadras, add_bloco_info_quadra)
from docx import Document
from shapely.geometry import LineString, shape, Point, Polygon
import math
from pathlib import Path
from docx.shared import Pt
from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsVectorFileWriter, QgsField,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsCoordinateTransformContext, QgsRasterLayer, QgsWkbTypes
)
from qgis.analysis import QgsNativeAlgorithms
from processing.core.Processing import Processing
import processing
from qgis.PyQt.QtCore import QVariant
from collections import defaultdict
from shapely.ops import unary_union
from shapely.ops import nearest_points
import json
import requests
import numpy as np
from docx.enum.text import WD_ALIGN_PARAGRAPH

Processing.initialize()
QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

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

def force_polygon(geom):
    """Tenta converter qualquer geometria em Polygon válido."""

    if geom.is_empty:
        return None

    # Caso 1: já é polígono
    if geom.geom_type == "Polygon":
        return geom

    # Caso 2: multipolígono → escolhe o maior
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)

    # Caso 3: GeometryCollection → filtrar apenas os Polygon
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type == "Polygon"]
        if polys:
            return max(polys, key=lambda g: g.area)

    # Último recurso → convex hull
    hull = geom.convex_hull
    if hull.geom_type == "Polygon":
        return hull

    # Tenta curar geometria degenerada
    fixed = geom.buffer(0)
    if fixed.geom_type == "Polygon":
        return fixed

    return None


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

    # union_poly = unary_union(geoms)
    # # union_poly = force_polygon(union_poly)

    # if union_poly is None:
    #     raise RuntimeError("❌ Não foi possível gerar polígono das quadras para consulta Overpass.")

    # coords_str = " ".join(
    #     f"{lat} {lon}" for lon, lat in union_poly.exterior.coords
    # )
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

        # 🔹 Usa as geometrias Shapely das quadras (já em EPSG:4326)
        area_union = unary_union(geoms)  # geoms é lista de Shapely Polygons

        # (Opcional) encolher um pouquinho pra não pegar rua muito longe da borda
        # 0.0003 ~ 30m, ajuste se precisar
        area_union = area_union.buffer(0.0003)

        # 🔹 Filtra só as ruas que realmente intersectam a área das quadras
        gdf = gdf[gdf.intersects(area_union)]

        # Agora reprojeta pro mesmo CRS da camada de quadras
        gdf = gdf.to_crs(quadras.crs().authid())
        
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


def atribuir_ruas_e_esquinas(upload_dir, arquivo_final_nome="final.shp", buffer_rua=5):
    """
    Atribui a(s) rua(s) correspondente(s) e detecta se cada lote é de esquina.
    Cria um arquivo final.gpkg com as colunas adicionais: 'Rua' e 'Esquina'.

    Parâmetros
    ----------
    upload_dir : Path
        Diretório base do processamento (contém 'ruas/' e 'final/').
    arquivo_final_nome : str
        Nome do shapefile final gerado antes desta etapa (padrão: 'final.shp').
    buffer_rua : float
        Tamanho do buffer em metros aplicado às ruas para detectar contato.
    """
    try:
        print("🏷️ Atribuindo ruas e detectando lotes de esquina...")

        ruas_path = upload_dir / "ruas" / "ruas_osm_detalhadas.gpkg"
        final_path = upload_dir / "final" / arquivo_final_nome
        final_gpkg = upload_dir / "final" / "final_gpkg.gpkg"

        if not ruas_path.exists():
            raise FileNotFoundError(f"Camada de ruas não encontrada: {ruas_path}")
        if not final_path.exists():
            raise FileNotFoundError(f"Camada de lotes não encontrada: {final_path}")

        # Carrega camadas
        gdf_ruas = gpd.read_file(ruas_path)
        gdf_lotes = gpd.read_file(final_path)

        # Garante que ambas estão no mesmo CRS
        if not gdf_lotes.crs:
            print("⚠️ CRS dos lotes indefinido. Definindo como EPSG:31983.")
            gdf_lotes.set_crs(epsg=31983, inplace=True)

        if not gdf_ruas.crs:
            print("⚠️ CRS das ruas indefinido. Definindo como EPSG:4326 (padrão OSM).")
            gdf_ruas.set_crs(epsg=4326, inplace=True)

        # Agora reprojeta corretamente
        gdf_ruas = gdf_ruas.to_crs(gdf_lotes.crs)

        # Buffer pequeno nas ruas (para garantir contato)
        gdf_ruas["geometry"] = gdf_ruas.buffer(buffer_rua)

        # Cria índice espacial
        sindex_ruas = gdf_ruas.sindex

        # Listas para resultados
        ruas_col = []
        esquina_col = []

        for _, lote in gdf_lotes.iterrows():
            # Seleciona ruas próximas (via bounding box)
            possible_idx = list(sindex_ruas.intersection(lote.geometry.bounds))
            possiveis = gdf_ruas.iloc[possible_idx]

            # Filtra ruas que realmente tocam o lote
            ruas_tocadas = possiveis[possiveis.intersects(lote.geometry)]

            # Nomes distintos
            nomes = sorted(set(r.strip() for r in ruas_tocadas["name"].dropna()))

            # Define campos
            ruas_col.append(", ".join(nomes) if nomes else None)
            esquina_col.append(len(nomes) >= 2)

        # Adiciona novas colunas
        gdf_lotes["Rua"] = ruas_col
        gdf_lotes["Rua_lista"] = gdf_lotes["Rua"].apply(lambda x: ";".join(x.split(", ")) if isinstance(x, str) and "," in x else x)
        gdf_lotes["Esquina"] = esquina_col

        # Salva no formato final.gpkg
        final_dir = upload_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        gdf_lotes.to_file(final_gpkg, driver="GPKG", encoding="utf-8")

        print(f"✅ Atribuição concluída! Arquivo exportado: {final_gpkg}")
        print(f"   Lotes: {len(gdf_lotes)} | Esquinas detectadas: {sum(esquina_col)}")

        return final_gpkg

    except Exception as e:
        print(f"⚠️ Erro na atribuição de ruas e detecção de esquinas: {e}")
        raise

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

def atribuir_ruas_frente(upload_dir,
                         arquivo_final_nome="final.shp",
                         buffer_rua=9,
                         min_testada=1.0):
    """
    Atribui às geometrias de lote:
      - Rua: todas as ruas tocantes (string)
      - Rua_lista: igual à Rua, porém usando ';' para joins
      - Esquina: True/False baseado em múltiplas testadas
      - LadoFrente: rua com maior testada (rua principal)
    """

    print("🏷️ Atribuindo ruas, esquinas e LadoFrente...")

    ruas_path = upload_dir / "ruas" / "ruas_osm_detalhadas.gpkg"
    final_path = upload_dir / "final" / arquivo_final_nome
    final_gpkg = upload_dir / "final" / "final_gpkg.gpkg"

    # ====================
    # 1) Carregar camadas
    # ====================
    gdf_ruas = gpd.read_file(ruas_path)
    gdf_lotes = gpd.read_file(final_path)

    # ====================
    # 2) Garantir CRS
    # ====================
    if not gdf_lotes.crs:
        gdf_lotes.set_crs(epsg=31983, inplace=True)

    if not gdf_ruas.crs:
        gdf_ruas.set_crs(epsg=4326, inplace=True)

    gdf_ruas = gdf_ruas.to_crs(gdf_lotes.crs)

    # ====================
    # 3) Pequeno buffer de contato
    # ====================
    gdf_ruas["geom_buff"] = gdf_ruas.geometry.buffer(buffer_rua)

    # Índice espacial
    sindex_ruas = gdf_ruas.sindex

    # ====================
    # 4) Helpers internos
    # ====================
    def testada(lote_geom, rua_geom):
        inter = lote_geom.boundary.intersection(rua_geom)
        if inter.is_empty:
            return 0.0
        if inter.geom_type == "LineString":
            return inter.length
        if inter.geom_type == "MultiLineString":
            return sum(seg.length for seg in inter.geoms)
        return 0.0

    # ====================
    # 5) Cálculo por lote
    # ====================
    ruas_final = []
    ruas_lista_final = []
    esquina_final = []
    lado_frente_final = []

    for _, lote in gdf_lotes.iterrows():
        lote_geom = lote.geometry

        # ruas candidatas pelo bbox
        idxs = list(sindex_ruas.intersection(lote_geom.bounds))
        cand = gdf_ruas.iloc[idxs]

        # Informação por rua
        ruas_tocantes = []
        testadas = []

        for _, r in cand.iterrows():
            nome = r["name"]
            if not isinstance(nome, str):
                continue

            t = testada(lote_geom, r.geom_buff)
            if t >= min_testada:
                ruas_tocantes.append(nome)
                testadas.append((nome, t))

        # Ordena nomes e salva Rua / Rua_lista
        if ruas_tocantes:
            ruas_ordenadas = sorted(set(ruas_tocantes))
            ruas_final.append(", ".join(ruas_ordenadas))
            ruas_lista_final.append(";".join(ruas_ordenadas))
        else:
            ruas_final.append(None)
            ruas_lista_final.append(None)

        # Esquina = >= 2 ruas tocantes
        esquina_final.append(len(ruas_tocantes) >= 2)

        # -------------------------
        # 🌟 LadoFrente = maior testada
        # -------------------------
        if testadas:
            nome_frente = max(testadas, key=lambda x: x[1])[0]
            lado_frente_final.append(nome_frente)
        else:
            lado_frente_final.append(None)

    # ====================
    # 6) Atualizar GeoDataFrame
    # ====================
    gdf_lotes["Rua"] = ruas_final
    gdf_lotes["Rua_lista"] = ruas_lista_final
    gdf_lotes["Esquina"] = esquina_final
    gdf_lotes["LadoFrente"] = lado_frente_final

    # ====================
    # 7) Exportar
    # ====================
    final_dir = upload_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    gdf_lotes.to_file(final_gpkg, driver="GPKG", encoding="utf-8")

    print(f"✅ Atribuição concluída: {final_gpkg}")
    print(f"   Lotes: {len(gdf_lotes)}")
    print(f"   Esquinas detectadas: {sum(esquina_final)}")
    print("   Campo LadoFrente criado com sucesso.")

    return final_gpkg

def gerar_confrontacoes(
    upload_dir,
    arquivo_final_nome="final_gpkg.gpkg",
    buffer_rua=4,
    epsg_lotes=31983
):
    import math
    import geopandas as gpd
    from shapely.geometry import LineString, Point, Polygon
    from collections import defaultdict

    print("📐 Gerando confrontações…")

    # ---------------------------------------------------------
    # Parâmetros de robustez
    # ---------------------------------------------------------
    TOL = 0.05            # tolerância topológica (m)
    MIN_LEN_LOTE = 0.7    # comprimento mínimo para considerar confrontação lote-lote
    MIN_FRAC_SEG = 0.15   # fração mínima do segmento

    # ---------------------------------------------------------
    # Carregar dados
    # ---------------------------------------------------------
    lotes_path = upload_dir / "final" / arquivo_final_nome
    ruas_path  = upload_dir / "ruas" / "ruas_osm_detalhadas.gpkg"

    gdf_lotes = gpd.read_file(lotes_path)
    gdf_ruas  = gpd.read_file(ruas_path)

    if not gdf_lotes.crs:
        gdf_lotes.set_crs(epsg_lotes, inplace=True)

    gdf_ruas = gdf_ruas.to_crs(gdf_lotes.crs)
    gdf_ruas["geom_buff"] = gdf_ruas.geometry.buffer(buffer_rua)

    sidx_lotes = gdf_lotes.sindex
    sidx_ruas  = gdf_ruas.sindex

    # ---------------------------------------------------------
    # Helpers geométricos
    # ---------------------------------------------------------
    def segmentos_do_lote(coords):
        return [
            (coords[i], coords[i + 1])
            for i in range(len(coords) - 1)
        ]

    def linha(seg):
        return LineString(seg)

    # ---------------------------------------------------------
    # Classificação de lados (sua lógica – intacta)
    # ---------------------------------------------------------
    def classificar_lados_por_frente(coords, idx_frente):
        C = Polygon(coords).representative_point()

        f1 = Point(coords[idx_frente])
        f2 = Point(coords[idx_frente + 1])

        fx, fy = f2.x - f1.x, f2.y - f1.y
        L = math.hypot(fx, fy)
        fx, fy = fx / L, fy / L

        n1 = (-fy, fx)
        n2 = ( fy, -fx)

        mx_f = (f1.x + f2.x) / 2
        my_f = (f1.y + f2.y) / 2
        vc = (C.x - mx_f, C.y - my_f)

        nx, ny = n1 if vc[0]*n1[0] + vc[1]*n1[1] > 0 else n2

        proj_y_list = []
        for i in range(len(coords) - 1):
            if i == idx_frente:
                continue

            p1 = Point(coords[i])
            p2 = Point(coords[i + 1])
            mx = (p1.x + p2.x) / 2 - C.x
            my = (p1.y + p2.y) / 2 - C.y
            proj_y = mx * nx + my * ny
            proj_y_list.append((i, proj_y))

        max_proj_y = max((py for _, py in proj_y_list), default=0)
        limiar = max_proj_y * 0.7

        lados = {"frente": [idx_frente], "fundos": [], "direita": [], "esquerda": []}

        for i, proj_y in proj_y_list:
            if proj_y >= limiar:
                lados["fundos"].append(i)
                continue

            p1 = Point(coords[i])
            p2 = Point(coords[i + 1])
            sx, sy = p2.x - p1.x, p2.y - p1.y
            cross = fx * sy - fy * sx

            if cross < 0:
                lados["direita"].append(i)
            elif cross > 0:
                lados["esquerda"].append(i)
            else:
                lados["direita"].append(i)

        return lados

    # ---------------------------------------------------------
    # Agregação cadastral
    # ---------------------------------------------------------
    def confrontante_do_lado(indices, seg_infos):
        soma = defaultdict(float)

        for i in indices:
            nome = seg_infos[i]["nome"]
            L = seg_infos[i]["comprimento"]
            soma[nome] += L

        if not soma:
            return "Área não identificada"

        return max(soma.items(), key=lambda x: x[1])[0]

    # ---------------------------------------------------------
    # Garantir campos
    # ---------------------------------------------------------
    for campo in ["Conf_Frente", "Conf_Fundos", "Conf_Direita", "Conf_Esquerda"]:
        if campo not in gdf_lotes.columns:
            gdf_lotes[campo] = None

    # ---------------------------------------------------------
    # PROCESSAMENTO PRINCIPAL
    # ---------------------------------------------------------
    for idx, row in gdf_lotes.iterrows():

        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        lado_frente = row.get("LadoFrente")
        if not isinstance(lado_frente, str):
            continue

        coords = list(geom.exterior.coords)
        segs = segmentos_do_lote(coords)

        seg_infos = []

        # ----------------------------
        # Detectar confrontante por segmento
        # ----------------------------
        for i, seg in enumerate(segs):
            ln = linha(seg)
            seg_len = ln.length
            ln_buff = ln.buffer(TOL)

            melhor_nome = "Área não identificada"
            melhor_score = 0

            # ---- LOTE VIZINHO (borda)
            for il in sidx_lotes.intersection(ln.bounds):
                if il == idx:
                    continue
                other = gdf_lotes.iloc[il]
                inter = other.geometry.boundary.intersection(ln_buff)

                if not inter.is_empty:
                    L = inter.length
                    # if L >= MIN_LEN_LOTE and L / seg_len >= MIN_FRAC_SEG:
                    if L / seg_len >= MIN_FRAC_SEG:
                        if L > melhor_score:
                            melhor_score = L
                            melhor_nome = f"Lote {other.get('lote_num')}"

            # ---- RUA
            if melhor_score == 0:
                for ir in sidx_ruas.intersection(ln.bounds):
                    rua = gdf_ruas.iloc[ir]
                    inter = rua["geom_buff"].intersection(ln_buff)
                    if not inter.is_empty and rua.get("name"):
                        L = inter.length
                        if L / seg_len >= MIN_FRAC_SEG and L > melhor_score:
                            melhor_score = L
                            melhor_nome = rua.get("name")

            seg_infos.append({
                "idx": i,
                "comprimento": seg_len,
                "nome": melhor_nome
            })

        # ----------------------------
        # Identificar índice da frente
        # ----------------------------
        idx_frente = None
        for s in seg_infos:
            if s["nome"] == lado_frente:
                if idx_frente is None or s["comprimento"] > seg_infos[idx_frente]["comprimento"]:
                    idx_frente = s["idx"]

        if idx_frente is None:
            continue

        # ----------------------------
        # Classificar lados corretamente
        # ----------------------------
        lados = classificar_lados_por_frente(coords, idx_frente)

        gdf_lotes.at[idx, "Conf_Frente"]   = confrontante_do_lado(lados["frente"],   seg_infos)
        gdf_lotes.at[idx, "Conf_Direita"]  = confrontante_do_lado(lados["direita"],  seg_infos)
        gdf_lotes.at[idx, "Conf_Esquerda"] = confrontante_do_lado(lados["esquerda"], seg_infos)
        gdf_lotes.at[idx, "Conf_Fundos"]   = confrontante_do_lado(lados["fundos"],   seg_infos)

    # ---------------------------------------------------------
    # Salvar resultado
    # ---------------------------------------------------------
    out = upload_dir / "final" / "final_confrontacoes.gpkg"
    gdf_lotes.to_file(out, driver="GPKG", encoding="utf-8")

    print("✅ Confrontações geradas com sucesso!")
    print("Arquivo:", out)
    return out



def calcular_medidas_e_azimutes(upload_dir,
                                arquivo_final_nome="final_confrontacoes.gpkg",
                                epsg_lotes=31983):
    """
    Calcula para cada lote:
      - Comprimentos oficiais (frente, fundos, direita, esquerda)
      - Azimutes (graus decimais)
      - Rumos (formato N xx°xx'xx" E)
    Usa os mesmos segmentos já detectados em gerar_confrontacoes().

    Gera novos campos:
      Comp_Frente, Comp_Fundos, Comp_Direita, Comp_Esquerda
      Az_Frente, Az_Fundos, Az_Direita, Az_Esquerda
      Rumo_Frente, Rumo_Fundos, Rumo_Direita, Rumo_Esquerda
    """

    print("📏 Calculando medidas e azimutes...")

    lotes_path = upload_dir / "final" / arquivo_final_nome
    gdf = gpd.read_file(lotes_path)

    if not gdf.crs:
        gdf.set_crs(epsg_lotes, inplace=True)

    # ============================
    # Helpers internos
    # ============================

    def segmentos(lote_geom):
        """Divide o polígono em segmentos p1→p2."""
        coords = list(lote_geom.exterior.coords)
        segs = []
        for i in range(len(coords)-1):
            p1 = coords[i]
            p2 = coords[i+1]
            segs.append((p1, p2))
        return segs

    def azimute(seg):
        (x1, y1), (x2, y2) = seg
        dx = x2 - x1
        dy = y2 - y1
        ang = math.degrees(math.atan2(dy, dx))
        return (ang + 360) % 360  # 0–360

    def rumo_from_az(az):
        """
        Converte azimute (0–360) para rumo:
        Ex: N 32°15'20" E
        """

        # Quadrantes
        if 0 <= az < 90:
            qN = "N"; qE = "E"; ang = az
        elif 90 <= az < 180:
            qN = "S"; qE = "E"; ang = 180 - az
        elif 180 <= az < 270:
            qN = "S"; qE = "W"; ang = az - 180
        else:
            qN = "N"; qE = "W"; ang = 360 - az

        # Quebra do ângulo
        g = int(ang)
        m_float = (ang - g) * 60
        m = int(m_float)
        s = (m_float - m) * 60

        return f"{qN} {g:02d}°{m:02d}'{s:04.1f}\" {qE}"

    # Campos a criar
    campos_med = [
        "Comp_Frente", "Comp_Fundos", "Comp_Direita", "Comp_Esquerda"
    ]
    campos_az = [
        "Az_Frente", "Az_Fundos", "Az_Direita", "Az_Esquerda"
    ]
    campos_rumo = [
        "Rumo_Frente", "Rumo_Fundos", "Rumo_Direita", "Rumo_Esquerda"
    ]

    # Cria campos se não existirem
    for c in campos_med + campos_az + campos_rumo:
        if c not in gdf.columns:
            gdf[c] = None

    # ============================
    # LOOP lote a lote
    # ============================

    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue

        segs = segmentos(geom)

        lado_frente = row.get("Conf_Frente")
        lado_fundos = row.get("Conf_Fundos")
        lado_dir    = row.get("Conf_Direita")
        lado_esq    = row.get("Conf_Esquerda")

        # estrutura: {"Frente": (comp, az, rumo), ...}
        dados = {
            "Frente": None,
            "Fundos": None,
            "Direita": None,
            "Esquerda": None,
        }

        # Para identificar qual segmento pertence a qual lado:
        for seg in segs:
            line = LineString(seg)
            comp = line.length
            az = azimute(seg)
            rumo = rumo_from_az(az)

            # Verifica qual confrontação este segmento representa
            nome_testado = None
            for lado_nome, conf in [
                ("Frente",  lado_frente),
                ("Fundos",  lado_fundos),
                ("Direita", lado_dir),
                ("Esquerda", lado_esq)
            ]:
                if conf and conf != "Limite":
                    # Se confrontante é rua ou lote
                    # simplificação robusta:
                    if conf in row["Rua"] or conf in str(row.get("Conf_" + lado_nome)):
                        # Esse lado toca esta confrontação
                        if dados[lado_nome] is None or comp > dados[lado_nome][0]:
                            dados[lado_nome] = (comp, az, rumo)

        # Gravar no GeoDataFrame
        for lado_nome, valor in dados.items():
            if valor:
                comp, az, rumo = valor

                gdf.at[idx, f"Comp_{lado_nome}"] = round(comp, 2)
                gdf.at[idx, f"Az_{lado_nome}"] = round(az, 4)
                gdf.at[idx, f"Rumo_{lado_nome}"] = rumo

    # ============================
    # Salvar resultado
    # ============================
    out = upload_dir / "final" / "final_medidas_azimutes.gpkg"
    gdf.to_file(out, driver="GPKG", encoding="utf-8")

    print("✅ Medidas e azimutes calculados!")
    print("Arquivo:", out)
    return out

def classificar_lados_por_frente(coords, idx_frente):
    import math
    from shapely.geometry import Point, Polygon

    n = len(coords)

    # -----------------------------------
    # 1) Centròide interno (robusto)
    # -----------------------------------
    C = Polygon(coords).representative_point()

    # -----------------------------------
    # 2) Vetor da frente (normalizado)
    # -----------------------------------
    f1 = Point(coords[idx_frente])
    f2 = Point(coords[(idx_frente + 1) % n])

    fx = f2.x - f1.x
    fy = f2.y - f1.y

    L = math.hypot(fx, fy)
    fx /= L
    fy /= L

    # -----------------------------------
    # 3) Normal interna (para profundidade / fundos)
    # -----------------------------------
    n1 = (-fy, fx)
    n2 = ( fy, -fx)

    mx_f = (f1.x + f2.x) / 2
    my_f = (f1.y + f2.y) / 2
    vc = (C.x - mx_f, C.y - my_f)

    if vc[0] * n1[0] + vc[1] * n1[1] > 0:
        nx, ny = n1
    else:
        nx, ny = n2

    # -----------------------------------
    # 4) Primeiro passo: calcular proj_y de todos
    # -----------------------------------
    proj_y_list = []

    for i in range(n):

        if i == idx_frente:
            continue

        p1 = Point(coords[i])
        p2 = Point(coords[(i + 1) % n])

        mx = (p1.x + p2.x) / 2 - C.x
        my = (p1.y + p2.y) / 2 - C.y

        proj_y = mx * nx + my * ny
        proj_y_list.append((i, proj_y))

    # -----------------------------------
    # 5) Determinar o LIMIAR real dos fundos
    # -----------------------------------
    if proj_y_list:
        max_proj_y = max(py for _, py in proj_y_list)
    else:
        max_proj_y = 0

    # 60% do máximo → resolução perfeita para lotes diagonais
    limiar = max_proj_y * 0.7

    # -----------------------------------
    # 6) Classificação final
    # -----------------------------------
    frente_list   = [idx_frente]
    fundos_list   = []
    direita_list  = []
    esquerda_list = []

    for i, proj_y in proj_y_list:

        # --- FUNDOS --- (correto e estável)
        if proj_y >= limiar:
            fundos_list.append(i)
            continue

        # --- Direita / esquerda por cross-product --- (100% estável)
        p1 = Point(coords[i])
        p2 = Point(coords[(i + 1) % n])
        sx = p2.x - p1.x
        sy = p2.y - p1.y

        cross = fx * sy - fy * sx

        if cross < 0:
            direita_list.append(i)
        elif cross > 0:
            esquerda_list.append(i)
        else:
            # perpendicular → decide pela projeção na frente
            mx = (p1.x + p2.x) / 2 - C.x
            my = (p1.y + p2.y) / 2 - C.y
            proj_x = mx * fx + my * fy

            if proj_x >= 0:
                esquerda_list.append(i)
            else:
                direita_list.append(i)

    # -----------------------------------
    # 7) retorno final no formato desejado
    # -----------------------------------
    return {
        "frente":    frente_list,
        "fundos":    fundos_list,
        "direita":   direita_list,
        "esquerda":  esquerda_list
    }

def _memorial_lote_completo(row, nucleo, municipio, uf):
    """
    Gera memorial descritivo completo, sentido horário,
    calculando direção, deflexão e confrontações reais
    para lotes irregulares (qualquer número de lados).
    """

    import math
    from shapely.geometry import Point

    geom = row.geometry
    if geom is None or geom.is_empty:
       return "Geometria indisponível."

    quadra = row.get("quadra")
    lote   = row.get("lote_num")

    # -------------------------------
    # Coordenadas do polígono
    # -------------------------------
    coords = list(geom.exterior.coords)
    if coords[0] == coords[-1]:
        coords = coords[:-1]

    n = len(coords)
    if n < 3:
        return "Lote com geometria insuficiente."

    # Frente correta (índice do segmento)
    frente_conf = row.get("Conf_Frente")
    try:
        frente_conf = int(frente_conf)
    except:
        frente_conf = 0

    # ------------------------------------
    # Helper: formatação coordenadas
    # ------------------------------------
    def fmt_coord(v):
        return format(float(v), ",.4f").replace(",", "X").replace(".", ",").replace("X", ".")

    # ------------------------------------
    # CLASSIFICAÇÃO DOS SEGMENTOS
    # ------------------------------------
    lados = classificar_lados_por_frente(coords, frente_conf)
    print("QUADRA,", quadra, 'Lote', lote)
    print(lados)

    # ------------------------------------
    # Tipo de lado dinâmico
    # ------------------------------------
    def nome_lado(i):
        if i in lados["frente"]:
            return "de frente"
        if i in lados["fundos"]:
            return "ao fundo"
        if i in lados["direita"]:
            return "do lado direito"
        if i in lados["esquerda"]:
            return "do lado esquerdo"
        return "pelo perímetro"

    # ------------------------------------
    # Confronto por lado
    # ------------------------------------
    def lado_confronto(idx):

        if idx in lados["frente"]:
            return row.get("Conf_Frente") or "Área não identificada"

        if idx in lados["direita"]:
            return row.get("Conf_Direita") or "Área não identificada"

        if idx in lados["fundos"]:
            return row.get("Conf_Fundos") or "Área não identificada"

        if idx in lados["esquerda"]:
            return row.get("Conf_Esquerda") or "Área não identificada"

        return "Área não identificada"

    # ------------------------------------
    # Deflexão com base no produto vetorial
    # ------------------------------------
    def deflexao(i):
        if i == 0:
            return ""

        x1, y1 = coords[i - 1]
        x2, y2 = coords[i]
        x3, y3 = coords[(i + 1) % n]

        v1 = (x2 - x1, y2 - y1)
        v2 = (x3 - x2, y3 - y2)

        cross = v1[0] * v2[1] - v1[1] * v2[0]

        if cross < 0:
            return "deste ponto deflete à direita"
        elif cross > 0:
            return "deste ponto deflete à esquerda"
        else:
            return "deste ponto segue em linha"

    # -----------------------------------------------------
    # Introdução
    # -----------------------------------------------------
    area = geom.area
    perim = geom.length

    intro = (
        f"O lote de terreno sob nº {lote} da Quadra {quadra}, do Núcleo denominado "
        f"“{nucleo}”, no município de {municipio} - {uf}, de formato irregular, "
        f"abrangendo uma área de {format(area, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.')} m² "
        f"e um perímetro de {format(perim, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.')} m.\n"
    )

    partes = [intro]

    # -----------------------------------------------------
    # Percorre todos os lados em sentido horário
    # -----------------------------------------------------
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]

        dist = Point(x1, y1).distance(Point(x2, y2))

        coord1 = f"(EX: {fmt_coord(x1)}  NY: {fmt_coord(y1)})"
        coord2 = f"(EX: {fmt_coord(x2)}  NY: {fmt_coord(y2)})"

        confronto = lado_confronto(i)
        tipo_lado = nome_lado(i)
        frase_deflexao = deflexao(i)

        dist_fmt = format(dist, ",.2f").replace(",", "X").replace(".", ",").replace("X", ".")

        if i == 0:
            texto = (
                f"Para quem de dentro do lote {lote} olha para {confronto} "
                f"inicia-se a descrição na coordenada {coord1}, "
                f"com uma distância de {dist_fmt} m {tipo_lado} "
                f"até a coordenada {coord2}, confrontando com {confronto}, "
            )
        elif i < n - 1:
            texto = (
                f"{frase_deflexao} com uma distância de {dist_fmt} m {tipo_lado} "
                f"até a coordenada {coord2}, confrontando com {confronto},"
            )
        else:
            texto = (
                f"{frase_deflexao} com uma distância de {dist_fmt} m {tipo_lado} "
                f"até a coordenada {coord2}, confrontando com {confronto};"
            )

        partes.append(texto)

    return " ".join(partes)


def gerar_memorial_quadra(upload_dir: Path,
                          arquivo_final_nome: str,
                          quadra_alvo,
                          nucleo: str,
                          municipio: str,
                          uf: str,
                          promotor: str = "Instituto Cidade Legal",
                          saida_dir: Path | None = None):

    final_path = upload_dir / "final" / arquivo_final_nome
    gdf = gpd.read_file(final_path)

    # normalizar quadra para string
    gdf["quadra_str"] = gdf["quadra"].astype(str)
    quadra_str = str(quadra_alvo)

    lotes_quadra = gdf[gdf["quadra_str"] == quadra_str].copy()
    if lotes_quadra.empty:
        print(f"⚠ Nenhum lote encontrado para a quadra {quadra_str}.")
        return None

    lotes_quadra = lotes_quadra.sort_values(by="lote_num")

    if saida_dir is None:
        saida_dir = upload_dir / "memoriais"
    saida_dir.mkdir(parents=True, exist_ok=True)

    doc_name = f"memorial_quadra_{quadra_str}.docx"
    docx_path = saida_dir / doc_name

    doc = Document()

    # Cabeçalho padrão
    _add_cabecalho_memorial(
        doc,
        titulo="MEMORIAL DESCRITIVO",
        quadra=quadra_str,
        nucleo=nucleo,
        municipio=municipio,
        uf=uf,
        promotor=promotor
    )

    # Título "DESCRIÇÃO"
    p_desc_titulo = doc.add_paragraph()
    p_desc_titulo.alignment = 1  # centralizado
    #run_desc = p_desc_titulo.add_run("DESCRIÇÃO")
    #run_desc.bold = True

    #doc.add_paragraph()

    for _, row in lotes_quadra.iterrows():
        quadra = row.get("quadra")
        lote_num = row.get("lote_num")
        geom = row.geometry
        area_m2 = geom.area if geom is not None else None
        perimetro_m = geom.length if geom is not None else None

        # Título do lote dentro da quadra
        p_header_lote = doc.add_paragraph()
        run = p_header_lote.add_run(f"Quadra: {quadra}\nLote: {lote_num}")
        run.bold = True

        # Área/perímetro destacados
        if area_m2 is not None:
            run2 = p_header_lote.add_run(f"\nÁrea: {_fmt_num_br(area_m2, 2)} m²\n")
            run2.bold = True
        if perimetro_m is not None:
            pass
            #p_info.add_run(f"Perímetro: {_fmt_num_br(perimetro_m, 2)} m\n")

        doc.add_paragraph()

        # Texto completo estilo exemplo
        texto_lote = _memorial_lote_completo(
            row=row,
            nucleo=nucleo,
            municipio=municipio,
            uf=uf
        )

        p_desc_lote = doc.add_paragraph()
        p_desc_lote.paragraph_format.first_line_indent = Pt(12)
        p_desc_lote.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_desc_lote.add_run(texto_lote)

        doc.add_paragraph()  # espaço entre lotes

    # Rodapé geral
    doc.add_paragraph()
    rod = doc.add_paragraph()
    rod.add_run(
        "Todas as medidas lineares, áreas e coordenadas foram calculadas no sistema de projeção "
        "e datum adotados no projeto (ex.: SIRGAS2000 / UTM)."
    )

    doc.save(str(docx_path))
    print(f"✅ Memorial da quadra {quadra_str} salvo em: {docx_path}")
    return docx_path

def gerar_memoriais_em_lote(upload_dir: Path,
                            arquivo_final_nome: str = "final_medidas_azimutes.gpkg",
                            nucleo: str = "Teste",
                            municipio: str = "Teste",
                            uf: str = "Teste",
                            promotor: str = "Instituto Cidade Legal",
                            saida_dir: Path | None = None):

    final_path = upload_dir / "final" / arquivo_final_nome
    gdf = gpd.read_file(final_path)

    if "quadra" not in gdf.columns:
        raise ValueError("Coluna 'quadra' não encontrada no GPKG final.")

    if saida_dir is None:
        saida_dir = upload_dir / "memoriais"
    saida_dir.mkdir(parents=True, exist_ok=True)

    quadras_unicas = sorted(gdf["quadra"].unique(), key=lambda x: str(x))

    paths_gerados = []

    for q in quadras_unicas:
        path_q = gerar_memorial_quadra(
            upload_dir=upload_dir,
            arquivo_final_nome=arquivo_final_nome,
            quadra_alvo=q,
            nucleo=nucleo,
            municipio=municipio,
            uf=uf,
            promotor=promotor,
            saida_dir=saida_dir
        )
        if path_q:
            paths_gerados.append(path_q)

    print("✅ Geração de memoriais concluída.")
    print("Arquivos gerados:")
    for p in paths_gerados:
        print("  -", p)

    return paths_gerados

def gerar_geometrias_quadras(
    upload_dir: Path,
    arquivo_final_nome: str = "final_medidas_azimutes.gpkg",
    epsg_lotes: int = 31983,
    saida_nome: str = "quadras_contorno.gpkg"
) -> Path:
    """
    Gera o contorno de cada quadra a partir dos lotes,
    unindo os polígonos e calculando área e perímetro da quadra.

    Saída: GPKG em upload_dir / "final" / saida_nome
    com colunas:
      - quadra
      - geometry (polígono da quadra)
      - area_q  (área da quadra)
      - perim_q (perímetro da quadra)
    """
    final_path = upload_dir / "final" / arquivo_final_nome
    if not final_path.exists():
        raise FileNotFoundError(f"Arquivo de lotes não encontrado: {final_path}")

    gdf_lotes = gpd.read_file(final_path)

    if "quadra" not in gdf_lotes.columns:
        raise ValueError("Coluna 'quadra' não encontrada no arquivo de lotes.")

    # Garantir CRS
    if not gdf_lotes.crs:
        gdf_lotes.set_crs(epsg=epsg_lotes, inplace=True)

    quadra_records = []

    # Agrupa lotes por quadra
    for quadra_val, sub in gdf_lotes.groupby("quadra"):
        geoms = [g for g in sub.geometry if g is not None]

        if not geoms:
            continue

        # União das geometrias da quadra
        uni = unary_union(geoms)

        # Limpar geometrias zoadas
        uni = uni.buffer(0)

        # Se ainda for MultiPolygon, pega o maior polígono como contorno principal
        if uni.geom_type == "MultiPolygon":
            uni = max(uni.geoms, key=lambda g: g.area)

        # Se ainda for GeometryCollection / outra coisa, tentar convex hull
        if not isinstance(uni, Polygon):
            uni = uni.convex_hull

        area_q = uni.area
        perim_q = uni.length

        quadra_records.append({
            "quadra": quadra_val,
            "geometry": uni,
            "area_q": area_q,
            "perim_q": perim_q,
        })

    if not quadra_records:
        raise RuntimeError("Não foi possível gerar geometrias de quadra (lista vazia).")

    gdf_quadras = gpd.GeoDataFrame(quadra_records, geometry="geometry", crs=gdf_lotes.crs)

    out_path = upload_dir / "final" / saida_nome
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf_quadras.to_file(out_path, driver="GPKG", encoding="utf-8")

    print(f"✅ Geometrias de quadra geradas: {out_path} (quadras: {len(gdf_quadras)})")
    return out_path

def segmentar_quadra_com_confrontantes(
    upload_dir: Path,
    quadras_gpkg: str = "quadras_contorno.gpkg",
    lotes_gpkg: str = "final_medidas_azimutes.gpkg",
    ruas_gpkg: str = "ruas_osm_detalhadas.gpkg",
    buffer_rua: float = 9.0
):
    """
    Segmenta cada quadra em trechos individuais e determina
    o confrontante de cada segmento: rua, lote ou limite.

    Retorna um GeoDataFrame com:
      quadra, seq, geometry, azimute, comprimento,
      x1, y1, x2, y2,
      tipo ('rua' | 'lote' | 'limite'),
      confronto (nome da rua ou 'Lote xx' ou 'Limite')
    """

    # ----------------------------------------------------------
    # Carregar camadas
    # ----------------------------------------------------------
    quadras_path = upload_dir / "final" / quadras_gpkg
    lotes_path   = upload_dir / "final" / lotes_gpkg
    ruas_path    = upload_dir / "ruas" / ruas_gpkg

    gdf_quadras = gpd.read_file(quadras_path)
    gdf_lotes   = gpd.read_file(lotes_path)
    gdf_ruas    = gpd.read_file(ruas_path)

    crs = gdf_quadras.crs
    gdf_lotes = gdf_lotes.to_crs(crs)
    gdf_ruas  = gdf_ruas.to_crs(crs)

    # buffer das ruas para facilitar interseção
    gdf_ruas["geom_buff"] = gdf_ruas.geometry.buffer(buffer_rua)
    sidx_ruas  = gdf_ruas.sindex
    sidx_lotes = gdf_lotes.sindex

    registros = []

    # ----------------------------------------------------------
    # Processar quadra por quadra
    # ----------------------------------------------------------
    for _, qrow in gdf_quadras.iterrows():
        quadra = qrow["quadra"]
        geom = qrow.geometry

        coords = list(geom.exterior.coords)

        # cada vértice vira um segmento p1->p2
        segmentos = []
        for i in range(len(coords) - 1):
            x1,y1 = coords[i]
            x2,y2 = coords[i+1]

            line = LineString([(x1,y1),(x2,y2)])
            dx = x2 - x1
            dy = y2 - y1
            az = (math.degrees(math.atan2(dy, dx)) + 360) % 360
            dist = line.length

            segmentos.append({
                "quadra": quadra,
                "seq": i + 1,
                "geometry": line,
                "azimute": az,
                "comprimento": dist,
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2
            })

        # ----------------------------------------------------------
        # Determinar confrontantes
        # ----------------------------------------------------------
        for seg in segmentos:
            line = seg["geometry"]

            # — Rua?
            rua_nome = None
            bbox = list(sidx_ruas.intersection(line.bounds))

            for idx_r in bbox:
                rr = gdf_ruas.iloc[idx_r]
                if rr["geom_buff"].intersects(line):
                    if rr.get("name"):
                        rua_nome = rr["name"]
                        break

            # — Lote?
            lote_conf = None
            if rua_nome is None:
                bbox2 = list(sidx_lotes.intersection(line.bounds))
                for idx_l in bbox2:
                    lote = gdf_lotes.iloc[idx_l]
                    if lote.geometry.intersects(line):
                        lote_conf = f"Lote {lote.get('lote_num')} - Quadra {lote.get('quadra')}"
                        break

            if rua_nome:
                seg["tipo"] = "rua"
                seg["confronto"] = rua_nome
            #elif lote_conf:
            #    seg["tipo"] = "lote"
            #    seg["confronto"] = lote_conf
            #else:
            #    seg["tipo"] = "limite"
            #    seg["confronto"] = "Limite"

                registros.append(seg)

    gdf = gpd.GeoDataFrame(registros, geometry="geometry", crs=crs)

    # salvar
    out_path = upload_dir / "final" / "quadras_segmentos.gpkg"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GPKG", encoding="utf-8")

    print(f"✅ Segmentos de quadras gerados: {out_path}")
    return gdf

def calcular_deflexoes_segmentos(
    upload_dir: Path,
    seg_gpkg: str = "quadras_segmentos.gpkg"
):
    """
    Lê os segmentos de quadras e adiciona:
      - deflexão entre trechos ('direita' ou 'esquerda')
      - tipo_lado (frente, direita, esquerda, fundos, perímetro)
      - delta (valor do giro)
      - flag é_primeiro (para o trecho inicial)
    """

    path = upload_dir / "final" / seg_gpkg
    gdf = gpd.read_file(path)

    registros_final = []

    for quadra in sorted(gdf["quadra"].unique(), key=lambda x: str(x)):
        sub = gdf[gdf["quadra"] == quadra].copy()
        sub = sub.sort_values("seq").reset_index(drop=True)

        N = len(sub)

        # percorre todos os segmentos
        for i in range(N):
            row = sub.loc[i]

            az1 = row["azimute"]
            comprimento = row["comprimento"]
            tipo_conf = row["tipo"]
            nome_conf = row["confronto"]

            # ----------------------------------------------------
            # calcular próximo azimute (para deflexão)
            # ----------------------------------------------------
            if i < N - 1:
                az2 = sub.loc[i+1, "azimute"]
            else:
                az2 = sub.loc[0, "azimute"]  # volta ao início

            delta = (az2 - az1 + 360) % 360

            if 0 < delta < 180:
                deflex = "à direita"
            else:
                deflex = "à esquerda"

            # ----------------------------------------------------
            # tipo de lado — baseado no confrontante
            # ----------------------------------------------------
            if tipo_conf == "rua":
                tipo_lado = "de frente"
            elif tipo_conf == "lote":
                tipo_lado = "do lado direito"  # pode melhorar depois
            elif tipo_conf == "limite":
                tipo_lado = "pelo perímetro"
            else:
                tipo_lado = ""

            registros_final.append({
                "quadra": quadra,
                "seq": row["seq"],
                "geometry": row.geometry,
                "x1": row["x1"],
                "y1": row["y1"],
                "x2": row["x2"],
                "y2": row["y2"],
                "comprimento": comprimento,
                "azimute": az1,
                "delta": delta,
                "deflexao": deflex,
                "tipo": tipo_conf,
                "tipo_lado": tipo_lado,
                "confronto": nome_conf,
                "primeiro": (i == 0)
            })

    gdf_out = gpd.GeoDataFrame(registros_final, geometry="geometry", crs=gdf.crs)

    out_path = upload_dir / "final" / "quadras_segmentos_deflex.gpkg"
    gdf_out.to_file(out_path, driver="GPKG", encoding="utf-8")

    print(f"✅ Deflexões calculadas e salvas em: {out_path}")
    return gdf_out

def carregar_quadras_poligono(upload_dir: Path):
    """
    Carrega a camada de quadras como POLÍGONOS e garante que possui CRS.
    Tenta automaticamente os arquivos comuns do pipeline.
    """

    candidatos = [
        upload_dir / "quadras" / "quadras.shp",
        upload_dir / "quadras" / "quadras_m2s.shp",
        upload_dir / "quadras" / "quadras_dissolve.shp",
    ]

    for path in candidatos:
        if path.exists():
            print(f"🔎 Tentando carregar quadras: {path}")
            gdf = gpd.read_file(path)

            # Caso não tenha CRS
            if gdf.crs is None:
                print("⚠ Quadras sem CRS — aplicando EPSG:31983")
                gdf = gdf.set_crs(31983)

            # Geometria deve ser Polygon ou MultiPolygon
            if gdf.geom_type.isin(["Polygon", "MultiPolygon"]).any():
                print(f"✅ Quadras carregadas com sucesso: {path}")
                return gdf

            else:
                print(f"⚠ Arquivo não contém polígonos (tipo: {gdf.geom_type.unique()})")

    raise FileNotFoundError(
        "Nenhuma camada válida de quadras poligonais foi encontrada."
    )

def gerar_memorial_quadras_docx(
        upload_dir: Path,
        arquivo_segmentos="quadras_segmentos.gpkg",
        nucleo="Teste",
        municipio="Teste",
        uf="Teste",
        promotor="Instituto Cidade Legal",
        saida_nome="memorial_quadras.docx"
    ):
    
    path_seg = upload_dir / "final" / arquivo_segmentos
    gdf = gpd.read_file(path_seg).sort_values(["quadra", "seq"])
    gdf_area = carregar_quadras_poligono(upload_dir)

    quadras = sorted(gdf["quadra"].unique(), key=lambda x: str(x))

    doc = Document()

    add_cabecalho_memorial_quadras(doc)

    # Estilo do documento
    estilo = doc.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(11)

    for quadra in quadras:
        sub = gdf[gdf["quadra"] == quadra].copy().reset_index(drop=True)
        sub_poly = gdf_area[gdf_area["quadra"] == quadra].copy().reset_index(drop=True)
        # -----------------------------
        # CALCULAR ÁREA E PERÍMETRO DA QUADRA
        # -----------------------------
        geom_quadra = sub_poly.geometry.union_all()

        print("Quadra:", quadra)
        print("Tipo:", geom_quadra.geom_type)
        print("Is valid:", geom_quadra.is_valid)
        print("Área bruta:", geom_quadra.area)
        print("csr", gdf.crs)

        # Corrige geometrias quebradas
        if geom_quadra.is_empty:
            print(f"⚠ Quadra {quadra}: geometria vazia ao dissolver.")
        else:
            geom_quadra = geom_quadra.buffer(0)

        # Agora sim: área e perímetro verdadeiros
        area_quadra = geom_quadra.area
        print("AREA QUADRA:", area_quadra)
        perimetro_quadra = sub.union_all().length

        # -----------------------------
        # BLOCO: QUADRA / ÁREA / PERÍMETRO
        # -----------------------------
        add_bloco_info_quadra(
            doc,
            quadra=quadra,
            area_m2=area_quadra,
            perimetro_m=perimetro_quadra
        )

        doc.add_paragraph()

        # --------------------------
        # INÍCIO DO TEXTÃO
        # --------------------------

        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(20)
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


        for i, row in sub.iterrows():

            P1 = f"P{str(i+1).zfill(2)}"
            P2 = f"P{str(i+2).zfill(2)}" if i < len(sub)-1 else "P01"

            x1, y1 = row["x1"], row["y1"]
            x2, y2 = row["x2"], row["y2"]
            dist = row["comprimento"]
            az = row["azimute"]
            conf = row["confronto"]

            coord1 = f"N {fmt_coord(y1)}m e E {fmt_coord(x1)}m"
            coord2 = f"N {fmt_coord(y2)}m e E {fmt_coord(x2)}m"

            az_dms = azimute_dms(az)
            dist_fmt = fmt_dist(dist)

            # Primeiro vértice
            if i == 0:
                texto = (
                    f"Inicia-se a descrição desta quadra no vértice {P1}, "
                    f"de coordenadas {coord1}; "
                    f"deste, segue confrontando com {conf}, "
                    f"com os seguintes azimutes e distâncias: "
                    f"{az_dms} e {dist_fmt} m até o vértice {P2}, "
                    f"de coordenadas {coord2}; "
                )
            elif i == len(sub)-1:
                texto = (
                    f" {az_dms} e {dist_fmt} m até o vértice P01, "
                    f"ponto inicial da descrição deste perímetro."
                )
            else:
                texto = (
                    f"{az_dms} e {dist_fmt} m até o vértice {P2}, "
                    f"de coordenadas {coord2}; "
                )

            run = p.add_run(texto)

        # --------------------------
        # Rodapé padrão da norma
        # --------------------------

        doc.add_paragraph()
        rod = doc.add_paragraph()
        rod.paragraph_format.first_line_indent = Pt(20)
        rod.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        rod.add_run(
            "Todas as coordenadas aqui descritas estão georreferenciadas ao Sistema Geodésico "
            "Brasileiro, de coordenadas N m e E m, e encontram-se representadas no Sistema "
            "U T M, referenciadas ao Meridiano Central n° 39º00', fuso -24, tendo como datum o "
            "SIRGAS2000. Todos os azimutes, distâncias, área e perímetro foram calculados no "
            "plano de projeção U T M."
        )

        doc.add_page_break()

    # --------------------------
    # Salvar DOCX final
    # --------------------------
    out_path = upload_dir / "memoriais" / saida_nome
    out_path.parent.mkdir(exist_ok=True, parents=True)
    doc.save(str(out_path))

    print("✅ Memorial de quadras gerado com sucesso!")
    print("Arquivo:", out_path)
    return out_path