from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
    Qgis,
    QgsField,
    QgsProject,
    QgsRendererCategory,
    QgsFillSymbol,
    QgsCategorizedSymbolRenderer,
    QgsEditorWidgetSetup,
    QgsRasterLayer,
    QgsLayerTreeLayer,
    QgsReadWriteContext
)
from pathlib import Path
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QVariant
import zipfile
import geopandas as gpd
from .stylize import stylize_layer_lotes, stylize_layer_ruas, stylize_layer_quadras
import qgis.core as qgs
import re

# CRS padrão (SIRGAS 2000 / UTM 22S)
project_crs = QgsCoordinateReferenceSystem("EPSG:31982")


def fix_relative_paths(qgz_path: Path, base_dir: Path):
    base_str = str(base_dir).replace('\\', '/').rstrip('/') + '/'

    with zipfile.ZipFile(qgz_path, 'r') as zip_in:
        qgs_name = [n for n in zip_in.namelist() if n.endswith('.qgs')][0]
        xml_data = zip_in.read(qgs_name).decode('utf-8')

    # Ex: /media/uploads/ProjetoX/final/... → final/...
    xml_data = xml_data.replace(base_str, '')
    xml_data = xml_data.replace('\\', '/')

    with zipfile.ZipFile(qgz_path, 'w', zipfile.ZIP_DEFLATED) as zip_out:
        zip_out.writestr(qgs_name, xml_data)

    print("🔧 Caminhos absolutos removidos, agora são relativos ao diretório do projeto.")

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


