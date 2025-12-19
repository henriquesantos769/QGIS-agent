from django.core.management.base import BaseCommand
from pathlib import Path
import os
import sys

from qgis.core import QgsApplication
from qgis.analysis import QgsNativeAlgorithms
from processing.core.Processing import Processing


class Command(BaseCommand):
    help = "Executa pipeline de memoriais usando QGIS"

    def add_arguments(self, parser):
        parser.add_argument("--project", required=True)
        parser.add_argument("--out", required=True)
        parser.add_argument("--lotes", required=True)
        parser.add_argument("--quadras", default="")
        parser.add_argument("--ruas", default="")

    def handle(self, *args, **opts):
        project_path = Path(opts["project"])
        out_dir = Path(opts["out"])
        layers_cfg = {
            "lotes": opts["lotes"],
            "quadras": opts["quadras"],
            "ruas": opts["ruas"],
        }

        # -----------------------------------
        # Inicializa QGIS (correto e simples)
        # -----------------------------------
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        qgs = QgsApplication([], False)
        qgs.initQgis()

        try:
            Processing.initialize()
            QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

            from automacoes_memoriais.pipeline import (
                pipeline_memorial_from_project,
                atribuir_ruas_frente,
                gerar_confrontacoes,
                calcular_medidas_e_azimutes,
                gerar_memoriais_em_lote,
                gerar_memorial_quadras_docx,
            )

            print("📂 Processando projeto QGIS…")
            pipeline_memorial_from_project(
                project_path=project_path,
                upload_dir=out_dir,
                layers_cfg=layers_cfg
            )

            atribuir_ruas_frente(out_dir)
            gerar_confrontacoes(out_dir)
            calcular_medidas_e_azimutes(out_dir)
            gerar_memoriais_em_lote(out_dir)
            gerar_memorial_quadras_docx(out_dir)

            print("✅ Memoriais gerados com sucesso")

        finally:
            qgs.exitQgis()
