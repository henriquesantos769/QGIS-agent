import threading

def processar_automacao(upload_dir, caminho_arquivo, request):
    try:
        request.session["etapa"] = 1
        load_and_split_dxf(caminho_arquivo, upload_dir)

        request.session["etapa"] = 2
        convert_lines_to_polygons(upload_dir)

        request.session["etapa"] = 3
        join_by_location_summary_lotes(upload_dir)

        request.session["etapa"] = 4
        join_by_location_summary_quadras(upload_dir)

        request.session["etapa"] = 5
        join_by_location_summary_final(upload_dir)

        request.session["etapa"] = 6
    except Exception as e:
        request.session["etapa"] = -1
        print("Erro no processamento:", e)
