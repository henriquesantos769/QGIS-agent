import geopandas as gpd
from .docx_utils import _fmt_num_br, _fmt_coord, _add_cabecalho_memorial
from docx import Document
from shapely.geometry import LineString, shape, Point
import math
from pathlib import Path
from docx.shared import Pt
from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsVectorFileWriter, QgsField,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsCoordinateTransformContext, QgsRasterLayer
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
    gdf_ruas["geometry"] = gdf_ruas.buffer(buffer_rua)

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

            t = testada(lote_geom, r.geometry)
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

def gerar_confrontacoes(upload_dir,
                        arquivo_final_nome="final_gpkg.gpkg",
                        buffer_rua=9,
                        min_testada=1.0,
                        epsg_lotes=31983):
    """
    Gera os confrontantes (frente, fundos, lado direito e esquerdo)
    para cada lote, usando geometria segmentada e Rua/LadoFrente já definidos.

    Campos adicionados:
      - Conf_Frente
      - Conf_Fundos
      - Conf_Direita
      - Conf_Esquerda
    """

    print("📐 Gerando confrontações...")

    # =====================
    # 1) Carregar lotes e ruas
    # =====================
    lotes_path = upload_dir / "final" / arquivo_final_nome
    ruas_path  = upload_dir / "ruas" / "ruas_osm_detalhadas.gpkg"

    gdf_lotes = gpd.read_file(lotes_path)
    gdf_ruas  = gpd.read_file(ruas_path)

    # Garantir CRS
    if not gdf_lotes.crs:
        gdf_lotes.set_crs(epsg_lotes, inplace=True)

    if not gdf_ruas.crs:
        gdf_ruas.set_crs(4326, inplace=True)

    gdf_ruas = gdf_ruas.to_crs(gdf_lotes.crs)
    gdf_ruas["geometry"] = gdf_ruas.buffer(buffer_rua)

    # Índices espaciais
    sindex_ruas  = gdf_ruas.sindex
    sindex_lotes = gdf_lotes.sindex

    # =====================
    # Helpers
    # =====================

    def segmentos_do_lote(lote_geom):
        """Divide o polígono em segmentos (p1,p2)."""
        coords = list(lote_geom.exterior.coords)
        segs = []
        for i in range(len(coords)-1):
            p1 = coords[i]
            p2 = coords[i+1]
            segs.append(((p1[0], p1[1]), (p2[0], p2[1])))
        return segs

    def segmento_para_linestring(seg):
        (x1,y1),(x2,y2) = seg
        return LineString([(x1,y1),(x2,y2)])

    # =====================
    # 2) Criar campos novos
    # =====================
    campos = ["Conf_Frente", "Conf_Fundos", "Conf_Direita", "Conf_Esquerda"]
    for c in campos:
        if c not in gdf_lotes.columns:
            gdf_lotes[c] = None

    # =====================
    # 3) Processar lote a lote
    # =====================
    for idx, lote in gdf_lotes.iterrows():
        geom = lote.geometry
        if geom is None:
            continue

        segs = segmentos_do_lote(geom)
        lado_frente = lote.get("LadoFrente", None)

        # Se não há LadoFrente, pula
        if not isinstance(lado_frente, str):
            continue

        seg_infos = []  # [(seg, tipo, nome, comprimento, azimute)]

        for seg in segs:
            line = segmento_para_linestring(seg)
            seg_len = line.length

            # azimute bruto do segmento
            dx = seg[1][0] - seg[0][0]
            dy = seg[1][1] - seg[0][1]
            az = (math.degrees(math.atan2(dy, dx)) + 360) % 360

            # Verifica contatos com ruas
            bbox_hits_rua = list(sindex_ruas.intersection(line.bounds))
            nome_rua_encostada = None
            for ir in bbox_hits_rua:
                r = gdf_ruas.iloc[ir]
                if r.geometry.intersects(line) and r["name"]:
                    nome_rua_encostada = r["name"]
                    break

            # Verifica contatos com outros lotes
            bbox_hits_lote = list(sindex_lotes.intersection(line.bounds))
            nome_lote_vizinho = None
            for il in bbox_hits_lote:
                if il == idx:
                    continue
                other = gdf_lotes.iloc[il]
                inter = other.geometry.intersection(line)

                if not inter.is_empty and inter.length > 0:
                    nome_lote_vizinho = f"Lote {other.get('lote_num')}"
                    break

            # Tipo de segmento
            if nome_rua_encostada:
                tipo = "rua"
                nome_conf = nome_rua_encostada
            elif nome_lote_vizinho:
                tipo = "lote"
                nome_conf = nome_lote_vizinho
            else:
                tipo = "limite"
                nome_conf = "Limite"

            seg_infos.append({
                "seg": seg,
                "comprimento": seg_len,
                "azimute": az,
                "tipo": tipo,
                "nome": nome_conf,
                "rua": nome_rua_encostada
            })

        # =====================
        # 4) Identificar Frente
        # =====================
        segs_frente = [s for s in seg_infos if s["rua"] == lado_frente]
        if segs_frente:
            frente_selecionado = max(segs_frente, key=lambda x: x["comprimento"])
        else:
            frente_selecionado = None

        # =====================
        # 5) Classificar lados
        # =====================
        if frente_selecionado:
            az_frente = frente_selecionado["azimute"]

            def delta(a, b):
                d = abs(a - b)
                return min(d, 360 - d)

            fundos = min(seg_infos, key=lambda s: delta(s["azimute"], (az_frente+180)%360))

            direita = min(seg_infos, key=lambda s: delta(s["azimute"], (az_frente-90)%360))
            esquerda = min(seg_infos, key=lambda s: delta(s["azimute"], (az_frente+90)%360))

            gdf_lotes.at[idx, "Conf_Frente"] = frente_selecionado["nome"]
            gdf_lotes.at[idx, "Conf_Fundos"] = fundos["nome"]
            gdf_lotes.at[idx, "Conf_Direita"] = direita["nome"]
            gdf_lotes.at[idx, "Conf_Esquerda"] = esquerda["nome"]

    # =====================
    # 6) Salvar
    # =====================
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


