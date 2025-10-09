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

def join_by_location_summary_quadras(base_directory: str):
    """Unir atributos de camadas por localização."""
    base_directory = Path(base_directory)
    quadras_path = base_directory / "quadras"
    textos_n_quadras_path = base_directory / "textos_n_quadras"

    # Carregar a camada “quadras corrigida” — supondo que seja shapefile ou gpkg
    quadras_corr_path = quadras_path / r"quadras_fixed.shp"
    quadras_corr = QgsVectorLayer(str(quadras_corr_path), "quadras_fixed", "ogr")
    if not quadras_corr.isValid():
        raise Exception("Camada de quadras corrigida inválida")

    # Carregar a camada de textos (texto_n_quadras)
    texto_n_quadras = textos_n_quadras_path / r"textos_n_quadras.shp"
    textos = QgsVectorLayer(str(texto_n_quadras), "textos_n_quadras", "ogr")

    if not textos.isValid():
        raise Exception("Camada de textos inválida")

    # Definir parâmetros para join by location summary
    params = {
        'INPUT': quadras_corr,                          # camada de entrada (“source”)
        'JOIN': textos,                              # camada a ser somada / unida
        # PREDICATE: 0 = intersect, 4 = overlap 
        'PREDICATE': [0, 4],                         # “interseccionam” ou “sobrepõem”
        'JOIN_FIELDS': ['Text'],                    # campo(s) da camada de textos que serão sumarizados
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

    out_path = base_directory /  'quadras_unidos'
    out_path.mkdir(parents=True, exist_ok=True)

    processing.run("native:joinbylocationsummary", {
        **params,
        'OUTPUT': str(out_path / r"quadras_texto_unido.shp")
    })
    print("Resultado salvo em:", out_path)

    return "Quadras unidas com sucesso."

