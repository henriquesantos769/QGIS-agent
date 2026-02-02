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
    Qgis,
    QgsFillSymbol,
    QgsProperty
)
from PyQt5.QtGui import QColor, QFont

def stylize_rotulos_lotes(layer):
    """
    Rótulo do número do lote:
    - Fica fora do centro
    - Não colide com a área
    - Sempre visível
    """

    if not layer or not layer.isValid():
        print("❌ Camada inválida.")
        return

    settings = QgsPalLayerSettings()
    settings.isExpression = True
    settings.fieldName = '"lote_num"'

    # 🔥 ESSENCIAL: fora do centro
    settings.placement = Qgis.LabelPlacement.AroundPoint
    settings.centroidInside = False
    settings.allowOverlap = True
    settings.obstacle = False
    settings.zIndex = 10

    # 🔹 Distância do centro (em mm na tela)
    settings.dist = 4.0

    # 🔹 Preferência lateral (direita)
    settings.quadrant = QgsPalLayerSettings.QuadrantRight

    # ----------------------------
    # Estilo
    # ----------------------------
    text = QgsTextFormat()
    text.setFont(QFont("Arial", 13, QFont.Bold))
    text.setColor(QColor("#092DDC"))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setColor(QColor("white"))
    buffer.setSize(1.2)

    text.setBuffer(buffer)
    settings.setFormat(text)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()

    print("✅ Rótulos de número posicionados fora do centro.")

def stylize_rotulos_area(layer):
    if not layer or not layer.isValid():
        print("❌ Camada inválida.")
        return

    settings = QgsPalLayerSettings()
    settings.isExpression = True
    settings.fieldName = 'format_number("area_m2", 2) || \' m²\''

    settings.placement = Qgis.LabelPlacement.OverPoint
    settings.centroidInside = True
    settings.allowOverlap = True
    settings.obstacle = False
    settings.zIndex = 5

    text = QgsTextFormat()
    text.setFont(QFont("Arial", 9))
    text.setColor(QColor("#4A90E2"))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setColor(QColor("white"))
    buffer.setSize(1.1)

    text.setBuffer(buffer)
    settings.setFormat(text)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()

    print("✅ Rótulos de área centralizados.")

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
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))

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


def stylize_layer_quadras_rotulos(layer):
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
    text_format.setColor(QColor("#FA0505"))  # vermelho bem vivo
    # text_format.setSizeUnit(QgsUnitTypes.RenderMapUnits)

    # Buffer simulando brilho em volta do texto
    glow_buffer = QgsTextBufferSettings()
    glow_buffer.setEnabled(True)
    glow_buffer.setSize(1.8)  # halo largo
    glow_buffer.setColor(QColor("#FFFFFF"))  
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

def stylize_layer_quadras(layer):
    """
    Aplica estilo à camada de quadras:
    - Sem preenchimento
    - Apenas contorno visível
    """

    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    # Criar símbolo sem preenchimento
    symbol = QgsFillSymbol.createSimple({
        "color": "0,0,0,0",           # totalmente transparente
        "outline_color": "#FFF700",   # amarelo
        "outline_width": "0.0",
        "outline_style": "solid"
    })

    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()

    print("✨ Camada de quadras estilizada (apenas contorno).")

def stylize_layer_perimetro(layer):
    """
    Aplica estilo à camada de perimetro:
    - Sem preenchimento
    - Apenas contorno visível
    """

    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    # Criar símbolo sem preenchimento
    symbol = QgsFillSymbol.createSimple({
        "color": "0,0,0,0",           # totalmente transparente
        "outline_color": "#FF00FF",   # rosa
        "outline_width": "0.0",
        "outline_style": "solid"
    })

    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()

    print("✨ Camada de quadras estilizada (apenas contorno).")

