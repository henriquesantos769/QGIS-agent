import os
import sys
import atexit

def setup_qgis_env():
    """Configura completamente o ambiente do QGIS no Windows standalone"""
    
    # --- Caminhos principais do QGIS ---
    QGIS_PREFIX_PATH = r"C:\Program Files\QGIS 3.40.11\apps\qgis-ltr"
    QGIS_BIN_PATH = r"C:\Program Files\QGIS 3.40.11\bin"
    QGIS_PYTHON_PATH = os.path.join(QGIS_PREFIX_PATH, "python")
    QGIS_SITE_PACKAGES = r"C:\Program Files\QGIS 3.40.11\apps\Python312\Lib\site-packages"
    QT_PLUGIN_PATH = r"C:\Program Files\QGIS 3.40.11\apps\Qt5\plugins"

    # --- Adiciona pastas do QGIS no sys.path ---
    paths_to_add = [
        QGIS_SITE_PACKAGES,
        QGIS_PYTHON_PATH,
        os.path.join(QGIS_PYTHON_PATH, "qgis"),
        os.path.join(QGIS_PYTHON_PATH, "plugins"),
    ]
    for p in paths_to_add:
        if os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    # --- Define variáveis de ambiente ---
    os.environ["QGIS_PREFIX_PATH"] = QGIS_PREFIX_PATH
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = QT_PLUGIN_PATH

    os.environ["PATH"] = (
        QGIS_BIN_PATH
        + os.pathsep
        + os.path.join(QGIS_PREFIX_PATH, "bin")
        + os.pathsep
        + os.environ.get("PATH", "")
    )

    # --- Teste visual para depuração ---
    print("\n✅ QGIS_ENV configurado com sucesso!")
    print("PYTHONPATH:")
    for p in sys.path[:6]:
        print("   ", p)
    print("QGIS_PREFIX_PATH:", os.environ.get("QGIS_PREFIX_PATH"))
    print("PATH contém qgis-ltr/bin?", "qgis-ltr\\bin" in os.environ["PATH"])
    print()


def init_qgis():
    """Inicializa o QGIS após o ambiente estar configurado"""
    try:
        from qgis.core import QgsApplication
    except ImportError as e:
        print("❌ Falha ao importar qgis.core:", e)
        print("Verifique se setup_qgis_env() foi chamado ANTES do Django iniciar.")
        raise

    QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
    qgs = QgsApplication([], False)
    qgs.initQgis()

    print("✅ QGIS inicializado com sucesso!")

    @atexit.register
    def cleanup_qgis():
        QgsApplication.exitQgis()

    return qgs