def create_final_project(base_dir: Path, ortho_path: Path = None, DEFAULT_CRS="EPSG:31983"):
    qgs = QgsApplication([], False)
    qgs.initQgis()
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().clear()
    project = QgsProject.instance()
    project.setCrs(project_crs)

     # ================== FUNÇÃO: Adicionar shapefiles ================== 
    def add_shapefiles_from_folder(folder: Path, group_name: str, DEFAULT_CRS=DEFAULT_CRS):
        """Adiciona todas as camadas .shp de uma pasta ao projeto dentro de um grupo.""" 
        if not folder.exists(): 
            print(f"⚠️ Pasta não encontrada: {folder}") 
            return 
        root = project.layerTreeRoot() 
        group = root.addGroup(group_name) 
    
        arquivos = []
        for ext in ("*.shp", "*.gpkg"):
            arquivos.extend(folder.glob(ext))

        for shp_file in arquivos: 
            if shp_file.name.lower() not in ["final_gpkg.gpkg", "ruas_osm_detalhadas.gpkg", "quadras_rotulo_pt.gpkg"]:
                continue # Pula arquivos indesejados 
             
             # limpar as tabelas de atributos das camadas 
            cols_to_maintain = ['fid', 'quadra', 'lote_num', 'name', 'geometry'] 
            gdf = gpd.read_file(shp_file, encoding="utf-8") 

            gdf_cols = [col for col in gdf.columns if col in cols_to_maintain] 
            if "final" in folder.name.lower(): 
                gdf_cols = gdf_cols + ["Nome", "Telefone", "Endereco", "Nº Casa", "STATUS"]
                gdf["Nome"] = "" 
                gdf["Telefone"] = ""
                gdf["Endereco"] = "" 
                gdf["Nº Casa"] = 0 
                # gdf["STATUS"] = "OUTROS"
                gdf["STATUS"] = None
                gdf = gdf[gdf_cols] 
            else:
                gdf = gdf[gdf_cols]
             
            gdf.to_file(shp_file, driver="GPKG", encoding="utf-8") 

            layer = QgsVectorLayer(str(shp_file), shp_file.stem, "ogr") 
            
            if layer.isValid(): 
                DEFAULT_CRS = QgsCoordinateReferenceSystem(DEFAULT_CRS)
                if not layer.crs().isValid() or layer.crs().authid() != DEFAULT_CRS.authid(): 
                    layer.setCrs(DEFAULT_CRS) 
                project.addMapLayer(layer, False) 
                if "final" in shp_file.name.lower():
                    stylize_layer_lotes(layer)
                elif "ruas" in shp_file.name.lower():
                    stylize_layer_ruas(layer)
                elif "quadras" in shp_file.name.lower():
                    stylize_layer_quadras(layer)
                group.addLayer(layer) 
                print(f"✅ Camada adicionada: {shp_file.name}") 
            else: 
                print(f"❌ Falha ao carregar: {shp_file.name}") 

            if "final" in shp_file.name.lower():
                layer.startEditing()
                form_config = layer.editFormConfig()

                # Garantir que os campos de interesse existam
                non_editable_fields = ["fid", "lote_num", "quadra"]
                for field_name in non_editable_fields:
                    idx = layer.fields().indexFromName(field_name)
                    if idx == -1:
                        continue

                    # Torna o campo somente leitura
                    form_config.setReadOnly(idx, True)

                    # Também pode ocultar no formulário (opcional)
                    if field_name == "fid":
                        hidden_widget = QgsEditorWidgetSetup("Hidden", {})
                        layer.setEditorWidgetSetup(idx, hidden_widget)

                for field_name in ["Nome", "Telefone", "Endereco", "Nº Casa"]:
                    if layer.fields().indexFromName(field_name) == -1:
                        print(f"⚠️ Campo '{field_name}' não encontrado na camada, pulando configuração.")
                        continue

                    # Tornar o campo editável
                    idx = layer.fields().indexFromName(field_name)
                    form_config.setReadOnly(idx, False)

                    # Definir widget adequado (para QField)
                    if field_name == "Telefone":
                        widget = QgsEditorWidgetSetup("TextEdit", {"IsMultiline": False})
                    elif field_name == "Nº Casa":
                        widget = QgsEditorWidgetSetup("Range", {"Min": 0, "Max": 9999})
                    else:
                        widget = QgsEditorWidgetSetup("TextEdit", {"IsMultiline": False})

                    layer.setEditorWidgetSetup(idx, widget)

                status_idx = layer.fields().indexFromName("STATUS")
                if status_idx != -1:
                    # Widget de lista suspensa (QField reconhece)
                    value_map = {
                        "IMÓVEIS CONFERIDOS": "IMÓVEIS CONFERIDOS",
                        "IMÓVEIS PENDENTES": "IMÓVEIS PENDENTES",
                        "OUTROS": "OUTROS"
                    }
                    widget = QgsEditorWidgetSetup("ValueMap", {"map": value_map})
                    layer.setEditorWidgetSetup(status_idx, widget)
                    form_config.setReadOnly(status_idx, False)

                    # Criar simbologia categorizada (borda colorida)
                    categories = []
                    color_map = {
                        "IMÓVEIS CONFERIDOS": QColor("#24eb32"),  # verde suave
                        "IMÓVEIS PENDENTES": QColor("#e3242b"),   # vermelho
                        "OUTROS": QColor("#1f75fe")      # azul
                    }

                    for status, color in color_map.items():
                        symbol = QgsFillSymbol.createSimple({
                            'outline_color': color.name(),
                            'outline_width': '0.8',
                            'color': '255,255,255,0',  # preenchimento totalmente transparente
                            'outline_style': 'solid'
                        })

                        category = QgsRendererCategory(status, symbol, status)
                        categories.append(category)
                        
                    # Adiciona uma categoria padrão (fallback)
                    default_symbol = QgsFillSymbol.createSimple({
                        'color': '255,255,255,0',   # preenchimento transparente
                        'outline_color': '#EBF400', # contorno amarelo
                        'outline_width': '0.5',
                        'outline_style': 'solid'
                    })
                    # default_symbol = layer.renderer()
                    default_category = QgsRendererCategory(None, default_symbol, 'Sem STATUS')
                    categories.append(default_category)

                    # Aplica o renderizador categorizado
                    renderer = QgsCategorizedSymbolRenderer("STATUS", categories)
                    layer.setRenderer(renderer)

                # Aplicar a configuração de formulário e garantir edição
                layer.setEditFormConfig(form_config)
                layer.setReadOnly(False)
                layer.setCustomProperty("qgis_readonly", False)
                layer.setCustomProperty("qfieldcloud_editable", True)
                layer.setCustomProperty("QFieldSync/source", "local")
                # layer.setCustomProperty("QFieldSync/cloud_action", "offline_editing")

                layer.commitChanges()
                layer.triggerRepaint()

        # ================== ADICIONAR CAMADAS ================== # 
        #add_shapefiles_from_folder(base_dir / "lotes_linhas", "Lotes - Linhas") 
    add_shapefiles_from_folder(base_dir / "final", "Lotes/Quadras - Polígonos") 
    add_shapefiles_from_folder(base_dir / "quadras", "Quadras") 
    add_shapefiles_from_folder(base_dir / "ruas", "Ruas") 

    iface = qgs.guiInterface() if hasattr(qgs, 'guiInterface') else None 

    layers = [layer for layer in QgsProject.instance().mapLayers().values() if layer.type() == QgsVectorLayer.VectorLayer] 

    root = project.layerTreeRoot()
    group = root.addGroup("Ortofoto")

    # adicionar ortofoto
    if ortho_path and ortho_path.exists():
        rlayer = QgsRasterLayer(str(ortho_path), "Ortofoto de Base")
        if rlayer.isValid():
            DEFAULT_CRS = QgsCoordinateReferenceSystem(DEFAULT_CRS)
            if not rlayer.crs().isValid() or rlayer.crs() != DEFAULT_CRS:
                rlayer.setCrs(DEFAULT_CRS)

            QgsProject.instance().addMapLayer(rlayer, False)
            group.addLayer(rlayer)
            print(f"🖼️ Ortofoto adicionada: {ortho_path.name}")
        else:
            print(f"⚠️ Não foi possível carregar a ortofoto: {ortho_path}")

    project_path = base_dir / "project.qgz"

    # --- Corrigir caminhos para compatibilidade com QField Cloud ---
    # Define caminho do projeto
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)

    # 💡 Força gravação de caminhos relativos a esse diretório
    project.writeEntryBool("Paths", "Absolute", False)
    project.writeEntryBool("Paths", "Relative", True)
    project.writeEntry("Variables", "project_path", ".")
    project.setDirty(True)

    # ================== SALVAR PROJETO ==================  
    if project.write(str(project_path)):
        print(f"🎉 Projeto salvo com sucesso em: {project_path}")
        # fix_relative_paths(project_path, base_dir)
    else:
        print("❌ Erro ao salvar projeto.")

    if layers: # Combina as extensões de todas as camadas 
        full_extent = layers[0].extent() 
        for lyr in layers[1:]: 
            full_extent.combineExtentWith(lyr.extent()) 
        # Ajusta a visualização do projeto para centralizar nessa extensão 
        if iface: 
            iface.mapCanvas().setExtent(full_extent) 
            iface.mapCanvas().refresh() 
        else: 
            print("⚠️ Interface gráfica não detectada (modo headless). Extensão combinada calculada, mas não aplicada.") 
        print("✅ Projeto centralizado na extensão das camadas.") 
    else: 
        print("⚠️ Nenhuma camada vetorial encontrada para centralizar o mapa.")

