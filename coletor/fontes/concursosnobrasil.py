"""Concursos no Brasil: tabela de concursos abertos em SP.

Segundo agregador, usado como checagem cruzada do PCI: o que aparecer aqui
e nao no PCI entra na base com os poucos campos disponiveis e marcado
"a conferir".
"""
from __future__ import annotations

import html
import re

from ..base import Cliente, ErroFonte, limpa_html

URL = "https://concursosnobrasil.com/concursos/sp/"
RE_LINHA = re.compile(
    r'<tr[^>]*>\s*<td>\s*<a href="(?P<url>[^"]+)"[^>]*title="(?P<titulo>[^"]*)"[^>]*>(?P<orgao>.*?)</a>\s*</td>'
    r'\s*<td[^>]*>(?P<vagas>.*?)</td>\s*</tr>', re.S)


def parse(pagina: str) -> list[dict]:
    a = pagina.find("<table")
    b = pagina.find("</table>", a)
    if a < 0 or b < 0:
        raise ErroFonte("Concursos no Brasil: tabela não encontrada (layout mudou?)")
    itens = []
    for m in RE_LINHA.finditer(pagina[a:b]):
        vt = limpa_html(m.group("vagas")).strip()
        vagas = int(vt.replace(".", "")) if re.fullmatch(r"[\d.]+", vt) else None
        itens.append({"url": html.unescape(m.group("url")),
                      "titulo": html.unescape(m.group("titulo")).strip(),
                      "orgao": limpa_html(m.group("orgao")).strip(),
                      "vagas": vagas, "vagas_texto": vt})
    return itens


def coletar(cli: Cliente) -> list[dict]:
    itens = parse(cli.get(URL).text)
    if len(itens) < 10:
        raise ErroFonte(f"Concursos no Brasil: só {len(itens)} linhas (layout mudou?)")
    return itens
