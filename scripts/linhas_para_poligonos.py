import processing
from pathlib import Path
from qgis.analysis import QgsNativeAlgorithms
from processing.core.Processing import Processing
from qgis.core import (
    QgsApplication,
)

qgs = QgsApplication([], False)
qgs.initQgis()

Processing.initialize()
QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

base_path = Path(r"./exportacoes")
lotes_path = base_path / "lotes"
quadras_path = base_path / "quadras"

# Converter linhas de lotes em polígonos e corigir geometria de lotes
polygons = processing.run("qgis:linestopolygons", {
    'INPUT': str(lotes_path / "lotes.shp"),
    'OUTPUT': str(lotes_path / "lotes_poligonos.shp")
})

fixed = processing.run("native:fixgeometries", {
    'INPUT': str(lotes_path / "lotes_poligonos.shp"),
    'OUTPUT': str(lotes_path / "lotes_fixed.shp")
})

# Converter linhas de quadras em polígonos e corigir geometria de quadras
polygons = processing.run("qgis:linestopolygons", {
    'INPUT': str(quadras_path / "quadras.shp"),
    'OUTPUT': str(quadras_path / "quadras_poligonos.shp")
})

fixed = processing.run("native:fixgeometries", {
    'INPUT': str(quadras_path / "quadras_poligonos.shp"),
    'OUTPUT': str(quadras_path / "quadras_fixed.shp")
})


