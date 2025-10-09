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

qgs = QgsApplication([], False)
qgs.initQgis()

Processing.initialize()
QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

base_path = Path(r"./exportacoes")
lotes_path = base_path / "lotes"
textos_n_lotes_path = base_path / "textos_n_lotes"

# Carregar a camada “LOTES corrigida” — supondo que seja shapefile ou gpkg
lotes_corr_path = lotes_path / r"lotes_fixed.shp"
lotes_corr = QgsVectorLayer(str(lotes_corr_path), "lotes_fixed", "ogr")
if not lotes_corr.isValid():
    raise Exception("Camada de lotes corrigida inválida")

# Carregar a camada de textos (texto_n_lotes)
texto_n_lotes = textos_n_lotes_path / r"textos_n_lotes.shp"
textos = QgsVectorLayer(str(texto_n_lotes), "textos_n_lotes", "ogr")

if not textos.isValid():
    raise Exception("Camada de textos inválida")

# Definir parâmetros para join by location summary
params = {
    'INPUT': lotes_corr,                          # camada de entrada (“source”)
    'JOIN': textos,                              # camada a ser somada / unida
    # PREDICATE: 1 = contain, 5 = within 
    'PREDICATE': [1, 5],                         # “contém” ou “está dentro de”
    'JOIN_FIELDS': ['Text'],                    # campo(s) da camada de textos que serão sumarizados
    'SUMMARIES': [2],                            # 2 = “min” 
    'DISCARD_NONMATCHING': False,               # manter feições de LOTES mesmo sem correspondência
    'OUTPUT': 'memory:'                          # ou caminho para salvar shapefile/gpkg
}

# Executar o algoritmo
result = processing.run("native:joinbylocationsummary", params)
joined = result['OUTPUT']

print("📦 Feições de LOTES unidas:", joined.featureCount())

print("Campos da camada resultante:")
for f in joined.fields():
    print(" -", f.name())

out_path = base_path /  'lotes_unidos'
out_path.mkdir(parents=True, exist_ok=True)

processing.run("native:joinbylocationsummary", {
    **params,
    'OUTPUT': str(out_path / r"lotes_texto_unido.shp")
})
print("Resultado salvo em:", out_path)

#qgs.exitQgis()
