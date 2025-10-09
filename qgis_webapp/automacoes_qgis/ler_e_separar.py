# from .qgis_setup import setup_qgis
# setup_qgis()
from qgis.core import (
    QgsVectorLayer,
    QgsFeatureRequest,
    QgsVectorFileWriter,
    QgsApplication,
    QgsCoordinateReferenceSystem
)
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")


def load_and_split_dxf(input_path: str, output_path: str):
    """Carrega um arquivo DXF e separa suas camadas em shapefiles e CSVs."""
    layer_uri_point = input_path + "|layername=entities|geometrytype=Point"
    layer_uri_linestring = input_path + "|layername=entities|geometrytype=LineString"

    layer_point = QgsVectorLayer(layer_uri_point, "entities", "ogr")
    layer_linestring = QgsVectorLayer(layer_uri_linestring, "entities", "ogr")


    print("Geometry Type LineString:",layer_linestring.geometryType())
    print("Geometry Type Point:",layer_point.geometryType())

    # Define o CRS (EPSG:31982 - SIRGAS 2000 / UTM zone 22S)
    crs = QgsCoordinateReferenceSystem("EPSG:31982")

    # Pastas de saída
    base_path = Path(output_path)
    base_path.mkdir(parents=True, exist_ok=True)

    lotes_path = base_path / "lotes"
    quadras_path = base_path / "quadras"
    textos_n_quadras_path = base_path / "textos_n_quadras"
    textos_n_lotes_path = base_path / "textos_n_lotes"

    for p in [lotes_path, quadras_path, textos_n_quadras_path, textos_n_lotes_path]:
        p.mkdir(parents=True, exist_ok=True)

    if not layer_point.isValid():
        print("❌ Camada Point inválidas!")
    else:
        print(f"✅ Camada '{layer_point.name()}' carregada com {layer_point.featureCount()} feições.")
        print("Campos disponíveis:", [f.name() for f in layer_point.fields()])
        print(f"🗺️ CRS aplicado: {crs.authid()}")

        #🔹Criar camadas filtradas
        layers_info_point = {
            "textos_n_quadras": ('"Layer" = \'TEXTO_N_QUADRAS\'', textos_n_quadras_path),
            "textos_n_lotes": ('"Layer" = \'TEXTO_N_LOTES\'', textos_n_lotes_path),
        }

        # Verificar valores únicos em "Layer"
        valores = set()
        for feat in layer_point.getFeatures():
            valor = feat.attribute("Layer")
            if valor:
                valores.add(valor)

        print("\n🧭 Layers disponíveis no Point DXF:")
        for v in sorted(valores):
            print("-", v)

        for nome, (filtro, pasta) in layers_info_point.items():
            sub_layer = layer_point.materialize(QgsFeatureRequest().setFilterExpression(filtro))
            print(f"🔹 {nome.upper()}: {sub_layer.featureCount()} feições")

            if sub_layer.featureCount() > 0:
                shp_path = str(pasta / f"{nome}.shp")
                QgsVectorFileWriter.writeAsVectorFormat(sub_layer, shp_path, "utf-8", crs, "ESRI Shapefile")

                csv_path = str(pasta / f"{nome}_atributos.csv")
                QgsVectorFileWriter.writeAsVectorFormat(sub_layer, csv_path, "utf-8", crs, "CSV", onlySelected=False)

                print(f"{nome.upper()} exportado: {shp_path}")
                print(f"CSV atributos: {csv_path}")
            else:
                print(f"Nenhuma feição encontrada para {nome.upper()}.")

    if not layer_linestring.isValid():
        print("❌ Camada LineString inválidas!")
    else:
        print(f"Camada '{layer_linestring.name()}' carregada com {layer_linestring.featureCount()} feições.")
        print("Campos disponíveis:", [f.name() for f in layer_linestring.fields()])

        print(f"CRS aplicado: {crs.authid()}")

        # 🔹 Criar camadas filtradas
        layers_info_linestring = {
            "lotes": ('"Layer" = \'LOTES\'', lotes_path),
            "quadras": ('"Layer" = \'QUADRAS\'', quadras_path),
        }

        # Verificar valores únicos em "Layer"
        valores = set()
        for feat in layer_linestring.getFeatures():
            valor = feat.attribute("Layer")
            if valor:
                valores.add(valor)

        print("\n🧭 Layers disponíveis no LineString DXF:")
        for v in sorted(valores):
            print("-", v)

        for nome, (filtro, pasta) in layers_info_linestring.items():
            sub_layer = layer_linestring.materialize(QgsFeatureRequest().setFilterExpression(filtro))
            print(f"🔹 {nome.upper()}: {sub_layer.featureCount()} feições")

            if sub_layer.featureCount() > 0:
                shp_path = str(pasta / f"{nome}.shp")
                QgsVectorFileWriter.writeAsVectorFormat(sub_layer, shp_path, "utf-8", crs, "ESRI Shapefile")

                csv_path = str(pasta / f"{nome}_atributos.csv")
                QgsVectorFileWriter.writeAsVectorFormat(sub_layer, csv_path, "utf-8", crs, "CSV", onlySelected=False)

                print(f"{nome.upper()} exportado: {shp_path}")
                print(f"CSV atributos: {csv_path}")
            else:
                print(f"Nenhuma feição encontrada para {nome.upper()}.")

    return "Leitura e separação de camadas concluída com sucesso."