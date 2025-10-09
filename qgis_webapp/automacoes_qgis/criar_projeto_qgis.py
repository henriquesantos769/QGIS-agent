from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
    Qgis
)
from pathlib import Path
from qgis.PyQt.QtGui import QColor, QFont

# CRS padrão (SIRGAS 2000 / UTM 22S)
project_crs = QgsCoordinateReferenceSystem("EPSG:31982")
project = QgsProject.instance()
project.setCrs(project_crs)


def enable_text_label(layer, field_name="Text", grupo_nome=None):
    field_names = [f.name() for f in layer.fields()]
    if field_name not in field_names:
        print(f"Campo '{field_name}' não encontrado em {layer.name()}.")
        return

    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = field_name
    label_settings.placement = Qgis.LabelPlacement.OverPoint

    text_format = QgsTextFormat()
    if grupo_nome == "TEXTO N LOTES":
        text_format.setSize(6)
        text_format.setFont(QFont("MS Shell Dlg 2", 6, QFont.Light))
        text_format.setColor(QColor(0, 50, 255))
    elif grupo_nome == "TEXTO N QUADRAS":
        text_format.setSize(14)
        text_format.setFont(QFont("MS Shell Dlg 2", 14, QFont.DemiBold))
        text_format.setColor(QColor(255, 50, 0))
    else:
        print(f"Grupo '{grupo_nome}' não reconhecido para rótulos.")
        return

    label_settings.setFormat(text_format)
    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabelsEnabled(True)
    layer.setLabeling(labeling)
    layer.triggerRepaint()
    print(f"Rótulos ativados para '{layer.name()}' (campo: {field_name})")


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
    print(f"✅ Adicionado: {layer_name} | CRS: {lyr.crs().authid()}")

    if "textos" in layer_name.lower():
        enable_text_label(lyr, "Text", grupo_nome=grupo_nome)
    return lyr


def create_project(base_directory: str):
    """Cria um projeto QGIS (.qgz) com camadas e rótulos."""
    base = Path(base_directory)

    estrutura = {
        "LOTES": [
            base / "lotes" / "lotes_poligonos.shp",
            base / "lotes" / "lotes_fixed.shp",
            base / "lotes" / "lotes.shp",
        ],
        "QUADRAS": [
            base / "quadras" / "quadras_poligonos.shp",
            base / "quadras" / "quadras_fixed.shp",
            base / "quadras" / "quadras.shp",
        ],
        "TEXTO N LOTES": [base / "textos_n_lotes" / "textos_n_lotes.shp"],
        "TEXTO N QUADRAS": [base / "textos_n_quadras" / "textos_n_quadras.shp"],
        "FINAL": [base / "final" / "tabela_final.shp"],
    }

    root = project.layerTreeRoot()
    for grupo_nome, arquivos in estrutura.items():
        grp = root.addGroup(grupo_nome)
        for arq in arquivos:
            add_layer_in_group(str(arq), grp, grupo_nome=grupo_nome)

    saida = base / "projeto_final_rotulado.qgz"
    project.write(str(saida))
    print(f"Projeto salvo com rótulos: {saida}")
    return f"💾 Projeto QGIS criado com sucesso em: {saida}"