def stylize_layer_outros(layer):
    """
    Aplica estilo visual à camada de limitantes:
    - Linha amarela com espessura 0.5
    - Rótulos azuis com buffer branco baseados na coluna 'name'
    """
    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    # ===================== ESTILO DAS LINHAS =====================
    symbol = QgsLineSymbol.createSimple({
        'color': "#0BFFEB",   
        'width': '0.5',
        'penstyle': 'solid'
    })
    layer.renderer().setSymbol(symbol)

    # ===================== CONFIGURAÇÃO DE RÓTULOS =====================
    label_settings = QgsPalLayerSettings()
    text_format = QgsTextFormat()

    text_format.setFont(QFont("Arial", 12))
    text_format.setSize(12)
    text_format.setColor(QColor("#0BFFEB"))  # azul
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
    label_settings.fieldName = "name"   # coluna de nomes das limitantes
    label_settings.enabled = True
    label_settings.placement = QgsPalLayerSettings.Line  # rótulo segue o traçado da via

    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)

    layer.triggerRepaint()
    print("✨ Estilo aplicado com sucesso à camada de limitantes (rótulos com buffer branco).")

def stylize_layer_vertices(layer):
    if not layer or not layer.isValid():
        print("❌ Camada inválida de vértices.")
        return

    # --------------------------------------------------
    # 🎯 SÍMBOLO DO PONTO
    # --------------------------------------------------
    symbol = QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": "#FFFFFF",          # preenchimento branco
        "outline_color": "#2ECC71",  # verde
        "outline_width": "0.8",
        "size": "3.0"
    })

    # tamanho fixo na tela
    symbol.setSizeUnit(QgsUnitTypes.RenderMillimeters)

    layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    # --------------------------------------------------
    # 🔤 RÓTULOS (P01, P02, ...)
    # --------------------------------------------------
    settings = QgsPalLayerSettings()
    settings.enabled = True
    settings.fieldName = "vertice"
    settings.isExpression = False

    # 🔥 ENUM CORRETO
    settings.placement = Qgis.LabelPlacement.OverPoint

    settings.allowOverlap = True
    settings.displayAll = True

    text_format = QgsTextFormat()
    text_format.setFont(QFont("Arial", 9, QFont.Bold))
    text_format.setColor(QColor("#000000"))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setColor(QColor("#FFFFFF"))
    buffer.setSize(1.0)

    text_format.setBuffer(buffer)

    # tamanho fixo do texto
    text_format.setSize(9)
    text_format.setSizeUnit(QgsUnitTypes.RenderPoints)

    settings.setFormat(text_format)

    labeling = QgsVectorLayerSimpleLabeling(settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)

    layer.triggerRepaint()

    print("✨ Vértices estilizados com rótulos visíveis (P01, P02...).")

def stylize_layer_segs_lotes(layer):
    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    print("🎨 Aplicando estilo na camada de segmentos...")

    # ===================== ESTILO DAS LINHAS =====================
    symbol = QgsLineSymbol.createSimple({
        'color': "#E67E22",   # laranja queimado (diferencia bem de rua e lote)
        'width': '0.0',
        'penstyle': 'solid'
    })
    layer.renderer().setSymbol(symbol)

    # ===================== CONFIGURAÇÃO DE RÓTULOS =====================
    label_settings = QgsPalLayerSettings()
    text_format = QgsTextFormat()

    text_format.setFont(QFont("Arial", 12))
    text_format.setSize(12)
    text_format.setColor(QColor("#FFF200"))
    text_format.setSizeUnit(QgsUnitTypes.RenderPoints)

    # ---------- BUFFER (contorno branco melhora leitura em campo) ----------
    buffer = text_format.buffer()
    buffer.setEnabled(True)
    buffer.setColor(QColor("#FFFFFF"))
    buffer.setSize(1.2)
    buffer.setSizeUnit(QgsUnitTypes.RenderPoints)
    text_format.setBuffer(buffer)

    label_settings.setFormat(text_format)

    # texto: apenas o segment_id
    label_settings.fieldName = "segment_id"
    label_settings.placement = QgsPalLayerSettings.Line
    label_settings.placementFlags = QgsPalLayerSettings.AboveLine

    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)

    layer.triggerRepaint()

    print("✅ Estilização aplicada.")