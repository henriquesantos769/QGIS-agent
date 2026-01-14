import processing
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
    QgsEditFormConfig,
    QgsLayerTreeLayer,
    QgsReadWriteContext,
    QgsAttributeTableConfig,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsLineSymbol,
    QgsSingleSymbolRenderer,
    QgsWkbTypes,
    QgsTextBufferSettings,
    QgsUnitTypes,
    QgsDefaultValue,
    QgsRelation
)
from pathlib import Path
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QVariant
import zipfile
import geopandas as gpd
from .stylize import (stylize_layer_ruas, stylize_layer_quadras, stylize_rotulos_area,
                        stylize_layer_quadras_rotulos, stylize_layer_outros,
                        stylize_rotulos_lotes, stylize_layer_vertices, stylize_layer_segs_lotes
                        )
import qgis.core as qgs
import xml.etree.ElementTree as ET
import copy
import tempfile
from PyQt5.QtCore import Qt
import os
import shutil
from processing.core.Processing import Processing
import processing
from qgis.analysis import QgsNativeAlgorithms

# CRS padrão (SIRGAS 2000 / UTM 22S)
project_crs = QgsCoordinateReferenceSystem("EPSG:31982")

QFIELD_PLUGIN_TEMPLATE = r"""
import QtQuick
import org.qfield
import Theme

Item {
    id: root

    property var mainWindow: iface.mainWindow()
    property var mapCanvas: iface.mapCanvas()

    property bool selectingFrontStreet: false

    property string ruasLayerName: "Ruas"
    property string ruaNameField: "name"
    property string loteFieldRuaId: "frente_rua_id"
    property string loteFieldRuaNome: "frente_rua_nome"

    QfToolButton {
        id: frontStreetButton
        iconSource: Theme.getThemeVectorIcon("ic_info_white_24dp")
        iconColor: "white"
        round: true
        property color activeColor: "#2196f3"
        property color inactiveColor: "#444444"
        bgcolor: selectingFrontStreet ? activeColor : inactiveColor

        onClicked: {
            selectingFrontStreet = !selectingFrontStreet
            if (selectingFrontStreet) {
                // LEGACY API QUE FUNCIONA EM ANDROID
                mainWindow.setMode("identify")
                mainWindow.displayToast("Modo frente: toque na RUA")
            } else {
                mainWindow.setMode("pan")
                mainWindow.displayToast("Modo frente desativado")
            }
        }
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(frontStreetButton)
        mainWindow.displayToast("Plugin de frente carregado")

        pointHandler.registerHandler("select_front_street", function(point, type, interactionType) {
            if (!selectingFrontStreet)
                return false

            // aqui vamos logar pra descobrir o evento real
            mainWindow.displayToast("EVENT: " + interactionType)

            if (interactionType === "clicked"
                || interactionType === "tap"
                || interactionType === "press") {
                return handleFrontStreetTap(point)
            }

            return false
        })

        pointHandler.setMapInteractionEnabled(true)
    }

    function currentFeatureDrawer() {
        var items = iface.uiItems()
        for (var i = 0; i < items.length; i++)
            if (items[i].featureModel)
                return items[i]
        return null
    }

    function handleFrontStreetTap(point) {
        mainWindow.displayToast("Toque detectado")

        var drawer = currentFeatureDrawer()
        if (!drawer || !drawer.featureModel) {
            mainWindow.displayToast("Abra o lote primeiro")
            mainWindow.setMode("pan")
            selectingFrontStreet = false
            return true
        }

        var loteFeature = drawer.featureModel.feature
        if (!loteFeature) {
            mainWindow.displayToast("Nenhum lote ativo")
            return true
        }

        var px = 20
        var tl = mapCanvas.mapSettings.screenToCoordinate(Qt.point(point.x - px, point.y - px))
        var br = mapCanvas.mapSettings.screenToCoordinate(Qt.point(point.x + px, point.y + px))
        var rectangle = GeometryUtils.createRectangleFromPoints(tl, br)

        var ruasLayers = qgisProject.mapLayersByName(ruasLayerName)
        if (!ruasLayers || ruasLayers.length === 0) {
            mainWindow.displayToast("Camada 'Ruas' não encontrada")
            return true
        }

        var it = LayerUtils.createFeatureIteratorFromRectangle(ruasLayers[0], rectangle)
        if (!it.hasNext()) {
            mainWindow.displayToast("Nenhuma rua nesse ponto")
            return true
        }

        var rua = it.next()
        var ruaId = rua.id
        var ruaNome = rua.attribute(ruaNameField)

        var idxNome = loteFeature.fields.names.indexOf(loteFieldRuaNome)
        var idxId = loteFeature.fields.names.indexOf(loteFieldRuaId)

        if (idxNome < 0 || idxId < 0) {
            mainWindow.displayToast("Campos frente_rua_* faltando")
            return true
        }

        loteFeature.setAttribute(idxId, ruaId)
        loteFeature.setAttribute(idxNome, ruaNome)
        drawer.featureModel.applyFeatureModel()

        mainWindow.displayToast("Frente: " + ruaNome)

        selectingFrontStreet = false
        mainWindow.setMode("pan")
        return true
    }
}
"""



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

