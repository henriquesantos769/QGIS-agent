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
    QgsSingleSymbolRenderer
)
from PyQt5.QtGui import QColor, QFont

def stylize_layer_lotes(layer):
    if not layer or not layer.isValid():
        print("❌ Camada inválida para estilização.")
        return

    # 👉 NÃO mexe no renderer aqui, deixa o categorizado em paz
    # Só configura rótulos

    label_settings = QgsPalLayerSettings()
    text_format = QgsTextFormat()

    text_format.setFont(QFont("Arial", 13))
    text_format.setSize(13)
    text_format.setColor(QColor("#092DDC"))

    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(1.2)
    buffer_settings.setOpacity(0.95)
    buffer_settings.setColor(QColor("#FFFFFF"))
    text_format.setBuffer(buffer_settings)

    label_settings.setFormat(text_format)
    label_settings.fieldName = "lote_num"
    label_settings.enabled = True

    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)

    layer.triggerRepaint()
    print("✨ Rótulos aplicados à camada de lotes (renderer preservado).")

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
        'color': "#0B48FF",   # amarelo
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

