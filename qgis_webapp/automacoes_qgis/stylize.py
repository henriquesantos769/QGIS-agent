from qgis.core import (
    QgsVectorLayerSimpleLabeling,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsLineSymbol,
    QgsSimpleFillSymbolLayer,
    QgsTextBufferSettings,
    QgsSymbol,
    QgsMarkerSymbol,
    QgsWkbTypes,
    QgsUnitTypes,
    QgsSingleSymbolRenderer,
    QgsRuleBasedLabeling,
    Qgis
)
from PyQt5.QtGui import QColor, QFont

def aplicar_rotulos_lotes_numero_e_area(layer):
    if not layer or not layer.isValid():
        print("❌ Camada inválida para rótulos.")
        return

    # ===============================
    # 🔹 RÓTULO 1 — NÚMERO DO LOTE
    # ===============================
    num_settings = QgsPalLayerSettings()
    num_settings.isExpression = False
    num_settings.fieldName = "lote_num"
    num_settings.placement = Qgis.LabelPlacement.OverPoint
    num_settings.centroidInside = True
    num_settings.allowOverlap = True

    num_format = QgsTextFormat()
    num_format.setFont(QFont("Arial", 13, QFont.Bold))
    num_format.setColor(QColor("#092DDC"))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.2)
    buffer.setColor(QColor("#FFFFFF"))
    num_format.setBuffer(buffer)

    num_settings.setFormat(num_format)

    rule_num = QgsRuleBasedLabeling.Rule(num_settings)

    # ===============================
    # 🔹 RÓTULO 2 — ÁREA DO LOTE
    # ===============================
    area_settings = QgsPalLayerSettings()
    area_settings.isExpression = True
    area_settings.fieldName = "format_number($area, 2) || ' m²'"
    area_settings.placement = Qgis.LabelPlacement.OverPoint
    area_settings.centroidInside = True

    # 🔽 deslocamento para baixo (mm)
    area_settings.yOffset = -5.0

    area_settings.allowOverlap = True
    area_settings.displayAll = True

    area_format = QgsTextFormat()
    area_format.setFont(QFont("Arial", 9))
    area_format.setColor(QColor("#55A4FF"))

    area_settings.setFormat(area_format)

    rule_area = QgsRuleBasedLabeling.Rule(area_settings)

    # ===============================
    # 🔹 COMBINAR OS DOIS RÓTULOS
    # ===============================
    root_rule = QgsRuleBasedLabeling.Rule(None)
    root_rule.appendChild(rule_num)
    root_rule.appendChild(rule_area)

    labeling = QgsRuleBasedLabeling(root_rule)

    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()

    print("✨ Rótulos de número + área aplicados com sucesso.")

def stylize_layer_ruas(layer):
    """
    Aplica estilo visual à camada de ruas:
    - Linha amarela com espessura 0.5
    - Rótulos azuis com buffer branco baseados na coluna 'name'
    """
    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    # ===================== ESTILO DAS LINHAS =====================
    symbol = QgsLineSymbol.createSimple({
        'color': "#0B48FF",   
        'width': '0.5',
        'penstyle': 'solid'
    })
    layer.renderer().setSymbol(symbol)

    # ===================== CONFIGURAÇÃO DE RÓTULOS =====================
    label_settings = QgsPalLayerSettings()
    text_format = QgsTextFormat()

    text_format.setFont(QFont("Arial", 12))
    text_format.setSize(12)
    text_format.setColor(QColor("#0270F7"))  # azul
    # text_format.setSizeUnit(QgsUnitTypes.RenderMapUnits)

    # ---------- CONFIGURAÇÃO DO BUFFER (contorno branco) ----------
    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(1.2)
    buffer_settings.setColor(QColor("#FFFFFF"))
    buffer_settings.setOpacity(0.95)
    text_format.setBuffer(buffer_settings)  # aplica o buffer antes de setar o formato

    # ---------- CONFIGURAÇÃO FINAL DE RÓTULOS ----------
    label_settings.setFormat(text_format)
    label_settings.fieldName = "name"   # coluna de nomes das ruas
    label_settings.enabled = True
    label_settings.placement = QgsPalLayerSettings.Line  # rótulo segue o traçado da via

    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)

    layer.triggerRepaint()
    print("✨ Estilo aplicado com sucesso à camada de ruas (rótulos com buffer branco).")

