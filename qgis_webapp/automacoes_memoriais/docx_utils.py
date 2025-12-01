from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

def _fmt_num_br(x, casas=2):
    """Formata número float no padrão brasileiro, com vírgula."""
    if x is None:
        return ""
    return f"{x:.{casas}f}".replace(".", ",")

def _fmt_coord(x, casas=4):
    """Formata coordenada com 4 casas decimais, padrão BR."""
    return _fmt_num_br(x, casas=casas)

def _add_cabecalho_memorial(doc: Document,
                            titulo="MEMORIAL DESCRITIVO",
                            quadra=None,
                            nucleo=None,
                            municipio=None,
                            uf=None,
                            promotor=None):
    """Monta o cabeçalho padrão do memorial."""
    p = doc.add_paragraph()
    run = p.add_run(titulo)
    run.bold = True
    run.font.size = Pt(14)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if quadra is not None and nucleo and municipio and uf:
        p2 = doc.add_paragraph()
        texto_quad = f"QUADRA {quadra} - NÚCLEO {nucleo} – {municipio} - {uf}"
        run2 = p2.add_run(texto_quad)
        run2.bold = True
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()  # linha em branco

    if promotor or nucleo or municipio or uf:
        t = doc.add_paragraph()
        if promotor:
            t.add_run("Promotor da REURB: ").bold = True
            t.add_run(str(promotor) + "\n")
        if nucleo:
            t.add_run("Núcleo: ").bold = True
            t.add_run(str(nucleo) + "\n")
        if municipio or uf:
            t.add_run("Local: ").bold = True
            loc = municipio or ""
            if uf:
                loc += f" - {uf}"
            t.add_run(loc)

    doc.add_paragraph()  # espaço
    p3 = doc.add_paragraph()
    r3 = p3.add_run("DESCRIÇÃO")
    r3.bold = True
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()
