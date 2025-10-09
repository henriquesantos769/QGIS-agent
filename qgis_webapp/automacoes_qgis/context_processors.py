def progresso(request):
    etapa = int(request.session.get("etapa", 0))
    total = 6  # total de etapas do pipeline
    pct = int(round((etapa / total) * 100)) if total else 0
    return {
        "progress_etapa": etapa,
        "progress_total": total,
        "progress_pct": f"{pct}%",  
    }
