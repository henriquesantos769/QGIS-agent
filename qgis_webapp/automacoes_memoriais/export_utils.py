import os
import json
import pandas as pd
import geopandas as gpd
from pathlib import Path
from collections import defaultdict

def gerar_planilha_area_quadras_prepare(upload_dir, nome_camada="final_gpkg", 
                                        col_quadra="quadra", col_lote="lote_num"):
    """
    Lê o arquivo GPKG final e gera um JSON auxiliar com as áreas dos lotes,
    agrupadas por quadra.
    Usa Geopandas para evitar dependência do QGIS.
    """
    upload_dir = Path(upload_dir)
    path_final_gpkg = upload_dir / "final" / "final_gpkg.gpkg"
    out_json = upload_dir / "memoriais" / "planilha_area_quadras.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)

    if not path_final_gpkg.exists():
        raise FileNotFoundError(f"Arquivo GPKG não encontrado: {path_final_gpkg}")

    print(f"Lendo GPKG para planilha: {path_final_gpkg}")
    
    # Lê usando Geopandas (independente do QGIS)
    gdf = gpd.read_file(path_final_gpkg)
    
    if col_quadra not in gdf.columns:
         print(f"⚠ Coluna '{col_quadra}' não encontrada no GPKG. Colunas disponíveis: {list(gdf.columns)}")
         # Tenta fallback se existir 'Quadra' com maiúscula?
         if "Quadra" in gdf.columns:
             col_quadra = "Quadra"
    
    if col_lote not in gdf.columns:
         print(f"⚠ Coluna '{col_lote}' não encontrada no GPKG.")

    grupos = defaultdict(list)

    for _, row in gdf.iterrows():
        quadra = row.get(col_quadra)
        lote = row.get(col_lote)
        geom = row.geometry
        
        if quadra is None:
            continue
        
        area = 0.0
        if geom is not None and not geom.is_empty:
            area = geom.area

        grupos[quadra].append({
            "lote": lote,
            "area_m2": area
        })

    # prepara JSON serializável
    data = {str(k): v for k, v in grupos.items()}

    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Dados das quadras exportados -> {out_json}")
    return out_json


