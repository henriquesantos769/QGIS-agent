from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling
)
from pathlib import Path
from qgis.core import Qgis
from qgis.PyQt.QtGui import QColor, QFont

# Inicializa QGIS (standalone)
qgs = QgsApplication([], False)
qgs.initQgis()

# Caminho base
base = Path(r"C:\Users\mario\Documents\estudos\instituto_legal\QGIS-agent\exportacoes")

# Define CRS padrão (SIRGAS 2000 / UTM 22S)
project_crs = QgsCoordinateReferenceSystem("EPSG:31982")
project = QgsProject.instance()
project.setCrs(project_crs)

# 🔹 Função para habilitar rótulos de texto
def enable_text_label(layer, field_name="Text", grupo_nome=None):
    field_names = [f.name() for f in layer.fields()]
    if field_name not in field_names:
        print(f"Campo '{field_name}' não encontrado em {layer.name()}.")
        return

    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = field_name

    # 🚀 Enum correta para QGIS 3.36+
    label_settings.placement = Qgis.LabelPlacement.OverPoint

    # Formatação visual
    if grupo_nome == "TEXTO N LOTES":
        text_format = QgsTextFormat()
        text_format.setSize(6)
        text_format.setSizeUnit(Qgis.RenderUnit.MapUnits)
        text_format.setFont(QFont("MS Shell Dlg 2", 6, QFont.Light))
        text_format.setColor(QColor(0, 50, 255)) # Azul
        label_settings.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabelsEnabled(True)
        layer.setLabeling(labeling)
        layer.triggerRepaint()

    elif grupo_nome == "TEXTO N QUADRAS":
        text_format = QgsTextFormat()
        text_format.setSize(14)
        text_format.setSizeUnit(Qgis.RenderUnit.MapUnits)
        text_format.setFont(QFont("MS Shell Dlg 2", 14, QFont.DemiBold))
        text_format.setColor(QColor(255, 50, 0))
        label_settings.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabelsEnabled(True)
        layer.setLabeling(labeling)
        layer.triggerRepaint()

    else:
        print(f"Grupo '{grupo_nome}' não reconhecido para rótulos.")

    print(f"Rótulos ativados para '{layer.name()}' (campo: {field_name})")

# 🔹 Função para adicionar camada em grupo com CRS e labels
def add_layer_in_group(path_str: str, group, name_hint: str = None, grupo_nome: str = None):
    p = Path(path_str)
    if not p.exists():
        print(f"Arquivo não encontrado: {p}")
        return None
    layer_name = name_hint or p.stem
    lyr = QgsVectorLayer(str(p), layer_name, "ogr")
    if not lyr.isValid():
        print(f"Camada inválida: {p}")
        return None

    lyr_crs = lyr.crs()
    if not lyr_crs.isValid():
        lyr.setCrs(project_crs)

    project.addMapLayer(lyr, False)
    group.addLayer(lyr)
    print(f"Adicionado: {layer_name} | CRS: {lyr.crs().authid()}")

    # Ativa rótulos automaticamente para camadas de texto
    if "textos" in layer_name.lower():
        enable_text_label(lyr, "Text", grupo_nome=grupo_nome)

    return lyr

# Estrutura de grupos e camadas
estrutura = {
    "LOTES": [
        base / "lotes" / "lotes_poligonos.shp",
        base / "lotes" / "lotes_fixed.shp",
        base / "lotes" / "lotes.shp"
    ],
    "QUADRAS": [
        base / "quadras" / "quadras_poligonos.shp",
        base / "quadras" / "quadras_fixed.shp",
        base / "quadras" / "quadras.shp"
    ],
    "TEXTO N LOTES": [
        base / "textos_n_lotes" / "textos_n_lotes.shp"
    ],
    "TEXTO N QUADRAS": [
        base / "textos_n_quadras" / "textos_n_quadras.shp"
    ],
    "FINAL": [
        base / "final" / "tabela_final.shp"
    ]
}

# Montar árvore de grupos
root = project.layerTreeRoot()
for grupo_nome, arquivos in estrutura.items():
    grp = root.addGroup(grupo_nome)
    for arq in arquivos:
        add_layer_in_group(str(arq), grp, grupo_nome=grupo_nome)

# Salvar projeto
saida = base / "projeto_final_rotulado.qgz"
project.write(str(saida))
print(f"\nProjeto salvo com rótulos: {saida}")

qgs.exitQgis()
