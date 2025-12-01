from django.urls import path
from .views import home, progresso, resetar_progresso, gerar_memoriais, baixar_memoriais

urlpatterns = [
    path("", home, name="home_memoriais"),
    path("progresso/", progresso, name="progresso_memoriais"),
    path("resetar_progresso/", resetar_progresso, name="resetar_memoriais"),
    path("gerar_memoriais/", gerar_memoriais, name="gerar_memoriais"),
    path("download/", baixar_memoriais, name="baixar_memoriais"),
]
