"""Querido Diario (Open Knowledge Brasil): busca nos diarios oficiais municipais.

A API e publica e documentada para uso por scripts (referencia de ate 60
requisicoes por minuto); por isso o robots.txt do host da API, que so afasta
indexadores de busca, nao e aplicado aqui. Usamos bem menos que o limite.

Na sondagem de 14/11/2026 a API nao respondeu a partir do GitHub (falha de
TLS em um host e tempo esgotado no outro). O coletor tenta a cada execucao e
registra o resultado; enquanto falhar, a fonte aparece como indisponivel.
"""
from __future__ import annotations

import datetime as dt
import re

from ..base import Cliente, ErroFonte, hoje, id_de, norm

BASES = ["https://api.queridodiario.org.br", "https://api.queridodiario.ok.org.br"]
JANELA_DIAS = 60
CONSULTAS = ['"concurso público" + autoriza', '"concurso público" + comissão', '"concurso público" + contratação']
RE_AUTORIZA = re.compile(r"autoriz\w+.{0,90}(abertura|realizacao|realizar|abrir).{0,40}concursos? publicos?")
RE_COMISSAO = re.compile(r"(nomeia|designa|constitui|institui|cria)\w*.{0,80}comissao.{0,80}concursos? publicos?")
RE_BANCA = re.compile(r"contrat\w+.{0,120}(empresa|instituicao|instituto|fundacao|banca).{0,160}concursos? publicos?")
RE_RUIDO = re.compile(r"homologa|convoca|nomeacao d|posse|classificad|gabarito|resultado final|prorroga a validade")


def _classificar(trecho: str) -> tuple[str, str] | None:
    n = norm(trecho)
    if RE_AUTORIZA.search(n):
        return "autorizado", "Ato autoriza a abertura de concurso público"
    if RE_BANCA.search(n) and not RE_RUIDO.search(n):
        return "banca em licitação", "Diário oficial registra contratação de organizadora para concurso"
    if RE_COMISSAO.search(n) and not RE_RUIDO.search(n):
        return "autorizado", "Ato nomeia comissão de concurso público"
    return None


def coletar(cli: Cliente, territorios: list[str]) -> dict:
    desde = (hoje() - dt.timedelta(days=JANELA_DIAS)).isoformat()
    base_ok, erro = None, "?"
    for base in BASES:
        try:
            r = cli.get(base + "/gazettes", params={"territory_ids": territorios[0], "size": 1},
                        robots=False, tentativas=2, espera=5, timeout=40)
            r.json()
            base_ok = base
            break
        except (ErroFonte, ValueError) as e:
            erro = str(e)
    if not base_ok:
        raise ErroFonte("Querido Diário: API não respondeu. " + erro)
    itens, vistos, lidos = [], set(), 0
    for q in CONSULTAS:
        for off in range(0, 300, 100):
            r = cli.get(base_ok + "/gazettes",
                        params={"querystring": q, "published_since": desde, "size": 100, "offset": off,
                                "sort_by": "descending_date", "territory_ids": territorios,
                                "excerpt_size": 600, "number_of_excerpts": 3},
                        robots=False, tentativas=2, espera=10, intervalo=2)
            gz = r.json().get("gazettes") or []
            for g in gz:
                lidos += 1
                for tr in g.get("excerpts") or []:
                    c = _classificar(tr)
                    if not c:
                        continue
                    chave = id_de(str(g.get("territory_id")), str(g.get("date")), norm(tr)[:80])
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    itens.append({"chave": chave, "codigo_ibge": str(g.get("territory_id")),
                                  "municipio": g.get("territory_name"), "data": g.get("date"),
                                  "situacao": c[0], "evidencia": c[1],
                                  "trecho": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", tr))[:420],
                                  "url": g.get("url") or g.get("txt_url")})
            if len(gz) < 100:
                break
    return {"itens": itens, "lidos": lidos, "base": base_ok}
