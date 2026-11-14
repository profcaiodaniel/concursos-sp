"""Diario Oficial do Estado de Sao Paulo: atos que autorizam concurso publico.

Usa a busca do proprio portal doe.sp.gov.br por frases exatas e so aceita
o resultado se o trecho devolvido contiver, de fato, um ato de autorizacao.
"""
from __future__ import annotations

import datetime as dt
import re

from ..base import Cliente, ErroFonte, hoje, norm

URL = "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications"
FRASES = [
    "autorizo a abertura de concurso público",
    "autorização para abertura de concurso público",
    "autoriza a abertura de concurso público",
    "autorizada a abertura de concurso público",
    "autorizo a realização de concurso público",
    "autorização para realização de concurso público",
    "autoriza a realização de concurso público",
    "autorizada a realização de concurso público",
]
JANELA_DIAS = 240
RE_ATO = re.compile(
    r"autoriz\w+.{0,90}(abertura|realizacao|realizar|abrir).{0,40}concursos? publicos?|"
    r"autoriz\w+.{0,60}concursos? publicos? para (o )?provimento")
# universidades autorizam, uma a uma, contratacoes de docentes e substitutos: ruido para o mapa
RE_ACADEMICO = re.compile(r"professor (doutor|titular|assistente|substituto|associado)|docente|substitut|livre docencia")


def _orgao(hierarquia: str) -> str:
    partes = [p.strip() for p in (hierarquia or "").split(">")]
    partes = [p for p in partes if p and p not in ("Executivo", "Atos Normativos", "Atos de Gestão e Despesas",
                                                   "Atos de Pessoal", "Legislativo", "Judiciário")]
    if not partes:
        return "Governo do Estado de São Paulo"
    if partes[0] == "Atos do Governador":
        return "Governo do Estado de São Paulo"
    return partes[0]


def coletar(cli: Cliente) -> dict:
    de = (hoje() - dt.timedelta(days=JANELA_DIAS)).isoformat()
    vistos, itens, erros, lidos = set(), [], [], 0
    for frase in FRASES:
        for pag in range(1, 5):
            try:
                r = cli.get(URL, params={"periodStartingDate": "personalized", "PageNumber": pag,
                                         "Terms[0]": frase, "FromDate": de, "ToDate": hoje().isoformat(),
                                         "PageSize": 50, "SortField": "Date"}, intervalo=2)
                j = r.json()
            except (ErroFonte, ValueError) as e:
                erros.append(f"{frase} p{pag}: {e}")
                break
            for it in j.get("items") or []:
                lidos += 1
                if it.get("id") in vistos:
                    continue
                vistos.add(it.get("id"))
                trecho = (it.get("excerpt") or "").strip()
                n = norm(trecho + " " + (it.get("title") or ""))
                if not RE_ATO.search(n):
                    continue
                itens.append({
                    "id_doe": it.get("id"),
                    "data": (it.get("date") or "")[:10],
                    "titulo": (it.get("title") or "").strip(),
                    "orgao": _orgao(it.get("hierarchy") or ""),
                    "hierarquia": it.get("hierarchy"),
                    "trecho": re.sub(r"\s+", " ", trecho)[:420],
                    "academico": bool(RE_ACADEMICO.search(n)),
                    "url": "https://www.doe.sp.gov.br/" + (it.get("slug") or "").lstrip("/"),
                })
            if not j.get("hasNextPage"):
                break
    if erros and len(erros) == len(FRASES):
        raise ErroFonte("DOE-SP: nenhuma consulta respondeu. " + erros[0])
    return {"itens": itens, "lidos": lidos, "erros": erros}
