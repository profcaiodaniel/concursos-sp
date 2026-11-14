"""PNCP: contratacoes de banca para concurso publico (sinal anterior ao edital).

Antes de abrir um concurso, o orgao contrata a banca organizadora, e essa
contratacao e publicada no Portal Nacional de Contratacoes Publicas.
"""
from __future__ import annotations

import datetime as dt
import re

from ..base import Cliente, ErroFonte, hoje, norm

URL = "https://pncp.gov.br/api/search/"
CONSULTAS = ["concurso público", "organização de concurso público", "processo seletivo público"]
JANELA_DIAS = 400

# o objeto precisa falar de concurso/processo seletivo de pessoal...
RE_TEMA = re.compile(r"\bconcursos? publicos?\b|\bprocessos? seletivos?\b|\bconcurso de provas\b|\bselecao publica\b")
# ...e de contratar quem organiza
RE_BANCA = re.compile(
    r"organiza|realizacao|execucao|planejamento|elaboracao|aplicacao|operacionaliza|banca|"
    r"empresa especializada|instituicao especializada|pessoa juridica|servicos tecnicos|"
    r"servicos especializados|prestacao de servico|"
    r"contratacao d[aeo] (empresa|instituicao|entidade|fundacao|instituto)")
# sinal forte: verbo de organizar perto do tema, ou contratacao de instituicao para o certame
RE_FORTE = re.compile(
    r"(organiza|planeja|realiza|execu|elabora|operacionaliza)\w*.{0,160}(concursos? publicos?|processos? seletivos?|concurso de provas)|"
    r"contratacao d[aeo] (empresa|instituicao|entidade|fundacao|instituto|banca).{0,220}(concursos? publicos?|processos? seletivos?)")
# ruido que sempre descarta: concursos culturais, eventos, cursos e servicos acessorios do certame
RE_RUIDO = re.compile(
    r"artist|music|show\b|banda\b|literari|fotograf|concurso de redacao|desenho|cultur|premia|premio|festival|"
    r"\bmiss\b|rainha|fanfarra|quadrilha|carnaval|gastronom|danca|poesia|cantor|"
    r"curso de capacitacao|capacitacao|treinamento|palestra|seminario|congresso|inscricao de servidor|"
    r"inscricoes para o curso|participacao d[eo]s? servidor|apostila|"
    r"projeto arquitetonico|projeto de arquitetura|estudo preliminar|logomarca|logotipo|"
    r"hino\b|bandeira|brasao|monumento|jurad|comissao julgadora|comissao avaliadora|ornamenta|decoracao natal|"
    r"honorarios|membro (titular|externo|suplente)|passagens|hospedagem|alimentacao|coffee|lanche|refeic|"
    r"avaliac(ao|oes) psicologic|testes? psicologic|exames? medic|aptidao fisica|locacao|"
    r"transporte de candidatos|publicacao de edital|publicidade legal|jornal de grande circulacao|"
    r"vestibular|alunos|discentes|estudantes|cursos de graduacao|residencia medica|"
    r"servicos bancarios|instituicao financeira|agencia bancaria|arrecadacao|cobranca|"
    r"servicos graficos|impressao|\bmodulo\b|credenciamento de profissionais")
# ruido que so descarta quando nao ha sinal forte
RE_RUIDO_FRACO = re.compile(
    r"aquisicao de|fornecimento de|material de|generos|medicament|combustivel|pneus|veiculo|livros?\b|"
    r"licenca de uso|sistema integrado|software")
RE_VUNESP_NOME = re.compile(r"fundacao para o vestibular da universidade estadual paulista( julio de mesquita filho)?")
RE_ESTAGIO = re.compile(r"estagi|agente de integracao|jovem aprendiz|menor aprendiz|residencia medica|bolsista")
RE_PS = re.compile(r"\bprocessos? seletivos?\b|\bselecao publica\b")
RE_CONCURSO = re.compile(r"\bconcursos? publicos?\b|\bconcurso de provas\b")


