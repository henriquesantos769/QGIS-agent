import sys
import os
import json
from pathlib import Path

# ---------------------------------------------------------
# ⚙️ Inicialização QGIS (isolada)
# ---------------------------------------------------------
from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsWkbTypes,
)

import processing
from processing.core.Processing import Processing

# ---------------------------------------------------------
# 📌 IMPORTA SEU PIPELINE
# ---------------------------------------------------------
from pipeline import (
    atribuir_ruas_frente,
    gerar_confrontacoes,
    calcular_medidas_e_azimutes,
    gerar_memoriais_em_lote,
    gerar_memorial_quadras_docx,
    obter_fuso_por_epsg,
    gerar_geometrias_quadras,
    segmentar_quadra_com_confrontantes,
    calcular_deflexoes_segmentos
)

def init_qgis():
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH"), True)
    qgs = QgsApplication([], False)
    qgs.initQgis()

    Processing.initialize()

    return qgs


# ---------------------------------------------------------
# 📊 Progresso (arquivo simples)
# ---------------------------------------------------------
def write_progress(out_dir: Path, etapa: int, mensagem: str):
    progress_file = out_dir / "progress.json"

    # escreve JSON (UTF-8, seguro)
    progress_file.write_text(
        json.dumps(
            {"etapa": etapa, "mensagem": mensagem},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # print ASCII-safe (sem emojis)
    safe_msg = mensagem.encode("ascii", "ignore").decode("ascii")
    print(f"[{etapa}] {safe_msg}", flush=True)



# ---------------------------------------------------------
# 🧠 Validação mínima das camadas
# ---------------------------------------------------------
def get_layer(project: QgsProject, name: str, geom_type=None, required=False):
    all_layers = list(project.mapLayers().values())
    available = [l.name() for l in all_layers]

    if not name:
        if required:
            raise RuntimeError(
                f"Nome da camada obrigatória não informado. "
                f"Camadas disponíveis: {available}"
            )
        return None

    layers = project.mapLayersByName(name)
    if not layers:
        raise RuntimeError(
            f"Camada '{name}' não encontrada. "
            f"Camadas disponíveis: {available}"
        )

    layer = layers[0]

    if geom_type is not None:
        if layer.geometryType() != geom_type:
            raise RuntimeError(
                f"Camada '{name}' possui geometria inválida"
            )

    if layer.featureCount() == 0:
        raise RuntimeError(f"Camada '{name}' está vazia")

    return layer

# ---------------------------------------------------------
# 🚀 MAIN
# ---------------------------------------------------------
def main():
    if len(sys.argv) < 4:
        print(
            "Uso: qgis_process.py <project.qgs> <out_dir> <session_key>",
            file=sys.stderr,
        )
        sys.exit(1)

    project_path = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    session_key = sys.argv[3]

    os.chdir(project_path.parent)

    # -----------------------------------------------------
    # 🟢 Inicializa QGIS (SEM GUI)
    # -----------------------------------------------------
    qgs = init_qgis()

    try:
        write_progress(out_dir, 4, "📂 Abrindo projeto QGIS...")

        project = QgsProject.instance()
        project.clear()


        if not project.read(str(project_path)):
            raise RuntimeError("Falha ao abrir o projeto QGIS")

        crs = project.crs().authid()
        fuso = obter_fuso_por_epsg(project.crs())
        print(f"CRS do projeto: {crs}")
        
        write_progress(out_dir, 5, "🧩 Validando camadas...")

        # lotes = get_layer(
        #     project,
        #     layers_cfg.get("lotes"),
        #     QgsWkbTypes.PolygonGeometry,
        #     required=True,
        # )

        # quadras = get_layer(
        #     project,
        #     layers_cfg.get("quadras"),
        #     QgsWkbTypes.PolygonGeometry,
        #     required=False,
        # )

        # ruas = get_layer(
        #     project,
        #     layers_cfg.get("ruas"),
        #     QgsWkbTypes.LineGeometry,
        #     required=False,
        # )

        write_progress(out_dir, 6, "🏗️ Processando lotes e quadras...")

        # pipeline_memorial_from_project(
        #     project=project,
        #     lotes=lotes,
        #     quadras=quadras,
        #     ruas=ruas,
        #     out_dir=out_dir,
        # )

        write_progress(out_dir, 10, "🏷️ Atribuindo ruas e esquinas...")
        atribuir_ruas_frente(out_dir, crs_epsg=int(crs.split(":")[1]))

        write_progress(out_dir, 12, "📐 Gerando confrontações...")
        gerar_confrontacoes(out_dir, epsg_lotes=int(crs.split(":")[1]))

        write_progress(out_dir, 14, "📏 Calculando medidas e azimutes...")
        calcular_medidas_e_azimutes(out_dir, epsg_lotes=int(crs.split(":")[1]))

        write_progress(out_dir, 16, "📝 Gerando memoriais dos lotes...")
        gerar_memoriais_em_lote(out_dir)

        write_progress(out_dir, 18, "📝 Gerando memoriais das quadras...")
        gerar_geometrias_quadras(out_dir, epsg_lotes=int(crs.split(":")[1]))
        segmentar_quadra_com_confrontantes(out_dir)
        calcular_deflexoes_segmentos(out_dir)
        gerar_memorial_quadras_docx(out_dir, fuso=fuso, epsg_default=int(crs.split(":")[1]))


        write_progress(out_dir, 20, "✅ Processamento concluído!")
        
    
    except Exception as e:
        write_progress(out_dir, 99, f"❌ Erro: {e}")
        raise

    finally:
        if qgs:
            qgs.exitQgis()


# ---------------------------------------------------------
if __name__ == "__main__":
    main()
