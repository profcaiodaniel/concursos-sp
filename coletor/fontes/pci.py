"""PCI Concursos: listagem de concursos abertos (secao Sao Paulo e nacional).

O PCI e um agregador: serve para descobrir o concurso. O link primario
(banca ou orgao) e extraido da pagina de detalhe quando existe.
"""
from __future__ import annotations

import html
import re

from ..base import Cliente, ErroFonte, data_br, dinheiro, limpa_html

URL_SUDESTE = "https://www.pciconcursos.com.br/concursos/sudeste/"
URL_NACIONAL = "https://www.pciconcursos.com.br/concursos/nacional/"

RE_ITEM = re.compile(
    r'<div class="(?:da|na|ea)"[^>]*data-url="(?P<url>[^"]+)"[^>]*>\s*'
    r'<div class="ca"><a [^>]*title="(?P<titulo>[^"]*)"[^>]*>(?P<orgao>.*?)</a>'
    r'.*?<div class="cc">(?P<uf>[^<]*)</div>\s*'
    r'<div class="cd">(?P<cd>.*?)</div>\s*<div class="ce">(?P<ce>.*?)</div>',
    re.S)


def _periodo(ce: str) -> tuple[str | None, str | None, str]:
    """Extrai (inicio, fim, texto_bruto) do campo de inscricao."""
    txt = limpa_html(ce).replace("\n", " ")
    fim = None
    datas = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", txt)
    if datas:
        fim = data_br(datas[-1])
    inicio = None
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s*a\s*(\d{1,2})/(\d{1,2})/(\d{4})", txt)
    if m:
        ano_fim = int(m.group(6))
        ano_ini = int(m.group(3)) if m.group(3) else (ano_fim - 1 if int(m.group(2)) > int(m.group(5)) else ano_fim)
        inicio = data_br(f"{m.group(1)}/{m.group(2)}/{ano_ini}")
    return inicio, fim, txt


def _cd(cd: str) -> dict:
    """'29 vagas até R$ 13.359,44<br><span>Cargos<br><span>Escolaridade</span></span>'"""
    partes = [limpa_html(p).replace("\n", " ").strip() for p in re.split(r"<br\s*/?>", cd)]
    partes = [p for p in partes if p]
    cab = partes[0] if partes else ""
    vagas = None
    m = re.search(r"(\d[\d.]*)\s+vagas?", cab, re.I)
    if m:
        vagas = int(m.group(1).replace(".", ""))
    cr = bool(re.search(r"cadastro\s+(de\s+)?reserva|\bCR\b", cab, re.I))
    escolaridade = []
    if len(partes) >= 2:
        ult = partes[-1]
        for nome, rx in [("fundamental", r"fundamental|alfabetizad"), ("médio", r"m[ée]dio"),
                         ("técnico", r"t[ée]cnico"), ("superior", r"superior")]:
            if re.search(rx, ult, re.I):
                escolaridade.append(nome)
    cargos = partes[1] if len(partes) >= 3 else (partes[1] if len(partes) == 2 and not escolaridade else None)
    return {"vagas": vagas, "cadastro_reserva": cr, "salario_ate": dinheiro(cab),
            "vagas_texto": cab, "cargos": cargos, "escolaridade": escolaridade}


def parse_listagem(pagina: str, secao: str | None) -> list[dict]:
    """Le uma listagem. `secao` = nome da UF em maiusculas ('SÃO PAULO') ou None para a pagina toda."""
    if secao:
        a = pagina.find(f'<div class="uf">{secao}</div>')
        if a < 0:
            raise ErroFonte(f"PCI: seção {secao} não encontrada (layout mudou?)")
        b = pagina.find('<div class="uf">', a + 10)
        pagina = pagina[a: b if b > 0 else len(pagina)]
    itens = []
    for m in RE_ITEM.finditer(pagina):
        inicio, fim, bruto = _periodo(m.group("ce"))
        d = _cd(m.group("cd"))
        itens.append({
            "url_pci": html.unescape(m.group("url")),
            "titulo": html.unescape(m.group("titulo")).strip(),
            "orgao": limpa_html(m.group("orgao")).strip(),
            "uf": limpa_html(m.group("uf")).strip(),
            "inscricao_inicio": inicio, "inscricao_fim": fim, "inscricao_texto": bruto, **d,
        })
    return itens


