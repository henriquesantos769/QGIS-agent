import shutil
import os
from pathlib import Path

def package_project_for_qfield(project_file: Path, export_folder: Path, include_data_folders: list = None):
    """
    Empacota o projeto QGIS para uso no QField / QField Cloud.
    - project_file: caminho para o arquivo .qgz/.qgs
    - export_folder: pasta onde o pacote será criado/copied
    - include_data_folders: lista de pastas relativas (a partir de projeto) que devem ser incluídas
    """
    if include_data_folders is None:
        include_data_folders = []

    # 1) cria pasta de exportação limpa
    if export_folder.exists():
        shutil.rmtree(export_folder)
    export_folder.mkdir(parents=True)

    # 2) copia o arquivo de projeto
    shutil.copy2(str(project_file), str(export_folder / project_file.name))

    # 3) copia pastas de dados
    for rel in include_data_folders:
        src = project_file.parent / rel
        dst = export_folder / rel
        if src.exists():
            shutil.copytree(str(src), str(dst))
        else:
            print(f"⚠️ Pasta de dados não encontrada: {src}")

    # 4) (opcional) gerar arquivo .cpg ou metadata para encoding, conforme necessidade
    print(f"📦 Projeto empacotado em: {export_folder}")

    # 5) (Extra) você pode automatizar o upload via API do QField Cloud se tiver credenciais/endpoint
    # Por enquanto: manual upload em https://cloud.qfield.org ou via plugin QFieldSync
    
    return export_folder