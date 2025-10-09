import subprocess
import os

# Caminho do executável do ODA Converter
ODA_PATH = r"C:\Program Files\ODA\ODAFileConverter 26.8.0\ODAFileConverter.exe"

# Diretórios de entrada e saída
INPUT_FOLDER = r"C:\Users\mario\Documents\estudos\instituto_legal\QGIS-agent\Arquivo Qgis"
OUTPUT_FOLDER = r"C:\Users\mario\Documents\estudos\instituto_legal\QGIS-agent\Arquivo Qgis (DXF)"

# Configurações
INPUT_FILTER = "*.DWG"
OUTPUT_VERSION = "R14 ASCII DXF"
RECURSE_FOLDERS = "0"  # 0 = não, 1 = sim
AUDIT = "1"             # 1 = audit ativo, 0 = desativado

# Comando completo
command = [
    ODA_PATH,
    INPUT_FOLDER,
    OUTPUT_FOLDER,
    INPUT_FILTER,
    OUTPUT_VERSION,
    RECURSE_FOLDERS,
    AUDIT
]

print("🔄 Iniciando conversão DWG → DXF...")
print("Comando:", " ".join(command))

# Executa o ODA Converter
try:
    subprocess.run(command, check=True)
    print("Conversão concluída com sucesso!")
except subprocess.CalledProcessError as e:
    print("Erro na conversão:", e)
except FileNotFoundError:
    print("Caminho do ODAFileConverter não encontrado. Verifique se está instalado corretamente.")
