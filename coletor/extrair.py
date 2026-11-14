"""Extracao de fatos (datas, taxa, site, cargos) do texto de uma noticia de concurso.

Regra geral: so devolve o que casar com um padrao claro. Na duvida, None.
O texto da noticia nao e republicado; so os fatos extraidos entram na base.
"""
from __future__ import annotations

import datetime as dt
import re

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_MES = "(" + "|".join(MESES) + ")"
RE_DATA_EXT = re.compile(r"(?<![\d/])(\d{1,2})[ºo°]?\s+de\s+" + _MES + r"(?:\s+de\s+(\d{4}))?", re.I)
RE_FAIXA_MESMO_MES = re.compile(r"(?<![\d/])(\d{1,2})[ºo°]?\s+(?:a|e|até)\s+(\d{1,2})[ºo°]?\s+de\s+" + _MES + r"\s+de\s+(\d{4})", re.I)
RE_DATA_NUM = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})")
RE_DOMINIO = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|org|net|gov|edu|sp|art|inf|srv|leg|jus|mp|def)(?:\.br)?|(?:[a-z0-9-]+\.)+br)\b(/[^\s,;)]*)?", re.I)


def _d(dia, mes, ano):
    try:
        return dt.date(int(ano), MESES[mes.lower()] if not str(mes).isdigit() else int(mes), int(dia)).isoformat()
    except (ValueError, KeyError):
        return None


def datas_da_frase(frase: str) -> list[str]:
    """Datas por extenso ou numericas de uma frase, na ordem. O ano que faltar e herdado da data seguinte."""
    achados = []
    for m in RE_FAIXA_MESMO_MES.finditer(frase):
        achados.append((m.start(), [_d(m.group(1), m.group(3), m.group(4)), _d(m.group(2), m.group(3), m.group(4))]))
    ocupado = [(m.start(), m.end()) for m in RE_FAIXA_MESMO_MES.finditer(frase)]
    brutos = []
    for m in RE_DATA_EXT.finditer(frase):
        if any(a <= m.start() < b for a, b in ocupado):
            continue
        brutos.append((m.start(), m.group(1), m.group(2), m.group(3)))
    # herda o ano da proxima data que tiver ano
    for i, (pos, dia, mes, ano) in enumerate(brutos):
        if not ano:
            for _, _, mes2, ano2 in brutos[i + 1:]:
                if ano2:
                    ano = str(int(ano2) - 1) if MESES[mes.lower()] > MESES[mes2.lower()] else ano2
                    break
        if ano:
            achados.append((pos, [_d(dia, mes, ano)]))
    for m in RE_DATA_NUM.finditer(frase):
        achados.append((m.start(), [_d(m.group(1), m.group(2), m.group(3))]))
    out = []
    for _, ds in sorted(achados, key=lambda x: x[0]):
        out += [d for d in ds if d]
    return out


def frases(texto: str) -> list[str]:
    partes = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ú])|\n+", texto)
    return [p.strip() for p in partes if p.strip()]


def extrair(texto: str) -> dict:
    """Devolve dict com: inscricao_inicio, inscricao_fim, site_inscricao, taxa_min, taxa_max,
    data_prova, isencao_inicio, isencao_fim, cargos (lista de {cargo, vagas})."""
    out = {"inscricao_inicio": None, "inscricao_fim": None, "site_inscricao": None,
           "taxa_min": None, "taxa_max": None, "data_prova": None, "isencao_inicio": None,
           "isencao_fim": None, "cargos": []}
    fs = frases(texto)
    for f in fs:
        fl = f.lower()
        if out["inscricao_fim"] is None and re.search(r"inscri[cç][aãõo]", fl) and \
                not re.search(r"isen[cç]|homologa|deferi|recurso", fl):
            ds = datas_da_frase(f)
            if len(ds) >= 2 and ds[0] <= ds[1]:
                out["inscricao_inicio"], out["inscricao_fim"] = ds[0], ds[1]
            elif len(ds) == 1 and re.search(r"\baté\b|encerra|termina", fl):
                out["inscricao_fim"] = ds[0]
            if ds and out["site_inscricao"] is None:
                m = RE_DOMINIO.search(f)
                if m and not re.search(r"pciconcursos|pci\.app", m.group(0), re.I):
                    out["site_inscricao"] = m.group(0).rstrip(".").lower()
        if out["site_inscricao"] is None and re.search(r"\b(site|endere[cç]o eletr[oô]nico|portal)\b", fl) and \
                re.search(r"inscri", fl):
            m = RE_DOMINIO.search(f)
            if m and not re.search(r"pciconcursos|pci\.app", m.group(0), re.I):
                out["site_inscricao"] = m.group(0).rstrip(".").lower()
        if out["isencao_fim"] is None and re.search(r"isen[cç]", fl):
            ds = datas_da_frase(f)
            if len(ds) >= 2 and ds[0] <= ds[1]:
                out["isencao_inicio"], out["isencao_fim"] = ds[0], ds[1]
            elif len(ds) == 1 and re.search(r"\baté\b", fl):
                out["isencao_fim"] = ds[0]
        if out["taxa_min"] is None and "taxa" in fl:
            vals = []
            for v in re.findall(r"R\$\s*([\d.]+,\d{2})", f):
                try:
                    vals.append(float(v.replace(".", "").replace(",", ".")))
                except ValueError:
                    pass
            vals = [v for v in vals if 0 < v < 1000]
            if vals:
                out["taxa_min"], out["taxa_max"] = min(vals), max(vals)
        if out["data_prova"] is None and re.search(r"\bprovas?\b", fl) and \
                re.search(r"previst|aplicad|realizad|ocorrer|acontecer|marcad|agendad|ser[aã]o? no dia|ser[aá] em", fl) and \
                not re.search(r"inscri[cç]", fl):
            ds = datas_da_frase(f)
            if ds:
                out["data_prova"] = ds[0]
    # cargos: linhas no formato "Nome do cargo (N vagas ...)" ou "(cadastro de reserva)"
    vistos = set()
    for linha in texto.split("\n"):
        m = re.match(r"^\s*(?P<cargo>[A-ZÀ-Ú][^()\n]{2,110}?)\s*\((?P<q>[^()]{1,80})\)[.;]?\s*$", linha)
        if not m:
            continue
        q = m.group("q").lower()
        if not re.search(r"vagas?|cadastro|reserva|\bcr\b", q):
            continue
        cargo = m.group("cargo").strip(" -–:;")
        if cargo.lower() in vistos:
            continue
        vistos.add(cargo.lower())
        n = re.search(r"(\d+)\s+vagas?", q)
        out["cargos"].append({"cargo": cargo, "vagas": int(n.group(1)) if n else None})
    return out