def gerar_planilha_area_quadras_xlsx(json_path, xlsx_path=None):
    """
    Gera o arquivo Excel a partir do JSON preparado.
    Robusto a falhas de lock de arquivo e falta de bibliotecas.
    """
    json_path = Path(json_path)
    if xlsx_path is None:
        xlsx_path = json_path.with_suffix(".xlsx")
    
    # Ensure string path for pandas safety
    xlsx_path_str = str(xlsx_path)

    print(f"Lendo JSON de: {json_path}")
    if not json_path.exists():
        print(f"❌ Arquivo JSON não encontrado: {json_path}")
        return None

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Erro ao ler/parsear JSON: {e}")
        return None

    # Verifica permissão de escrita / remove anterior
    if os.path.exists(xlsx_path_str):
        try:
            os.remove(xlsx_path_str)
            print("Arquivo Excel antigo removido.")
        except Exception as e:
            print(f"⚠ Aviso: Não foi possível remover arquivo existente: {e}")
            # Não damos raise aqui, deixamos o pandas tentar sobrescrever.

    # Definição do engine
    engine_to_use = "xlsxwriter"
    try:
        import xlsxwriter
    except ImportError:
        print("⚠ Biblioteca 'xlsxwriter' não encontrada. Usando 'openpyxl' (se disponível).")
        engine_to_use = "openpyxl"
    
    print(f"Iniciando criação do Excel em: {xlsx_path_str} (engine={engine_to_use})")
    
    try:
        with pd.ExcelWriter(xlsx_path_str, engine=engine_to_use) as writer:
            if not data:
                print("⚠ JSON vazio. Gerando aba 'Aviso'...")
                pd.DataFrame({"Status": ["Sem dados para gerar planilha"]}).to_excel(writer, sheet_name="Aviso", index=False)
            else:
                for quadra, registros in sorted(data.items(), key=lambda x: int(x[0])): # str key safe sort
                    # sheet name constraint (31 chars)
                    sheet_name = f"Quadra_{quadra}"[:31]
                    
                    print(f"  - Aba: {sheet_name} ({len(registros)} lotes)")
                    df = pd.DataFrame(registros).sort_values(by="lote")
                    
                    # Totalizador
                    if not df.empty and "area_m2" in df.columns:
                        area_total = df["area_m2"].sum()
                        row_total = {col: "" for col in df.columns}
                        row_total["lote"] = "Total"
                        row_total["area_m2"] = area_total
                        
                        df = pd.concat([df, pd.DataFrame([row_total])], ignore_index=True)

                        if "area_fmt" not in df.columns:
                            df["area_fmt"] = df["area_m2"].apply(lambda x: 
                                f"{x:,.2f} m²".replace(",", "X").replace(".", ",").replace("X", ".") if isinstance(x, (int, float)) else x
                            )

                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                
        print(f"✅ XLSX salvo com sucesso -> {xlsx_path_str}")

    except Exception as e:
        print(f"❌ Erro ao gerar Excel com engine '{engine_to_use}': {e}")
        if engine_to_use == "xlsxwriter":
            print("Tentando fallback para 'openpyxl'...")
            try:
                with pd.ExcelWriter(xlsx_path_str, engine="openpyxl") as writer:
                     if not data:
                        pd.DataFrame({"Status": ["Sem dados"]}).to_excel(writer, sheet_name="Aviso", index=False)
                     else:
                        for quadra, registros in sorted(data.items(), key=lambda x: str(x[0])):
                            sheet_name = f"Quadra_{quadra}"[:31]
                            df = pd.DataFrame(registros) 
                            df.to_excel(writer, sheet_name=sheet_name, index=False)
                print(f"✅ Recuperado! XLSX salvo com openpyxl -> {xlsx_path_str}")
            except Exception as e2:
                 print(f"❌ Fallback falhou também: {e2}")
                 raise e 
        else:
            raise

    return xlsx_path

def exportar_tabela_coordenadas_quadras(upload_dir, arquivo_segmentos="quadras_segmentos.gpkg"):
    upload_dir = Path(upload_dir)   
    path_seg = upload_dir / "final" / arquivo_segmentos
    gdf = gpd.read_file(path_seg).sort_values(["quadra", "seq"])

    quadras = sorted(gdf["quadra"].unique(), key=lambda x: int(x))

    saida = {}

    def fmt_coord(v):
        return f"{v:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def fmt_dist(v):
        return f"{v:,.2f} m".replace(",", "X").replace(".", ",").replace("X", ",")

    def fmt_dms(az):
        # az vem em graus decimais
        g = int(az)
        m_float = (az - g) * 60
        m = int(m_float)
        s = round((m_float - m) * 60)
        return f'{g}°{m:02d}\'{s:02d}"'

    for quadra in quadras:
        sub = gdf[gdf["quadra"] == quadra].copy().reset_index(drop=True)

        idx_inicio = sub["y1"].idxmax()
        sub = pd.concat([sub.loc[idx_inicio:], sub.loc[:idx_inicio]], ignore_index=True)

        registros = []

        for i, row in sub.iterrows():
            P1 = f"P{str(i+1).zfill(2)}"
            P2 = f"P{str(i+2).zfill(2)}" if i < len(sub)-1 else "P01"

            registros.append({
                "de": P1,
                "para": P2,
                "ny": fmt_coord(row["y1"]),
                "ex": fmt_coord(row["x1"]),
                "az": fmt_dms(row["azimute"]),
                "dist": fmt_dist(row["comprimento"])
            })

        saida[str(quadra)] = registros

    out = upload_dir / "memoriais" / "tabela_coordenadas_quadras.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Tabela de coordenadas exportada →", out)
    return out

