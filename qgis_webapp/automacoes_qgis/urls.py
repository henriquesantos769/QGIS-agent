from django.urls import path
from .views import (upload_dxf, converter_para_qgis, download_pacote_zip,
                    visualizar_shp, voltar_para_etapa, status_progresso)

urlpatterns = [
    path("", upload_dxf, name="upload_dxf"),
    path("converter_qgis/", converter_para_qgis, name="converter_para_qgis"),
    path("visualizar/", visualizar_shp, name="visualizar_shp"),
    path("voltar_etapa/", voltar_para_etapa, name="voltar_etapa"),
    path("status_progresso/", status_progresso, name="status_progresso"),
    path("download_pacote/", download_pacote_zip, name="download_pacote_zip"),

]
