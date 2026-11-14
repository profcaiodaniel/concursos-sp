"""Bancas com listagem publica acessivel a partir do GitHub.

Fonte primaria: confirma datas e acha concursos que os agregadores perderam.
A maioria das bancas bloqueia acesso automatizado (ver dados/fontes.json);
aqui ficam so as que respondem e tem listagem estruturada.
"""
from __future__ import annotations

import html
import re

from ..base import Cliente, ErroFonte, data_br, limpa_html

# ------------------------------------------------------------- Nosso Rumo
URL_NOSSO_RUMO = "https://www.nossorumo.org.br/"
RE_NR_CARD = re.compile(
    r'data-sobre-certame=(?P<id>\d+)>(?P<miolo>.*?)data-cronograma=(?P=id)', re.S)


def parse_nosso_rumo(pagina: str) -> list[dict]:
    itens, vistos = [], set()
    for m in RE_NR_CARD.finditer(pagina):
        if m.group("id") in vistos:
            continue
        vistos.add(m.group("id"))
        miolo = m.group("miolo")
        nome = re.search(r'data-nome-certame="([^"]+)"', miolo)
        per = re.search(r'data-periodo-inscricao="([^"]*)"', miolo)
        if not nome:
            continue
        nome_t = html.unescape(nome.group(1)).strip()
        selo = limpa_html(re.search(r'class=corner-text>(.*?)</div>', miolo, re.S).group(1)).replace("\n", " ") \
            if re.search(r'class=corner-text>', miolo) else ""
        datas = re.findall(r"\d{2}/\d{2}/\d{4}", html.unescape(per.group(1)) if per else "")
        crono = {}
        for rot, val in re.findall(r'<p[^>]*class="text-muted f-14 mb-1">\s*([^<]+?)\s*<br[^>]*>\s*([^<]+?)\s*</p>', miolo):
            crono[html.unescape(rot).strip()] = html.unescape(val).strip()
        itens.append({
            "id_banca": m.group("id"), "nome": nome_t, "selo": selo.strip(),
            "inscricao_inicio": data_br(datas[0]) if len(datas) >= 1 else None,
            "inscricao_fim": data_br(datas[1]) if len(datas) >= 2 else None,
            "prova": data_br(crono.get("Prova Objetiva")),
            "resultado": data_br(crono.get("Resultado Final")),
            "uf": (re.search(r"/([A-Z]{2})\b", nome_t) or [None, None])[1],
            "url": URL_NOSSO_RUMO,
        })
    return itens


def coletar_nosso_rumo(cli: Cliente) -> list[dict]:
    itens = parse_nosso_rumo(cli.get(URL_NOSSO_RUMO).text)
    if not itens:
        raise ErroFonte("Nosso Rumo: nenhum certame encontrado (layout mudou?)")
    return itens


# ---------------------------------------------------------- Instituto Mais
URL_IMAIS = "https://www.institutomais.org.br/Concursos/ConcursosAbertos"


def parse_instituto_mais(pagina: str) -> list[dict]:
    """Devolve os certames da secao 'Inscricoes Abertas' (so nomes e links)."""
    a = pagina.find("Inscrições Abertas")
    if a < 0:
        a = pagina.find("Inscri&#231;&#245;es Abertas")
    b = pagina.find("Concursos em andamento", a)
    if a < 0:
        raise ErroFonte("Instituto Mais: seção 'Inscrições Abertas' não encontrada (layout mudou?)")
    bloco = pagina[a: b if b > 0 else len(pagina)]
    itens = []
    for href, miolo in re.findall(r'<a[^>]+href="([^"]*Concursos?/[^"]*)"[^>]*>(.*?)</a>', bloco, re.S | re.I):
        nome = limpa_html(miolo).replace("\n", " ").strip()
        if len(nome) < 12 or any(nome == x["nome"] for x in itens):
            continue
        url = href if href.startswith("http") else "https://www.institutomais.org.br" + href
        itens.append({"nome": nome, "url": html.unescape(url),
                      "uf": (re.search(r"/\s*([A-Z]{2})\b", nome) or [None, None])[1]})
    return itens


def coletar_instituto_mais(cli: Cliente) -> list[dict]:
    return parse_instituto_mais(cli.get(URL_IMAIS).text)