def classificar(it: dict) -> dict | None:
    """Devolve dados normalizados se o item for contratacao de banca; senao None."""
    desc = RE_VUNESP_NOME.sub("vunesp", norm(it.get("description") or ""))
    if not desc or not RE_TEMA.search(desc):
        return None
    forte = bool(RE_FORTE.search(desc))
    curto = len(desc) <= 60 and bool(RE_CONCURSO.search(desc))  # ex.: objeto "Concurso Publico"
    if not (forte or curto or RE_BANCA.search(desc)):
        return None
    if RE_RUIDO.search(desc) or RE_ESTAGIO.search(desc):
        return None
    if RE_RUIDO_FRACO.search(desc) and not forte:
        return None
    if norm(it.get("modalidade_licitacao_nome") or "") in ("concurso", "credenciamento", "leilao"):
        return None  # modalidade "concurso" da Lei 14.133 escolhe trabalho tecnico ou artistico
    sit = norm(it.get("situacao_nome") or "")
    if it.get("cancelado") or re.search(r"revogad|anulad|suspens|cancelad", sit):
        return None
    modalidade = it.get("modalidade_licitacao_nome") or ""
    direta = bool(re.search(r"dispensa|inexigibilidade", norm(modalidade)))
    situacao = "banca contratada" if (direta or it.get("tem_resultado")) else "banca em licitação"
    tem_c, tem_ps = bool(RE_CONCURSO.search(desc)), bool(RE_PS.search(desc))
    tipo = "concurso público" if tem_c and not tem_ps else ("processo seletivo" if tem_ps and not tem_c
                                                            else "concurso e processo seletivo")
    return {
        "numero_controle": it.get("numero_controle_pncp"),
        "orgao": (it.get("orgao_nome") or "").strip(),
        "unidade": (it.get("unidade_nome") or "").strip(),
        "esfera_pncp": it.get("esfera_nome"),
        "poder": it.get("poder_nome"),
        "municipio": it.get("municipio_nome"),
        "codigo_ibge": str(it.get("codigo_ibge") or "") or None,
        "uf": it.get("uf"),
        "objeto": (it.get("description") or "").strip(),
        "modalidade": modalidade,
        "situacao_pncp": it.get("situacao_nome"),
        "situacao": situacao,
        "tipo": tipo,
        "data_publicacao": (it.get("data_publicacao_pncp") or "")[:10] or None,
        "valor": it.get("valor_global"),
        "url": "https://pncp.gov.br/app/editais/" + (it.get("item_url") or "").replace("/compras/", "").strip("/")
               if it.get("item_url") else None,
    }


def coletar(cli: Cliente, max_paginas: int = 12) -> dict:
    """Le as contratacoes recentes em SP e devolve as que sao de banca de concurso."""
    limite = (hoje() - dt.timedelta(days=JANELA_DIAS)).isoformat()
    vistos, bancas, lidos, erros = set(), [], 0, []
    municipios_publicando = set()
    for q in CONSULTAS:
        for pag in range(1, max_paginas + 1):
            try:
                r = cli.get(URL, params={"q": q, "tipos_documento": "edital", "ordenacao": "-data",
                                         "pagina": pag, "tam_pagina": 100, "status": "todos", "ufs": "SP"},
                            tentativas=5, espera=15, intervalo=4)
                itens = r.json().get("items") or []
            except (ErroFonte, ValueError) as e:
                erros.append(f"{q} p{pag}: {e}")
                break
            antigos = 0
            for it in itens:
                lidos += 1
                if (it.get("data_publicacao_pncp") or "")[:10] < limite:
                    antigos += 1
                    continue
                if it.get("esfera_id") == "M" and str(it.get("codigo_ibge") or "").startswith("35"):
                    municipios_publicando.add(str(it["codigo_ibge"]))
                chave = it.get("numero_controle_pncp") or it.get("id")
                if chave in vistos:
                    continue
                vistos.add(chave)
                c = classificar(it)
                if c:
                    bancas.append(c)
            if len(itens) < 100 or antigos == len(itens):
                break
    # orgaos federais de qualquer estado (sem filtro de UF); a esfera e conferida item a item
    for pag in range(1, 9):
        try:
            r = cli.get(URL, params={"q": "concurso público", "tipos_documento": "edital", "ordenacao": "-data",
                                     "pagina": pag, "tam_pagina": 100, "status": "todos", "esferas": "F"},
                        tentativas=5, espera=15, intervalo=4)
            itens = r.json().get("items") or []
        except (ErroFonte, ValueError) as e:
            erros.append(f"federais p{pag}: {e}")
            break
        antigos = 0
        for it in itens:
            lidos += 1
            if (it.get("data_publicacao_pncp") or "")[:10] < limite:
                antigos += 1
                continue
            if it.get("esfera_id") != "F" or it.get("uf") == "SP":
                continue
            chave = it.get("numero_controle_pncp") or it.get("id")
            if chave in vistos:
                continue
            vistos.add(chave)
            c = classificar(it)
            if c:
                c["federal_outro_estado"] = True
                bancas.append(c)
        if len(itens) < 100 or antigos == len(itens):
            break
    if lidos == 0:
        raise ErroFonte("PNCP: nenhuma página respondeu. " + "; ".join(erros[:2]))
    return {"itens": bancas, "lidos": lidos, "erros": erros,
            "municipios_publicando": sorted(municipios_publicando)}
