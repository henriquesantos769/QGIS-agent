# from .qgis_setup import setup_qgis
# setup_qgis()
from qgis.core import (
    QgsApplication,
    QgsVectorLayer
)
import processing
from qgis.analysis import QgsNativeAlgorithms
from pathlib import Path
import warnings
from processing.core.Processing import Processing
warnings.filterwarnings("ignore")

Processing.initialize()
QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

def join_by_location_summary_final(base_directory: str):
    """Unir atributos de camadas por localização."""
    base_directory = Path(base_directory)
    quadras_unidos_path = base_directory / "quadras_unidos"
    lotes_unidos_path = base_directory / "lotes_unidos"

    quadras_unidos_path = quadras_unidos_path / r"quadras_texto_unido.shp"
    quadras_unidos = QgsVectorLayer(str(quadras_unidos_path), "quadras_texto_unido", "ogr")
    if not quadras_unidos.isValid():
        raise Exception("Camada de quadras unidos inválida")

    lotes_unidos_path = lotes_unidos_path / r"lotes_texto_unido.shp"
    lotes_unidos = QgsVectorLayer(str(lotes_unidos_path), "lotes_texto_unido", "ogr")

    if not lotes_unidos.isValid():
        raise Exception("Camada de lotes_unidos inválida")

    # Definir parâmetros para join by location summary
    params = {
        'INPUT': lotes_unidos,                          # camada de entrada (“source”)
        'JOIN': quadras_unidos,                              # camada a ser somada / unida
        # PREDICATE: 0 = intersect, 4 = overlap, 1 = contain
        'PREDICATE': [0, 1, 4],                         # “interseccionam” ou “sobrepõem” ou "contém"
        'JOIN_FIELDS': ['Text_max'],                    # campo(s) da camada de textos que serão sumarizados
        'SUMMARIES': [3],                            # 3 = “max” 
        'DISCARD_NONMATCHING': False,               # manter feições de quadras mesmo sem correspondência
        'OUTPUT': 'memory:'                          # ou caminho para salvar shapefile/gpkg
    }

    # Executar o algoritmo
    result = processing.run("native:joinbylocationsummary", params)
    joined = result['OUTPUT']

    print("Feições de quadras unidas:", joined.featureCount())

    print("Campos da camada resultante:")
    for f in joined.fields():
        print(" -", f.name())

    out_path = base_directory /  'final'
    out_path.mkdir(parents=True, exist_ok=True)

    processing.run("native:joinbylocationsummary", {
        **params,
        'OUTPUT': str(out_path / r"tabela_final.shp")
    })
    print("Resultado salvo em:", out_path)

    return "Tabela final criada com sucesso."