def _memorial_lote_completo(row, nucleo, municipio, uf):
    """
    Gera memorial descritivo completo, sentido horário, estilo REURB,
    incluindo coordenadas (EX/NY), distâncias e confrontações por segmento.
    """

    geom = row.geometry
    if geom is None or geom.is_empty:
        return "Geometria indisponível para descrição."

    quadra = row.get("quadra")
    lote = row.get("lote_num")

    coords = list(geom.exterior.coords)
    if coords[0] == coords[-1]:
        coords = coords[:-1]

    n = len(coords)
    if n < 3:
        return "Lote com geometria insuficiente para descrição."

    # Confrontações calculadas pelo pipeline
    frente_conf = row.get("Conf_Frente")
    dir_conf    = row.get("Conf_Direita")
    fundo_conf  = row.get("Conf_Fundos")
    esq_conf    = row.get("Conf_Esquerda")

    # -----------------------------------------------------
    # Helper: formata coordenadas
    # -----------------------------------------------------
    def fmt_coord(v):
        return format(float(v), ",.4f").replace(",", "X").replace(".", ",").replace("X", ".")

    # -----------------------------------------------------
    # Determina confrontação por lado (sentido horário)
    # -----------------------------------------------------
    def lado_confronto(idx):
        if idx == 0:
            return frente_conf or "Área não identificada"
        elif idx == 1:
            return dir_conf or "Área não identificada"
        elif idx == 2:
            return fundo_conf or "Área não identificada"
        elif idx == 3:
            return esq_conf or "Área não identificada"
        return "Área não identificada"

    # -----------------------------------------------------
    # Determina tipo do lado (para frase)
    # -----------------------------------------------------
    def nome_lado(idx):
        if idx == 0:
            return "de frente"
        elif idx == 1:
            return "do lado direito"
        elif idx == 2:
            return "ao fundo"
        elif idx == 3:
            return "do lado esquerdo"
        return "pelo perímetro"

    # -----------------------------------------------------
    # Determina direção da deflexão
    # -----------------------------------------------------
    def deflexao(idx):
        if idx == 0:
            return ""  # primeiro lado não tem deflexão
        # sentido horário
        # 0→1 direita / 1→2 direita / 2→3 direita / 3→0 direita
        return "deste ponto deflete à direita"

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

        # -------------------------------------------------
        # Montagem da frase
        # -------------------------------------------------
        if i == 0:
            # 🔹 PRIMEIRO SEGMENTO
            # Sem espaço no começo, termina com vírgula
            texto = (
                f"Para quem de dentro do lote {lote} olha para {confronto} "
                f"inicia-se a descrição na coordenada {coord1}, "
                f"com uma distância de {dist_fmt} m {tipo_lado} "
                f"até a coordenada {coord2}, confrontando com {confronto}, "
            )
        elif i < n - 1:
            # 🔹 SEGMENTOS INTERMEDIÁRIOS
            # Começa com "deste ponto ...", termina com vírgula
            texto = (
                f"deste ponto {frase_deflexao} com uma distância de {dist_fmt} m {tipo_lado} "
                f"até a coordenada {coord2}, confrontando com {confronto},"
            )
        else:
            # 🔹 ÚLTIMO SEGMENTO
            # Termina com ponto e vírgula
            texto = (
                f"deste ponto {frase_deflexao} com uma distância de {dist_fmt} m {tipo_lado} "
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