# ------------------------------------------------------------------ detalhe
BANCAS = {
    "Vunesp": r"\bvunesp\b", "FGV": r"\bFGV\b|funda[cç][aã]o get[uú]lio vargas", "Cebraspe": r"cebraspe|\bcespe\b",
    "FCC": r"\bFCC\b|funda[cç][aã]o carlos chagas", "IBFC": r"\bIBFC\b", "Instituto Mais": r"instituto mais",
    "Avança SP": r"avan[cç]a\s?sp", "Nosso Rumo": r"nosso rumo", "RBO": r"\bRBO\b", "IBAM": r"\bIBAM\b",
    "Consulplan": r"consulplan", "SHDias": r"sh\s?dias", "Publiconsult": r"publiconsult", "Indepac": r"indepac",
    "Zambini": r"zambini", "AOCP": r"\bAOCP\b", "Access": r"instituto access|\baccess\b", "Dédalus": r"d[ée]dalus",
    "Aplicativa": r"aplicativa", "Consesp": r"consesp", "Conscam": r"conscam", "Fundatec": r"fundatec",
    "Cesgranrio": r"cesgranrio", "Idecan": r"idecan", "Quadrix": r"quadrix", "Selecon": r"selecon",
    "Fundação Vunesp": r"funda[cç][aã]o vunesp", "Instituto Unifil": r"unifil", "Omni": r"\bomni\b",
    "GL Consultoria": r"gl consultoria", "Integri Brasil": r"integri", "Abcp": r"\bABCP\b",
    "Instituto Excelência": r"instituto excel[êe]ncia", "MS Concursos": r"ms concursos",
    "Exatus": r"exatus", "Orhion": r"orhion", "Apta": r"\bapta assessoria", "Sigma": r"sigma assessoria",
    "Agirh": r"\bagirh\b", "Direta": r"direta carreiras", "Ameosc": r"ameosc", "Ibade": r"\bibade\b",
    "Fepese": r"fepese", "Legalle": r"legalle", "Cetap": r"\bcetap\b", "Objetiva": r"objetiva concursos",
    "Mouramelo": r"moura\s?melo", "Líder": r"l[ií]der consultoria", "Fapec": r"\bfapec\b",
    "Coseac": r"coseac", "Copeve": r"copeve", "Avalia": r"instituto avalia", "IUDS": r"\bIUDS\b",
    "Igecs": r"\bigecs\b", "Ipefae": r"ipefae", "Metrocapital": r"metrocapital", "Unisa": r"\bunisa\b",
    "Nova Concursos": r"nova concursos", "Instituto Indec": r"\bindec\b", "Cemat": r"\bcemat\b",
    "Planexcon": r"planexcon", "Ibrasp": r"ibrasp", "Epl": r"\bEPL concursos", "Itame": r"\bitame\b",
    "Ganzaroli": r"ganzaroli", "Instituto Zambini": r"instituto zambini", "Fundep": r"fundep",
    "Funcab": r"funcab", "Iades": r"\biades\b", "Idib": r"\bidib\b", "Cev": r"\bCEV[- ]UECE",
}
RE_DOMINIO_PCI = re.compile(r"pciconcursos|pci\.app\.br|facebook|twitter|whatsapp|instagram|youtube|t\.me|google|linkedin", re.I)


def parse_detalhe(pagina: str) -> dict:
    """Extrai da noticia do PCI: banca citada, links externos e o texto."""
    m = re.search(r'<article[^>]*>(.*?)</article>', pagina, re.S | re.I) or \
        re.search(r'itemprop="articleBody"[^>]*>(.*?)</div>\s*</div>', pagina, re.S | re.I)
    corpo = m.group(1) if m else pagina
    texto = limpa_html(corpo)
    bancas = []
    for nome, rx in BANCAS.items():
        if re.search(rx, texto, re.I if not rx.startswith(r"\b") or rx.islower() else 0):
            bancas.append(nome)
    # nomes compostos ganham dos simples
    if "Fundação Vunesp" in bancas:
        bancas = [b for b in bancas if b != "Fundação Vunesp"] + ([] if "Vunesp" in bancas else ["Vunesp"])
    if "Instituto Zambini" in bancas:
        bancas = [b for b in bancas if b != "Instituto Zambini"] + ([] if "Zambini" in bancas else ["Zambini"])
    links = []
    for href in re.findall(r'href="(https?://[^"]+)"', corpo):
        href = html.unescape(href)
        if not RE_DOMINIO_PCI.search(href) and href not in links:
            links.append(href)
    datas = sorted({d for d in (data_br(x) for x in re.findall(r"\d{1,2}/\d{1,2}/\d{4}", texto)) if d})
    return {"bancas_citadas": bancas, "links_externos": links[:10], "texto": texto[:6000],
            "datas_citadas": datas}


def coletar(cli: Cliente) -> dict:
    """Devolve {'sp': [...], 'nacional': [...]}"""
    r = cli.get(URL_SUDESTE)
    sp = parse_listagem(r.text, "SÃO PAULO")
    if len(sp) < 20:
        raise ErroFonte(f"PCI: só {len(sp)} itens na seção SP (layout mudou?)")
    nacional = []
    try:
        rn = cli.get(URL_NACIONAL)
        nacional = parse_listagem(rn.text, None)
    except ErroFonte:
        pass
    return {"sp": sp, "nacional": nacional}
