from django.urls import path
from .views import (criar_projeto_qgis, enviar_para_qfieldcloud,
                     home, download_pacote_zip, progresso, progresso_qfield,
                     tentar_overpass, resetar_progresso, baixar_e_enviar_qfieldcloud)

urlpatterns = [
    path("", home, name="home"),
    path("baixar_e_enviar_qfieldcloud/", baixar_e_enviar_qfieldcloud, name="baixar_e_enviar_qfieldcloud"),
    path("criar_projeto_qgis/", criar_projeto_qgis, name="criar_projeto_qgis"),
    path("exportar-qfield/", enviar_para_qfieldcloud, name="exportar_qfield"),
    path("download_pacote/", download_pacote_zip, name="download_pacote_zip"),
    path("progresso/", progresso, name="progresso"),
    path("progresso_qfield/", progresso_qfield, name="progresso_qfield"),
    path("tentar_overpass/", tentar_overpass, name="tentar_overpass"),
    path("resetar_progresso/", resetar_progresso, name="resetar_progresso"),
]