def exportar_tabela_coordenadas_perimetro(
    upload_dir,
    arquivo_segmentos="perimetro_segmentos.gpkg"
):
    upload_dir = Path(upload_dir)
    path_seg = upload_dir / "final" / arquivo_segmentos
    gdf = gpd.read_file(path_seg)

    # --------------------------
    # Validação mínima
    # --------------------------
    required_cols = {"quadra", "x1", "y1", "azimute", "comprimento", "seq"}
    missing = required_cols - set(gdf.columns)
    if missing:
        raise RuntimeError(
            f"Arquivo {arquivo_segmentos} não possui colunas obrigatórias: {missing}"
        )

    # --------------------------
    # Para perímetro: usa uma única quadra
    # --------------------------
    quadras = gdf["quadra"].unique()
    if len(quadras) != 1:
        raise RuntimeError(
            f"Esperado apenas uma quadra (perímetro), encontrado: {quadras}"
        )

    quadra = quadras[0]
    sub = gdf[gdf["quadra"] == quadra].copy().reset_index(drop=True)

    # --------------------------
    # Reordenar a partir do ponto mais ao norte
    # --------------------------
    idx_inicio = sub["y1"].idxmax()
    sub = pd.concat(
        [sub.loc[idx_inicio:], sub.loc[:idx_inicio]],
        ignore_index=True
    )

    # --------------------------
    # Formatadores
    # --------------------------
    def fmt_coord(v):
        return f"{v:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def fmt_dist(v):
        return f"{v:,.2f} m".replace(",", "X").replace(".", ",").replace("X", ",")

    def fmt_dms(az):
        g = int(az)
        m_float = (az - g) * 60
        m = int(m_float)
        s = round((m_float - m) * 60)
        return f'{g}°{m:02d}\'{s:02d}"'

    # --------------------------
    # Montar registros
    # --------------------------
    registros = []

    for i, row in sub.iterrows():
        P1 = f"P{str(i+1).zfill(2)}"
        P2 = f"P{str(i+2).zfill(2)}" if i < len(sub)-1 else "P01"

        registros.append({
            "de": P1,
            "para": P2,
            "ny": fmt_coord(row["y1"]),
            "ex": fmt_coord(row["x1"]),
            "az": fmt_dms(row["azimute"]),
            "dist": fmt_dist(row["comprimento"])
        })

    # --------------------------
    # Salvar JSON
    # --------------------------
    out = upload_dir / "memoriais" / "tabela_coordenadas_perimetro.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(registros, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("Tabela de coordenadas exportada →", out)
    return out


def gerar_tabela_coordenadas_excel(json_path, xlsx_path=None):
    json_path = Path(json_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))

    if xlsx_path is None:
        xlsx_path = json_path.with_suffix(".xlsx")

    writer = pd.ExcelWriter(xlsx_path, engine="xlsxwriter")

    # --------------------------
    # CASO 1: QUADRAS (dict)
    # --------------------------
    if isinstance(data, dict):
        for quadra, registros in sorted(data.items(), key=lambda x: int(x[0])):
            df = pd.DataFrame(registros)
            df = df[["de", "para", "ny", "ex", "az", "dist"]]
            df.columns = [
                "De", "Para",
                "Coord. N(Y)", "Coord. E(X)",
                "Azimute", "Distância"
            ]
            df.to_excel(
                writer,
                sheet_name=f"Quadra_{quadra}",
                index=False
            )

    # --------------------------
    # CASO 2: PERÍMETRO (list)
    # --------------------------
    elif isinstance(data, list):
        df = pd.DataFrame(data)
        df = df[["de", "para", "ny", "ex", "az", "dist"]]
        df.columns = [
            "De", "Para",
            "Coord. N(Y)", "Coord. E(X)",
            "Azimute", "Distância"
        ]
        df.to_excel(
            writer,
            sheet_name="Perímetro",
            index=False
        )

    else:
        raise RuntimeError(
            f"Formato JSON não suportado: {type(data)}"
        )

    writer.close()
    print("Excel gerado →", xlsx_path)
    return xlsx_path