def stylize_layer_quadras(layer):
    """
    Estilo 'neon vermelho' para quadras:
    - Esconde o ponto
    - Mostra apenas o valor do campo 'quadra' com efeito de brilho vermelho
    """
    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    # ===================== ESCONDE O PONTO =====================
    symbol = QgsMarkerSymbol.createSimple({
        "color": "255,255,255,0",         # totalmente transparente
        "outline_color": "255,255,255,0", # sem contorno
        "size": "0"                       # sem marcador visível
    })
    layer.renderer().setSymbol(symbol)

    # ===================== CONFIGURAÇÃO DE RÓTULOS =====================
    label_settings = QgsPalLayerSettings()
    text_format = QgsTextFormat()

    # Texto principal (vermelho "neon")
    text_format.setFont(QFont("Arial Black", 14))
    text_format.setSize(14)
    text_format.setColor(QColor("#1820FA"))  # vermelho bem vivo
    # text_format.setSizeUnit(QgsUnitTypes.RenderMapUnits)

    # Buffer simulando brilho em volta do texto
    glow_buffer = QgsTextBufferSettings()
    glow_buffer.setEnabled(True)
    glow_buffer.setSize(1.8)  # halo largo
    glow_buffer.setColor(QColor("#FA0505"))  
    text_format.setBuffer(glow_buffer)
    text_format.setOpacity(1.0)

    label_settings.setFormat(text_format)
    label_settings.fieldName = "quadra"  # campo numérico das quadras
    label_settings.enabled = True

    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)

    layer.triggerRepaint()
    print("✨ Camada de quadras estilizada: números em 'neon' vermelho, pontos ocultos.")

def stylize_layer_outros(layer):
    """
    Estilo para camada 'outros':
    - Linha lilás forte
    - Texto vermelho com buffer branco
    - Compatível com LineString e Point
    """
    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    geom_type = layer.geometryType()

    # ===================== ESTILO DA GEOMETRIA =====================
    if geom_type == QgsWkbTypes.LineGeometry:
        # ---- Linha lilás forte ----
        symbol = QgsLineSymbol.createSimple({
            'color': '#B100FF',   # lilás forte
            'width': '0.7',
            'penstyle': 'solid'
        })
        layer.renderer().setSymbol(symbol)

    elif geom_type == QgsWkbTypes.PointGeometry:
        # ---- Ponto discreto (quase invisível) ----
        symbol = QgsMarkerSymbol.createSimple({
            "color": "177,0,255,80",          # lilás translúcido
            "outline_color": "177,0,255,180",
            "size": "1.6"
        })
        layer.renderer().setSymbol(symbol)

    # ===================== CONFIGURAÇÃO DE RÓTULOS =====================
    label_settings = QgsPalLayerSettings()
    text_format = QgsTextFormat()

    # Texto vermelho
    text_format.setFont(QFont("Arial", 11))
    text_format.setSize(11)
    text_format.setColor(QColor("#E60000"))  # vermelho forte

    # Buffer branco para legibilidade
    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(1.2)
    buffer_settings.setColor(QColor("#FFFFFF"))
    buffer_settings.setOpacity(0.95)
    text_format.setBuffer(buffer_settings)

    label_settings.setFormat(text_format)

    # Campo de texto (padrão do seu pipeline)
    if "nome" in layer.fields().names():
        label_settings.fieldName = "nome"
    elif "Text" in layer.fields().names():
        label_settings.fieldName = "Text"
    elif "text" in layer.fields().names():
        label_settings.fieldName = "text"
    else:
        print("⚠️ Nenhum campo de texto encontrado para rótulo em 'outros'.")
        return

    label_settings.enabled = True

    # Posicionamento de rótulo
    if geom_type == QgsWkbTypes.LineGeometry:
        label_settings.placement = QgsPalLayerSettings.Line

    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)

    layer.triggerRepaint()
    print("✨ Estilo aplicado à camada 'outros' (linha lilás, texto vermelho).")