def atualizar_campos_final(layer):
    provider = layer.dataProvider()
    campos_existentes = [f.name() for f in layer.fields()]

    # Campos a remover
    campos_remover = [c for c in campos_existentes if c.lower() not in ["nome", "telefone", "endereco", "status", "nº casa", "fid", "quadra", "lote_num"]]
    idx_remover = [layer.fields().indexFromName(c) for c in campos_remover if layer.fields().indexFromName(c) != -1]
    provider.deleteAttributes(idx_remover)
    layer.updateFields()

    # Campos a adicionar
    novos_campos = []
    if "Nome" not in campos_existentes:
        novos_campos.append(QgsField("Nome", QVariant.String))
    if "Telefone" not in campos_existentes:
        novos_campos.append(QgsField("Telefone", QVariant.String))
    if "Endereco" not in campos_existentes:
        novos_campos.append(QgsField("Endereco", QVariant.String))
    if "STATUS" not in campos_existentes:
        novos_campos.append(QgsField("STATUS", QVariant.String))

    if novos_campos:
        provider.addAttributes(novos_campos)
        layer.updateFields()

def create_final_project(base_dir: Path, ortho_path: Path = None, DEFAULT_CRS="EPSG:31983"):
    print("🧠 Iniciando criação do projeto QGIS com campos customizados e ajustes QFieldSync...")

    qgs = QgsApplication([], False)
    qgs.initQgis()

    Processing.initialize()
    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

    project = QgsProject.instance()
    project.removeAllMapLayers()
    project.clear()

    project_path = base_dir / "project_cloud.qgs"
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setCrs(QgsCoordinateReferenceSystem(DEFAULT_CRS))

    root_tree = project.layerTreeRoot()

    # Nome do projeto / título (atributo projectname + <title>)
    project_name = "project_cloud_1 (QFieldCloud)"
    project.setTitle(project_name)

    fotos_dir = base_dir / "fotos"
    fotos_dir.mkdir(exist_ok=True)

    # --- Carregar camadas vetoriais ---
    camadas = [
        ("final/final_gpkg.gpkg", "Lotes"),
        ("final/lotes_rotulos.gpkg", "Lotes"),
        ("final/lotes_area_rotulos.gpkg", "Lotes"),
        ("final/indices_segmentos.gpkg", "Lotes"),
        ("quadras/quadras_dissolve.gpkg", "Quadras"),
        ("quadras/quadras_rotulos_pt.gpkg", "Quadras"),
        ("ruas/ruas_osm_detalhadas.gpkg", "Ruas"),
        ("limitante/limitante.gpkg", "Limitante"),
        ("quadras/quadras_vertices.gpkg", "Quadras"),
    ]

    final_layer_obj = None

    for rel_path, nome_grupo in camadas:
        camada_path = base_dir / rel_path
        if not camada_path.exists():
            print(f"⚠️ Arquivo não encontrado: {camada_path}")
            continue

        layer = QgsVectorLayer(str(camada_path.resolve()), camada_path.stem, "ogr")
        if not layer.isValid():
            print(f"❌ Falha ao carregar camada: {camada_path}")
            continue

        # Corrigir CRS
        crs = QgsCoordinateReferenceSystem(DEFAULT_CRS)
        if not layer.crs().isValid() or layer.crs().authid() != crs.authid():
            layer.setCrs(crs)

        # Adiciona camada base ao projeto
        project.addMapLayer(layer, False)
        print(f"✅ Camada adicionada: {rel_path}")

        # Estilização básica para camadas não 'final'
        if "ruas" in rel_path.lower():
            ruas_layer_obj = layer
            layer.startEditing()
            prov = layer.dataProvider()

            if "rua_id" not in [f.name() for f in layer.fields()]:
                prov.addAttributes([QgsField("rua_id", QVariant.Int)])
                layer.updateFields()

                # preencher ID único incremental
                for i, f in enumerate(layer.getFeatures()):
                    layer.changeAttributeValue(f.id(), layer.fields().indexFromName("rua_id"), i+1)

            layer.commitChanges()
            stylize_layer_ruas(layer)

        elif "quadras_vertices" in rel_path.lower():
            stylize_layer_vertices(layer)

        elif "quadras_rotulos" in rel_path.lower():
            stylize_layer_quadras_rotulos(layer)

        elif "quadras" in rel_path.lower():
            stylize_layer_quadras(layer)

        elif "lotes_area_rotulos" in rel_path.lower():
            stylize_rotulos_area(layer)

        elif "lotes_rotulos" in rel_path.lower():
            stylize_rotulos_lotes(layer)

        elif "limitante" in rel_path.lower():
            stylize_layer_outros(layer)
        
        elif "indices_segmentos" in rel_path.lower():
            stylize_layer_segs_lotes(layer)



        if "final_gpkg" in rel_path.lower():
            final_layer_obj = layer
            camada_filtrada = str(camada_path.resolve())

            # --- 1. Garantir que os campos necessários existam ---
            layer.startEditing()
            prov = layer.dataProvider()
            existing = {f.name() for f in layer.fields()}

            required_fields = [
                ("Nome", QVariant.String),
                ("Telefone", QVariant.String),
                ("Endereco", QVariant.String),
                ("Nº Casa", QVariant.Int),
                ("STATUS", QVariant.String),
                ("quadra", QVariant.String),
                ("lote_num", QVariant.String),
                ("foto", QVariant.String),
                ("frente_rua_nome", QVariant.String),
                ("frente_rua_id", QVariant.Int),
            ]

            for fname, ftype in required_fields:
                if fname not in existing:
                    print(f"➕ Criando campo ausente: {fname}")
                    prov.addAttributes([QgsField(fname, ftype)])
            layer.updateFields()

            # --- 2. Configuração do formulário (editFormConfig) ---
            form_config = layer.editFormConfig()

            # Campos somente leitura
            non_editable_fields = ["fid", "lote_num", "quadra"]
            for field_name in non_editable_fields:
                idx = layer.fields().indexFromName(field_name)
                if idx == -1:
                    continue
                form_config.setReadOnly(idx, True)
                if field_name == "fid":
                    hidden_widget = QgsEditorWidgetSetup("Hidden", {})
                    layer.setEditorWidgetSetup(idx, hidden_widget)

            # Campos visíveis e editáveis
            for field_name in ["Nome", "Telefone", "Endereco", "Nº Casa"]:
                idx = layer.fields().indexFromName(field_name)
                if idx == -1:
                    print(f"⚠️ Campo '{field_name}' não encontrado, pulando.")
                    continue
                form_config.setReadOnly(idx, False)
                if field_name == "Telefone":
                    widget = QgsEditorWidgetSetup("TextEdit", {"IsMultiline": False})
                elif field_name == "Nº Casa":
                    widget = QgsEditorWidgetSetup("Range", {"Min": 0, "Max": 9999})
                else:
                    widget = QgsEditorWidgetSetup("TextEdit", {"IsMultiline": False})
                layer.setEditorWidgetSetup(idx, widget)

            # Campo Rua
            print("🔎 Campos encontrados no layer final:")
            print([f.name() for f in layer.fields()])

            # Esconder campos CAD
            hide_fields = ["Layer", "PaperSpace", "Text", "Linetype", "EntityHand", "SubClasses"]
            for field_name in hide_fields:
                idx = layer.fields().indexFromName(field_name)
                if idx != -1:
                    hidden_widget = QgsEditorWidgetSetup("Hidden", {})
                    layer.setEditorWidgetSetup(idx, hidden_widget)
                    form_config.setReadOnly(idx, True)

            layer.setEditFormConfig(form_config)

            # --- Campo FOTO (fachada do imóvel) ---
            foto_idx = layer.fields().indexFromName("foto")
            if foto_idx != -1:
                foto_widget = QgsEditorWidgetSetup(
                    "ExternalResource",
                    {
                        "UseLink": False,
                        "Property": "photo",
                        "DocumentViewer": 1,
                        "DefaultRoot": "./fotos",
                        "RelativeStorage": True,
                        "StorageMode": 0,
                        "FileWidget": True,
                        "AllowMultiple": False
                    }
                )
                layer.setEditorWidgetSetup(foto_idx, foto_widget)
                form_config.setReadOnly(foto_idx, False)

            layer.setEditFormConfig(form_config)

            # 🔹 Esconder campos CAD na tabela de atributos
            table_cfg = layer.attributeTableConfig()
            cols = table_cfg.columns()
            for col in cols:
                if col.name in hide_fields:
                    col.hidden = True
            table_cfg.setColumns(cols)
            layer.setAttributeTableConfig(table_cfg)

            # --- 3. Configurar widget de STATUS ---
            status_idx = layer.fields().indexFromName("STATUS")
            if status_idx != -1:
                value_map = {
                    "IMÓVEIS CONFERIDOS": "IMÓVEIS CONFERIDOS",
                    "IMÓVEIS PENDENTES": "IMÓVEIS PENDENTES",
                    "OUTROS": "OUTROS",
                }
                widget = QgsEditorWidgetSetup("ValueMap", {"map": value_map})
                layer.setEditorWidgetSetup(status_idx, widget)
                form_config.setReadOnly(status_idx, False)

            # --- 4. Aplicar propriedades QField ---
            layer.setReadOnly(False)
            layer.setCustomProperty("qgis_readonly", False)
            layer.setCustomProperty("qfieldcloud_editable", True)
            layer.setCustomProperty("QFieldSync/source", "local")
            layer.setCustomProperty("QFieldSync/cloud_action", "offline_editing")

            # ✅ Finaliza edição antes do renderer
            if not layer.commitChanges():
                print("⚠️ Falha ao salvar alterações na camada final.")

            # --- 5. Aplicar renderer categorizado (fora do modo de edição) ---
            status_idx = layer.fields().indexFromName("STATUS")
            if status_idx != -1:
                categories = []
                color_map = {
                    "IMÓVEIS CONFERIDOS": QColor("#24eb32"),
                    "IMÓVEIS PENDENTES": QColor("#e3242b"),
                    "OUTROS": QColor("#1f75fe"),
                }

                for status, color in color_map.items():
                    symbol = QgsFillSymbol.createSimple({
                        "outline_color": color.name(),
                        "outline_width": "0.0",
                        "color": "255,255,255,0",
                        "outline_style": "solid",
                    })
                    categories.append(QgsRendererCategory(status, symbol, status))

                default_symbol = QgsFillSymbol.createSimple({
                    "color": "255,255,255,0",
                    "outline_color": "#EBF400",
                    "outline_width": "0.0",
                    "outline_style": "solid",
                })
                categories.append(QgsRendererCategory(None, default_symbol, "Sem STATUS"))

                renderer = QgsCategorizedSymbolRenderer("STATUS", categories)
                layer.setRenderer(renderer)
                layer.triggerRepaint()
                print("🎨 Renderer STATUS aplicado após commit (salvo corretamente no projeto).")

            # --- 6. Estilo visual adicional (rótulos etc.) ---
            print("🎨 Simbologia e campos aplicados na camada final.")

        # --- 5. Propriedades globais QFieldSync e árvore de camadas ---
        layer.setCustomProperty("QFieldSync/cloud_action", "offline")

        group = root_tree.findGroup(nome_grupo) or root_tree.addGroup(nome_grupo)
        group.addLayer(layer)
        print(f"✅ Camada adicionada: {rel_path} | ID: {layer.id()}")
    
    print("🔧 Configurando relação frente_rua...")

    linhas_path = base_dir / "final" / "lotes_segmentos.gpkg"

    # (Opcional mas recomendado) remove arquivo anterior pra evitar erro de escrita
    if linhas_path.exists():
        linhas_path.unlink()

    # 1) reprojeta de verdade (para CRS em metros)
    reproj = processing.run(
        "native:reprojectlayer",
        {
            "INPUT": final_layer_obj,
            "TARGET_CRS": QgsCoordinateReferenceSystem(DEFAULT_CRS),
            "OUTPUT": "memory:"
        }
    )["OUTPUT"]

    # 2) polígono -> linha (contorno completo)
    contorno = processing.run(
        "native:polygonstolines",
        {
            "INPUT": reproj,
            "OUTPUT": "memory:"
        }
    )["OUTPUT"]

    # 3) quebra a linha em segmentos (cada aresta vira uma feição)
    segs = processing.run(
        "native:explodelines",
        {
            "INPUT": contorno,
            "OUTPUT": "memory:"
        }
    )["OUTPUT"]

    # --------------------------------------------------
    # 🔥 4) Criar chave única por segmento (independente da direção)
    #     Isso resolve lotes colados com 2 linhas iguais
    # --------------------------------------------------
    expr_key = """
    with_variable('x1', round(x(start_point($geometry)), 3),
    with_variable('y1', round(y(start_point($geometry)), 3),
    with_variable('x2', round(x(end_point($geometry)), 3),
    with_variable('y2', round(y(end_point($geometry)), 3),
    with_variable('swap', (@x1 > @x2) OR (@x1 = @x2 AND @y1 > @y2),
    if(@swap,
        concat(@x2,';',@y2,';',@x1,';',@y1),
        concat(@x1,';',@y1,';',@x2,';',@y2)
    )
    )))))
    """

    segs_keyed = processing.run(
        "native:fieldcalculator",
        {
            "INPUT": segs,
            "FIELD_NAME": "seg_key",
            "FIELD_TYPE": 2,   # String
            "FIELD_LENGTH": 80,
            "FIELD_PRECISION": 0,
            "FORMULA": expr_key,
            "OUTPUT": "memory:"
        }
    )["OUTPUT"]

    # 5) Dissolver por seg_key -> 1 feição por aresta colada
    segs_unique = processing.run(
        "native:dissolve",
        {
            "INPUT": segs_keyed,
            "FIELD": ["seg_key"],
            "OUTPUT": str(linhas_path)
        }
    )["OUTPUT"]

    # 6) carregar camada no projeto
    layer_linhas = QgsVectorLayer(str(linhas_path), "Lotes - Distâncias", "ogr")
    project.addMapLayer(layer_linhas, False)

    # Rótulos = comprimento do segmento (2 casas)
    settings = QgsPalLayerSettings()
    settings.fieldName = "format_number(length($geometry), 2)"
    settings.isExpression = True
    settings.placement = QgsPalLayerSettings.Line

    # forçar exibição (pra não “sumir” em trechos pequenos/colados)
    settings.displayAll = True
    settings.allowOverlap = True
    settings.minFeatureSize = 0.0
    settings.repeatDistance = 0

    text_format = QgsTextFormat()

    text_format.setFont(QFont("Arial"))
    # text_format.setSize(0.5)  # 🔹 tamanho em METROS 
    # text_format.setSizeUnit(QgsUnitTypes.RenderMetersInMapUnits)

    text_format.setSize(10)  # 🔹 tamanho em pt

    text_format.setColor(QColor("#ff0008"))

    # (opcional) buffer branco pra legibilidade
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.5)  # metros
    #buffer.setSizeUnit(QgsUnitTypes.RenderMetersInMapUnits) # metros
    buffer.setColor(QColor("#FFFFFF"))
    text_format.setBuffer(buffer)

    settings.setFormat(text_format)

    layer_linhas.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer_linhas.setLabelsEnabled(True)
    layer_linhas.triggerRepaint()

    # Estilo simples
    symbol = QgsLineSymbol.createSimple({
        "color": "#000000",
        "width": "0.0"
    })
    layer_linhas.setRenderer(QgsSingleSymbolRenderer(symbol))

    # Grupo
    group = root_tree.findGroup("Lotes/Quadras - Polígonos") or root_tree.addGroup("Lotes/Quadras - Polígonos")
    group.addLayer(layer_linhas)

    if ortho_path:
        rlayer = QgsRasterLayer(str(ortho_path.resolve()), "Ortofoto de Base")
        if rlayer.isValid():
            rlayer.setCrs(QgsCoordinateReferenceSystem(DEFAULT_CRS))
            rlayer.setCustomProperty("QFieldSync/cloud_action", "copy")
            rlayer.setCustomProperty("identify/format", "Value")
            project.addMapLayer(rlayer, False)
            ortho_group = root_tree.addGroup("Ortofoto")
            ortho_group.addLayer(rlayer)
            print(f"🖼️ Ortofoto adicionada: {ortho_path.name}")
        else:
            print(f"⚠️ Não foi possível carregar ortofoto: {ortho_path}")

    # Ordem de camadas (gera <custom-order enabled="1">)
    root_tree.setCustomLayerOrder(list(project.mapLayers().values()))
    root_tree.setHasCustomLayerOrder(True)

    # Caminhos relativos (Paths.Absolute/Relative)
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.writeEntryBool("Paths", "Absolute", False)
    project.writeEntryBool("Paths", "Relative", True)
    project.setDirty(True)

    # Filtro da legenda (vai virar <properties><Legend><filterByMap ...>)
    project.writeEntryBool("Legend", "filterByMap", False)

    if final_layer_obj:
        final_layer_obj.setDisplayExpression('"Nome"')
    
    # Salva o projeto uma primeira vez
    if not project.write(str(project_path)):
        print("❌ Erro ao salvar projeto (primeira escrita).")
        qgs.exitQgis()
        return
    
    #plugin_path = base_dir / "project_cloud.qml"
    #plugin_path = project_path.with_suffix(".qml")
    #plugin_path.write_text(QFIELD_PLUGIN_TEMPLATE, encoding="utf-8")
    #print(f"🧩 Plugin QField criado: {plugin_path.name}")

    # --- Pós-processamento do .qgs para ficar compatível com o QFieldSync ---

    text = project_path.read_text(encoding="utf-8")

    # Preservar DOCTYPE
    if text.lstrip().startswith("<!DOCTYPE"):
        first_nl = text.find("\n")
        doctype = text[:first_nl]
        xml_str = text[first_nl + 1 :]
    else:
        doctype = ""
        xml_str = text

    root = ET.fromstring(xml_str)

    # === habilitar plugin QML para overlay no QField ===
    # qfield_el = ET.Element("qfield")
    # plugins_el = ET.SubElement(qfield_el, "plugins")
    # plugin_el = ET.SubElement(plugins_el, "plugin", {
    #     "type": "qml",
    #     "location": "overlay"
    # })
    # plugin_el.text = "project_cloud.qml"

    # root.append(qfield_el)

    # 1) Mapa de IDs das camadas a partir de <projectlayers>
    layer_ids = []  # lista na ordem
    name_to_id = {}
    datasource_for = {}
    projectlayers_el = root.find("projectlayers")
    if projectlayers_el is not None:
        for ml in projectlayers_el.findall("maplayer"):
            if ml.get("type") == "raster":
                lname = ml.findtext("layername") or ""
                if lname == "Ortofoto de Base":
                    ds_el = ml.find("datasource")
                    if ds_el is not None and ds_el.text:
                        fname = Path(ds_el.text).name
                        ds_el.text = f"./ortofoto/{fname}"  # 🔹 mantém estrutura correta

                    cp = ml.find("customproperties")
                    if cp is None:
                        cp = ET.SubElement(ml, "customproperties")

                    opt_map = cp.find("Option")
                    if opt_map is None or opt_map.get("type") != "Map":
                        opt_map = ET.SubElement(cp, "Option", {"type": "Map"})

                    # Remove duplicatas antigas
                    for opt in list(opt_map):
                        if opt.get("name") in ["QFieldSync/cloud_action", "identify/format"]:
                            opt_map.remove(opt)

                    # Recria as propriedades do QFieldSync conforme o projeto original
                    ET.SubElement(
                        opt_map,
                        "Option",
                        {"name": "QFieldSync/cloud_action", "value": "no_action", "type": "QString"},
                    )
                    ET.SubElement(
                        opt_map,
                        "Option",
                        {"name": "identify/format", "value": "Value", "type": "QString"},
                    )

    # 2) <layerorder> explícito
    layerorder_el = root.find("layerorder")
    if layerorder_el is None:
        # inserir logo depois de </projectlayers>
        idx = list(root).index(projectlayers_el) + 1 if projectlayers_el is not None else len(list(root))
        layerorder_el = ET.Element("layerorder")
        root.insert(idx, layerorder_el)
    else:
        layerorder_el.clear()

    for lid in layer_ids:
        ET.SubElement(layerorder_el, "layer", {"id": lid})

    # 3) custom-order enabled="1" dentro de <layer-tree-group>
    ltg_root = root.find("layer-tree-group")
    if ltg_root is not None:
        # procura custom-order existente
        custom_order = None
        for child in ltg_root.findall("custom-order"):
            custom_order = child
        if custom_order is None:
            custom_order = ET.SubElement(ltg_root, "custom-order")
        custom_order.set("enabled", "1")
        custom_order.clear()
        custom_order.set("enabled", "1")
        for lid in layer_ids:
            item = ET.SubElement(custom_order, "item")
            item.text = lid

    # 4) relations / polymorphicRelations / mapcanvas / projectModels / mapViewDocks
    snap_el = root.find("snapping-settings")
    insert_index = list(root).index(snap_el) + 1 if snap_el is not None else 0

    def ensure_after(tag, current_index):
        el = root.find(tag)
        if el is None:
            el = ET.Element(tag)
            root.insert(current_index, el)
            current_index += 1
        return el, current_index

    relations_el, insert_index = ensure_after("relations", insert_index)
    poly_el, insert_index = ensure_after("polymorphicRelations", insert_index)

    # mapcanvas com extent combinado das camadas
    mapcanvas_el = root.find("mapcanvas")
    if mapcanvas_el is None:
        # calcula extent a partir dos <maplayer><extent>
        xmin = ymin = xmax = ymax = None
        if projectlayers_el is not None:
            for ml in projectlayers_el.findall("maplayer"):
                ext = ml.find("extent")
                if ext is None:
                    continue
                exmin = float(ext.findtext("xmin"))
                eymin = float(ext.findtext("ymin"))
                exmax = float(ext.findtext("xmax"))
                eymax = float(ext.findtext("ymax"))
                if xmin is None:
                    xmin, ymin, xmax, ymax = exmin, eymin, exmax, eymax
                else:
                    xmin = min(xmin, exmin)
                    ymin = min(ymin, eymin)
                    xmax = max(xmax, exmax)
                    ymax = max(ymax, eymax)

        mapcanvas_el = ET.Element("mapcanvas", {"name": "theMapCanvas", "annotationsVisible": "1"})
        units_el = ET.SubElement(mapcanvas_el, "units")
        units_el.text = "meters"

        extent_el = ET.SubElement(mapcanvas_el, "extent")
        for tag, val in (("xmin", xmin), ("ymin", ymin), ("xmax", xmax), ("ymax", ymax)):
            el = ET.SubElement(extent_el, tag)
            el.text = f"{val}" if val is not None else "0"

        rot_el = ET.SubElement(mapcanvas_el, "rotation")
        rot_el.text = "0"

        dest_el = ET.SubElement(mapcanvas_el, "destinationsrs")
        # copia o <spatialrefsys> de <projectCrs>
        proj_crs = root.find("projectCrs")
        if proj_crs is not None:
            srs_el = proj_crs.find("spatialrefsys")
            if srs_el is not None:
                dest_el.append(copy.deepcopy(srs_el))

        root.insert(insert_index, mapcanvas_el)
        insert_index += 1

    projectModels_el, insert_index = ensure_after("projectModels", insert_index)
    mapViewDocks_el, insert_index = ensure_after("mapViewDocks", insert_index)

    # 5) properties / Legend / filterByMap = false  (já gravamos, aqui só garantimos)
    properties_el = root.find("properties")
    if properties_el is None:
        properties_el = ET.Element("properties")
        root.append(properties_el)

    legend_prop_el = None
    for child in properties_el.findall("Legend"):
        legend_prop_el = child
    if legend_prop_el is None:
        legend_prop_el = ET.SubElement(properties_el, "Legend")

    filter_el = legend_prop_el.find("filterByMap")
    if filter_el is None:
        filter_el = ET.SubElement(legend_prop_el, "filterByMap", {"type": "bool"})
    filter_el.set("type", "bool")
    filter_el.text = "false"

    # 6) GPS apenas na camada final_gpkg
    # remove ProjectGpsSettings antigo, se existir
    for gps_old in root.findall("ProjectGpsSettings"):
        root.remove(gps_old)

    if "final_gpkg" in name_to_id:
        final_id = name_to_id["final_gpkg"]
        final_ds = datasource_for.get("final_gpkg", "./final/final_gpkg.gpkg")

        gps_el = ET.Element(
            "ProjectGpsSettings",
            {
                "autoCommitFeatures": "0",
                "destinationFollowsActiveLayer": "1",
                "autoAddTrackVertices": "0",
                "destinationLayerProvider": "ogr",
                "destinationLayer": final_id,
                "destinationLayerName": "final_gpkg",
                "destinationLayerSource": final_ds,
            },
        )
        ET.SubElement(gps_el, "timeStampFields")
        root.append(gps_el)

    # 7) reescrever o arquivo com DOCTYPE preservado
    new_xml = ET.tostring(root, encoding="unicode")
    if doctype:
        project_path.write_text(doctype + "\n" + new_xml, encoding="utf-8")
    else:
        project_path.write_text(new_xml, encoding="utf-8")

    print(f"🎉 Projeto salvo e pós-processado em {project_path}")
