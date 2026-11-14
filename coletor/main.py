"""Coleta todas as fontes, consolida numa base unica e grava os arquivos de dados/.

Uso: python -m coletor.main [--max-detalhes N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

from .base import DADOS, Cliente, ErroFonte, Municipios, agora_iso, hoje, id_de, norm
from .classificar import chave_orgao, esfera_de, mesmo_orgao_por_sigla, municipio_de, tipo_de
from .extrair import datas_da_frase, extrair
from .fontes import bancas, concursosnobrasil, doe_sp, pci, pncp, querido_diario

RE_FORA_DE_ESCOPO = re.compile(r"est[aá]gi|resid[eê]ncia|vestibular|jovem aprendiz|menor aprendiz|bolsista|trainee", re.I)
SITES_BANCAS = {
    "Vunesp": "https://www.vunesp.com.br", "FGV": "https://conhecimento.fgv.br/concursos",
    "Cebraspe": "https://www.cebraspe.org.br/concursos", "FCC": "https://www.concursosfcc.com.br",
    "IBFC": "https://www.ibfc.org.br", "Instituto Mais": "https://www.institutomais.org.br",
    "Avança SP": "https://www.avancasp.org.br", "Nosso Rumo": "https://www.nossorumo.org.br",
    "RBO": "https://www.rboconcursos.com.br", "IBAM": "https://www.ibamsp-concursos.org.br",
    "Consulplan": "https://www.institutoconsulplan.org.br", "SHDias": "https://www.shdias.com.br",
    "Publiconsult": "https://www.publiconsult.com.br", "Indepac": "https://www.indepac.org.br",
    "Zambini": "https://www.zambini.org.br", "AOCP": "https://www.institutoaocp.org.br",
    "Access": "https://www.access.org.br", "Dédalus": "https://www.dedalusconcursos.com.br",
    "Cesgranrio": "https://www.cesgranrio.org.br", "Quadrix": "https://www.quadrix.org.br",
    "Idecan": "https://www.idecan.org.br", "Fundatec": "https://www.fundatec.org.br",
}
DOMINIO_BANCA = {re.sub(r"^https?://(www\.)?", "", u).split("/")[0]: n for n, u in SITES_BANCAS.items()}
MANTER_ENCERRADOS_DIAS = 120
ALERTA_SEM_EDITAL_DIAS = 180
MOSTRAR_FUTURO_DIAS = 365


def ler(nome: str, padrao):
    try:
        with open(os.path.join(DADOS, nome), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return padrao


def gravar(nome: str, obj) -> None:
    with open(os.path.join(DADOS, nome), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")


def dias_entre(a: str | None, b: str | None) -> int | None:
    try:
        return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return None


def nome_bonito(orgao: str, mun: dict | None) -> str:
    """Nome de exibicao para orgaos do PNCP, que vem em maiusculas e sem acento."""
    if re.search(r"[a-z]", orgao):
        return orgao
    if mun and re.search(r"^\s*(MUNICIPIO|PREFEITURA)\b", orgao):
        return f"Prefeitura de {mun['nome']}"
    if mun and re.search(r"\bCAMARA\b", orgao):
        return f"Câmara Municipal de {mun['nome']}"
    peq = {"de", "da", "do", "das", "dos", "e", "em"}
    palavras = []
    for i, w in enumerate(orgao.split()):
        palavras.append(w.lower() if (w.lower() in peq and i) else w.capitalize())
    return " ".join(palavras)


# ============================================================ fontes: abertos
def detalhar_pci(cli: Cliente, itens: list[dict], cache: dict, max_novos: int) -> tuple[int, int]:
    """Busca a pagina de detalhe dos itens que ainda nao estao no cache."""
    novos = falhas = 0
    for it in itens:
        u = it["url_pci"]
        if u in cache or novos >= max_novos:
            continue
        try:
            d = pci.parse_detalhe(cli.get(u, tentativas=2, espera=8, intervalo=1.6).text)
        except ErroFonte:
            falhas += 1
            continue
        fatos = extrair(d["texto"])
        cab = d["texto"][:500]
        dn = datas_da_frase(cab)
        fatos.update(bancas=d["bancas_citadas"], links=d["links_externos"][:5],
                     data_noticia=dn[0] if dn else None, coletado_em=agora_iso())
        cache[u] = fatos
        novos += 1
    return novos, falhas


def registro_pci(it: dict, det: dict | None, M: Municipios, abrangencia: str, agora: str) -> dict | None:
    if RE_FORA_DE_ESCOPO.search(it["titulo"]) or RE_FORA_DE_ESCOPO.search(it.get("cargos") or ""):
        return None
    det = det or {}
    mun = municipio_de(M, it["orgao"], it["titulo"]) if abrangencia == "SP" else None
    esfera = esfera_de(it["orgao"], it["titulo"], mun)
    if esfera != "municipal" and mun and not re.search(re.escape(norm(mun["nome"])), norm(it["orgao"])):
        pass  # orgao estadual/federal com unidade num municipio: mantem o municipio como local
    conferir, notas = [], {}
    # --- inscricoes
    fim, inicio = it["inscricao_fim"], it["inscricao_inicio"]
    d_ini, d_fim = det.get("inscricao_inicio"), det.get("inscricao_fim")
    if not inicio and d_ini and fim and d_ini <= fim:
        inicio = d_ini
    if d_fim and fim and d_fim != fim:
        conferir.append("inscricao_fim")
        notas["inscricao_fim"] = (f"A listagem do agregador indica {fim}; a notícia original cita {d_fim} "
                                  "(pode ter havido prorrogação ou retificação).")
    if not inicio:
        conferir.append("inscricao_inicio")
    # --- banca e link primario
    site = det.get("site_inscricao")
    bancas_cit = det.get("bancas") or []
    banca = None
    if site:
        dom = re.sub(r"^www\.", "", site.split("/")[0])
        banca = DOMINIO_BANCA.get(dom)
    if not banca and len(bancas_cit) == 1:
        banca = bancas_cit[0]
    link_primario = None
    if site:
        link_primario = "https://" + site
    elif banca and banca in SITES_BANCAS:
        link_primario = SITES_BANCAS[banca]
    if not banca and not site:
        conferir.append("banca")
    if not link_primario:
        conferir.append("link_primario")
    # --- demais campos
    cargos_det = det.get("cargos") or []
    cargos = [c["cargo"] for c in cargos_det][:80]
    cargos_resumo = it.get("cargos")
    vagas = it["vagas"]
    if vagas is None and not it["cadastro_reserva"]:
        conferir.append("vagas")
    salario = it["salario_ate"]
    if re.search(r"hora", it.get("vagas_texto") or "", re.I):
        notas["salario_ate"] = "Valor por hora ou hora-aula."
    if salario is None:
        conferir.append("salario_ate")
    if not it["escolaridade"]:
        conferir.append("escolaridade")
    if esfera == "a conferir":
        conferir.append("esfera")
    if abrangencia == "nacional":
        conferir.append("lotacao_sp")
        notas["lotacao_sp"] = "Concurso de abrangência nacional ou de outro estado listado como nacional: confirmar no edital se há vagas em SP."
    tipo = tipo_de(it["titulo"])
    return {
        "id": "a_" + id_de(it["url_pci"]),
        "situacao": "aberto", "tipo": tipo, "orgao": it["orgao"], "esfera": esfera,
        "municipio": mun["nome"] if mun else None, "codigo_ibge": mun["codigo_ibge"] if mun else None,
        "regiao": mun.get("regiao") if mun else None, "abrangencia": abrangencia,
        "cargos": cargos, "cargos_resumo": cargos_resumo, "vagas": vagas,
        "cadastro_reserva": it["cadastro_reserva"], "salario_ate": salario,
        "escolaridade": it["escolaridade"], "banca": banca, "site_inscricao": site,
        "inscricao_inicio": inicio, "inscricao_fim": fim,
        "isencao_inicio": det.get("isencao_inicio"), "isencao_fim": det.get("isencao_fim"),
        "taxa_min": det.get("taxa_min"), "taxa_max": det.get("taxa_max"), "data_prova": det.get("data_prova"),
        "link_primario": link_primario, "publicado_em": det.get("data_noticia"),
        "fontes": [{"nome": "PCI Concursos", "tipo": "agregador", "url": it["url_pci"], "coletado_em": agora}],
        "a_conferir": conferir, "notas": notas,
        "_chave": chave_orgao(it["orgao"], mun), "_titulo": it["titulo"],
    }


def fundir_nosso_rumo(recs: list[dict], itens: list[dict], M: Municipios, agora: str) -> int:
    novos = 0
    for b in itens:
        if b.get("uf") != "SP" or not b.get("inscricao_fim") or b["inscricao_fim"] < hoje().isoformat():
            continue
        if RE_FORA_DE_ESCOPO.search(b["nome"]):
            continue
        partes = [p.strip() for p in b["nome"].split(" - ")]
        orgao_bruto = partes[1] if len(partes) >= 2 else b["nome"]
        orgao_bruto = re.sub(r"/SP\b.*$", "", orgao_bruto).strip()
        mun = municipio_de(M, orgao_bruto)
        chave = chave_orgao(orgao_bruto, mun)
        fonte = {"nome": "Nosso Rumo (banca)", "tipo": "banca", "url": b["url"], "coletado_em": agora}
        cands = [r for r in recs if r["_chave"] == chave and r["situacao"] == "aberto" and
                 (dias_entre(r["inscricao_fim"], b["inscricao_fim"]) or 0) <= 3]
        if cands:
            r = min(cands, key=lambda r: dias_entre(r["inscricao_fim"], b["inscricao_fim"]) or 0)
            r["fontes"].append(fonte)
            r["banca"], r["link_primario"] = "Nosso Rumo", b["url"]
            r["inscricao_inicio"], r["inscricao_fim"] = b["inscricao_inicio"], b["inscricao_fim"]
            r["data_prova"] = b.get("prova") or r.get("data_prova")
            r["data_resultado"] = b.get("resultado")
            r["a_conferir"] = [c for c in r["a_conferir"] if c not in
                               ("banca", "link_primario", "inscricao_inicio", "inscricao_fim")]
            r["notas"].pop("inscricao_fim", None)
            continue
        esfera = esfera_de(orgao_bruto, b["nome"], mun)
        recs.append({
            "id": "a_" + id_de("nossorumo", b["id_banca"]), "situacao": "aberto", "tipo": tipo_de(partes[0]),
            "orgao": nome_bonito(orgao_bruto, mun) if not re.search(r"[a-z]", orgao_bruto) else orgao_bruto,
            "esfera": esfera, "municipio": mun["nome"] if mun else None,
            "codigo_ibge": mun["codigo_ibge"] if mun else None, "regiao": mun.get("regiao") if mun else None,
            "abrangencia": "SP", "cargos": [], "cargos_resumo": None, "vagas": None, "cadastro_reserva": False,
            "salario_ate": None, "escolaridade": [], "banca": "Nosso Rumo", "site_inscricao": "www.nossorumo.org.br",
            "inscricao_inicio": b["inscricao_inicio"], "inscricao_fim": b["inscricao_fim"],
            "isencao_inicio": None, "isencao_fim": None, "taxa_min": None, "taxa_max": None,
            "data_prova": b.get("prova"), "data_resultado": b.get("resultado"),
            "link_primario": b["url"], "publicado_em": None, "fontes": [fonte],
            "a_conferir": ["vagas", "salario_ate", "escolaridade", "cargos"], "notas": {},
            "_chave": chave, "_titulo": b["nome"],
        })
        novos += 1
    return novos


def fundir_agregador2(recs: list[dict], itens: list[dict], M: Municipios, agora: str) -> int:
    """Concursos no Brasil: confirma registros existentes e acrescenta os que faltam."""
    novos = 0
    indice = [(r, norm(r["orgao"] + " " + r.get("_titulo", ""))) for r in recs]
    for c in itens:
        if RE_FORA_DE_ESCOPO.search(c["titulo"]):
            continue
        mun = municipio_de(M, c["orgao"], c["titulo"])
        chave = chave_orgao(c["orgao"], mun)
        n = norm(c["orgao"])
        fonte = {"nome": "Concursos no Brasil", "tipo": "agregador", "url": c["url"], "coletado_em": agora}
        achou = False
        for r, texto in indice:
            if r["_chave"] == chave or (len(n) >= 3 and re.search(r"(^| )" + re.escape(n) + r"( |$)", texto)) \
                    or mesmo_orgao_por_sigla(c["orgao"], r["orgao"]):
                achou = True
                if not any(f["nome"] == fonte["nome"] for f in r["fontes"]):
                    r["fontes"].append(fonte)
                if r["abrangencia"] == "nacional" and "lotacao_sp" in r["a_conferir"]:
                    r["notas"]["lotacao_sp"] = ("Um segundo agregador lista este concurso entre os de SP; "
                                                "confirmar no edital as cidades de lotação.")
        if achou:
            continue
        esfera = esfera_de(c["orgao"], c["titulo"], mun)
        em_sp = "/concursos/sp/" in c["url"]
        rec = {
            "id": "a_" + id_de(c["url"]), "situacao": "aberto", "tipo": tipo_de(c["titulo"]),
            "orgao": c["orgao"], "esfera": esfera, "municipio": mun["nome"] if mun else None,
            "codigo_ibge": mun["codigo_ibge"] if mun else None, "regiao": mun.get("regiao") if mun else None,
            "abrangencia": "SP" if em_sp else "nacional", "cargos": [], "cargos_resumo": None,
            "vagas": c["vagas"], "cadastro_reserva": False, "salario_ate": None, "escolaridade": [],
            "banca": None, "site_inscricao": None, "inscricao_inicio": None, "inscricao_fim": None,
            "isencao_inicio": None, "isencao_fim": None, "taxa_min": None, "taxa_max": None, "data_prova": None,
            "link_primario": None, "publicado_em": None, "fontes": [fonte],
            "a_conferir": ["inscricao_inicio", "inscricao_fim", "salario_ate", "escolaridade", "banca",
                           "link_primario"] + ([] if c["vagas"] else ["vagas"]) +
                          ([] if em_sp else ["lotacao_sp"]) + (["esfera"] if esfera == "a conferir" else []),
            "notas": {"geral": "Registro vindo só do segundo agregador, que não informa datas: abrir a fonte para conferir."},
            "_chave": chave, "_titulo": c["titulo"],
        }
        recs.append(rec)
        indice.append((rec, norm(rec["orgao"] + " " + rec["_titulo"])))
        novos += 1
    return novos


def fundir_instituto_mais(recs: list[dict], itens: list[dict], M: Municipios, agora: str) -> int:
    confirmados = 0
    for b in itens:
        if RE_FORA_DE_ESCOPO.search(b["nome"]):
            continue
        orgao = re.split(r"\s+/\s*SP\b|\s+[-–]\s+", b["nome"])[0].strip()
        mun = municipio_de(M, orgao)
        chave = chave_orgao(orgao, mun)
        for r in recs:
            if r["_chave"] == chave and r["situacao"] == "aberto":
                if not any(f["url"] == b["url"] for f in r["fontes"]):
                    r["fontes"].append({"nome": "Instituto Mais (banca)", "tipo": "banca", "url": b["url"],
                                        "coletado_em": agora})
                if not r.get("banca"):
                    r["banca"] = "Instituto Mais"
                if not r.get("link_primario") or r["link_primario"] == SITES_BANCAS["Instituto Mais"]:
                    r["link_primario"] = b["url"]
                r["a_conferir"] = [c for c in r["a_conferir"] if c not in ("banca", "link_primario")]
                confirmados += 1
    return confirmados


# ============================================================ fontes: futuros
def registros_pncp(itens: list[dict], M: Municipios, agora: str) -> list[dict]:
    recs = []
    for c in itens:
        mun = M.por_codigo.get(c["codigo_ibge"] or "")
        esfera = esfera_de(c["orgao"], c["objeto"], mun, c.get("esfera_pncp"))
        if esfera != "municipal":
            mun_local = None  # orgaos estaduais e federais: o municipio do PNCP e so a sede da unidade
        else:
            mun_local = mun
        nome = nome_bonito(c["orgao"], mun)
        recs.append({
            "id": "p_" + id_de(c["numero_controle"] or c["url"] or c["objeto"]),
            "situacao": c["situacao"], "tipo": c["tipo"], "orgao": nome, "orgao_fonte": c["orgao"],
            "esfera": esfera, "municipio": mun_local["nome"] if mun_local else None,
            "codigo_ibge": mun_local["codigo_ibge"] if mun_local else None,
            "regiao": mun_local.get("regiao") if mun_local else None, "abrangencia": "SP",
            "data_ato": c["data_publicacao"], "evidencia": "Contratação de organizadora publicada no PNCP "
            f"({c['modalidade'] or 'modalidade não informada'}).",
            "trecho": re.sub(r"\s+", " ", c["objeto"])[:420], "link_primario": c["url"],
            "fontes": [{"nome": "PNCP", "tipo": "oficial", "url": c["url"], "coletado_em": agora}],
            "a_conferir": [] if c["url"] else ["link_primario"], "notas": {},
            "_chave": chave_orgao(nome, mun),
        })
    return recs


def registros_doe(itens: list[dict], agora: str) -> list[dict]:
    recs = []
    for d in itens:
        recs.append({
            "id": "d_" + id_de(d["id_doe"] or d["url"]), "situacao": "autorizado",
            "tipo": "concurso público", "orgao": d["orgao"], "esfera": "estadual", "municipio": None,
            "codigo_ibge": None, "regiao": None, "abrangencia": "SP", "data_ato": d["data"],
            "evidencia": f"{d['titulo']} (Diário Oficial do Estado de SP).", "trecho": d["trecho"],
            "academico": d["academico"], "link_primario": d["url"],
            "fontes": [{"nome": "Diário Oficial do Estado de SP", "tipo": "oficial", "url": d["url"],
                        "coletado_em": agora}],
            "a_conferir": [], "notas": {}, "_chave": chave_orgao(d["orgao"], None),
        })
    return recs


def registros_qd(itens: list[dict], M: Municipios, agora: str) -> list[dict]:
    recs = []
    for q in itens:
        mun = M.por_codigo.get(q["codigo_ibge"])
        recs.append({
            "id": "q_" + q["chave"], "situacao": q["situacao"], "tipo": "concurso público",
            "orgao": f"Município de {mun['nome']}" if mun else (q.get("municipio") or "Município"),
            "esfera": "municipal", "municipio": mun["nome"] if mun else q.get("municipio"),
            "codigo_ibge": q["codigo_ibge"], "regiao": mun.get("regiao") if mun else None, "abrangencia": "SP",
            "data_ato": q["data"], "evidencia": q["evidencia"] + " (diário oficial do município).",
            "trecho": q["trecho"], "link_primario": q["url"],
            "fontes": [{"nome": "Querido Diário", "tipo": "oficial", "url": q["url"], "coletado_em": agora}],
            "a_conferir": ["orgao"], "notas": {"orgao": "O diário não distingue aqui prefeitura, câmara ou autarquia."},
            "_chave": f"municipio:{q['codigo_ibge']}",
        })
    return recs


def ligar_futuros(futuros: list[dict], abertos: list[dict]) -> None:
    """Marca o futuro como 'edital publicado' quando ha concurso aberto do mesmo orgao depois do ato."""
    por_chave: dict[str, list[dict]] = {}
    for a in abertos:
        por_chave.setdefault(a["_chave"], []).append(a)
    hj = hoje()
    for f in futuros:
        cands = por_chave.get(f["_chave"], [])
        ato = f.get("data_ato")
        for a in cands:
            ref = a.get("publicado_em") or a.get("primeira_coleta") or a.get("inscricao_inicio")
            if ato and ref and ref >= ato:
                f["situacao_original"], f["situacao"] = f["situacao"], "edital publicado"
                f["edital_id"] = a["id"]
                a["ato_anterior"] = {"data": ato, "descricao": f["evidencia"], "url": f["link_primario"]}
                break
        if f["situacao"] != "edital publicado" and ato:
            idade = (hj - dt.date.fromisoformat(ato)).days
            f["dias_desde_ato"] = idade
            if idade > ALERTA_SEM_EDITAL_DIAS and f["id"].startswith("p_"):
                f["notas"]["alerta"] = (f"Organizadora contratada há {idade} dias e nenhum edital localizado "
                                        "nas fontes: conferir se o concurso já ocorreu ou foi cancelado.")
                if "edital" not in f["a_conferir"]:
                    f["a_conferir"].append("edital")


# ==================================================================== principal
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-detalhes", type=int, default=320)
    args = ap.parse_args(argv)

    agora, hj = agora_iso(), hoje().isoformat()
    cli = Cliente()
    M = Municipios()
    anterior = {r["id"]: r for r in ler("concursos.json", {}).get("concursos", [])}
    cache = ler("cache_detalhes.json", {})
    observado = ler("pncp_observado.json", {})
    manual = ler("manual.json", {"concursos": []}).get("concursos", [])
    status: list[dict] = []

    def rodar(nome, tipo, url, fn, papel):
        linha = {"nome": nome, "tipo": tipo, "url": url, "papel": papel, "quando": agora, "ok": False,
                 "itens": 0, "erro": None, "obs": None}
        try:
            res = fn()
            linha["ok"] = True
            status.append(linha)
            return res, linha
        except ErroFonte as e:
            linha["erro"] = str(e)[:300]
        except Exception as e:  # noqa: BLE001  (uma fonte nunca derruba as outras)
            linha["erro"] = f"{type(e).__name__}: {e}"[:300]
        status.append(linha)
        return None, linha

    # ------------------------------------------------------------- abertos
    abertos: list[dict] = []
    res, ln = rodar("PCI Concursos", "agregador", pci.URL_SUDESTE, lambda: pci.coletar(cli),
                    "Descoberta de concursos abertos (seção SP e nacional)")
    pci_ok = res is not None
    if res:
        todos = res["sp"] + res["nacional"]
        novos, falhas = detalhar_pci(cli, todos, cache, args.max_detalhes)
        for it in res["sp"]:
            r = registro_pci(it, cache.get(it["url_pci"]), M, "SP", agora)
            if r:
                abertos.append(r)
        for it in res["nacional"]:
            r = registro_pci(it, cache.get(it["url_pci"]), M, "nacional", agora)
            if r:
                abertos.append(r)
        ln["itens"] = len(abertos)
        ln["obs"] = (f"{len(res['sp'])} na seção SP, {len(res['nacional'])} na nacional; "
                     f"{novos} páginas de detalhe lidas nesta execução" + (f", {falhas} falharam" if falhas else ""))
        usados = {it["url_pci"] for it in todos}
        for u in [u for u in cache if u not in usados]:
            cache.pop(u)

    res, ln = rodar("Nosso Rumo", "banca", bancas.URL_NOSSO_RUMO, lambda: bancas.coletar_nosso_rumo(cli),
                    "Fonte primária: datas de inscrição, prova e resultado")
    if res:
        ln["itens"] = len(res)
        ln["obs"] = f"{fundir_nosso_rumo(abertos, res, M, agora)} registros que não estavam nos agregadores"

    res, ln = rodar("Instituto Mais", "banca", bancas.URL_IMAIS, lambda: bancas.coletar_instituto_mais(cli),
                    "Fonte primária: confirma concursos com inscrições abertas")
    if res is not None:
        ln["itens"] = len(res)
        ln["obs"] = f"{fundir_instituto_mais(abertos, res, M, agora)} registros confirmados na banca"

    res, ln = rodar("Concursos no Brasil", "agregador", concursosnobrasil.URL,
                    lambda: concursosnobrasil.coletar(cli), "Checagem cruzada do PCI")
    if res:
        ln["itens"] = len(res)
        ln["obs"] = f"{fundir_agregador2(abertos, res, M, agora)} registros que não estavam no PCI"

    # ------------------------------------------------------------- futuros
    futuros: list[dict] = []
    res, ln = rodar("PNCP", "oficial", "https://pncp.gov.br", lambda: pncp.coletar(cli),
                    "Fase anterior ao edital: contratação da banca organizadora")
    if res:
        futuros += registros_pncp(res["itens"], M, agora)
        ln["itens"] = len(res["itens"])
        ln["obs"] = f"{res['lidos']} contratações lidas" + (f"; {len(res['erros'])} consultas falharam" if res["erros"] else "")
        for cod in res["municipios_publicando"]:
            observado[cod] = hj

    res, ln = rodar("Diário Oficial do Estado de SP", "oficial", "https://www.doe.sp.gov.br",
                    lambda: doe_sp.coletar(cli), "Autorizações de concurso na esfera estadual")
    if res:
        futuros += registros_doe(res["itens"], agora)
        ln["itens"] = len(res["itens"])
        ln["obs"] = f"{res['lidos']} publicações lidas" + (f"; {len(res['erros'])} consultas falharam" if res["erros"] else "")

    terrs = [m["codigo_ibge"] for m in M.lista if m.get("querido_diario")]
    res, ln = rodar("Querido Diário", "oficial", "https://queridodiario.ok.org.br",
                    lambda: querido_diario.coletar(cli, terrs),
                    f"Diários oficiais de {len(terrs)} municípios: autorizações, comissões e contratações")
    qd_ok = res is not None
    if res:
        futuros += registros_qd(res["itens"], M, agora)
        ln["itens"] = len(res["itens"])
        ln["obs"] = f"{res['lidos']} diários lidos"

    # registros incluidos a mao pela revisao semanal (ex.: autorizacoes federais do DOU)
    for m in manual:
        m = dict(m)
        m.setdefault("fontes", [])
        m.setdefault("a_conferir", [])
        m.setdefault("notas", {})
        m["_chave"] = chave_orgao(m.get("orgao", ""), None)
        (futuros if m.get("situacao") != "aberto" else abertos).append(m)

    # ------------------------------------------------- historico e situacao
    for r in abertos:
        ant = anterior.get(r["id"])
        r["primeira_coleta"] = ant.get("primeira_coleta", hj) if ant else hj
        r["ultima_coleta"] = hj
        if r.get("inscricao_fim") and r["inscricao_fim"] < hj:
            r["situacao"] = "encerrado"
    ids_agora = {r["id"] for r in abertos}
    limite = (hoje() - dt.timedelta(days=MANTER_ENCERRADOS_DIAS)).isoformat()
    for rid, ant in anterior.items():
        if rid in ids_agora or not rid.startswith("a_"):
            continue
        ant = dict(ant)
        fim = ant.get("inscricao_fim")
        if ant.get("situacao") == "aberto":
            fontes_do_registro = {f.get("nome") for f in ant.get("fontes", [])}
            fonte_respondeu = any(s["ok"] and (s["nome"] in fontes_do_registro or
                                              s["nome"] + " (banca)" in fontes_do_registro) for s in status)
            if fim and fim < hj:
                ant["situacao"] = "encerrado"
            elif fonte_respondeu:
                # sumiu das listagens antes do fim previsto: pode ter sido suspenso ou retirado
                ant["situacao"] = "encerrado"
                ant.setdefault("notas", {})["geral"] = ("Saiu das listagens antes da data de encerramento "
                                                        "registrada: conferir na fonte se foi suspenso.")
                if "situacao" not in ant.get("a_conferir", []):
                    ant.setdefault("a_conferir", []).append("situacao")
            if ant["situacao"] == "encerrado":
                ant["encerrado_em"] = ant.get("encerrado_em") or hj
        if (ant.get("encerrado_em") or ant.get("ultima_coleta") or hj) >= limite:
            ant["_chave"] = ant.get("_chave") or chave_orgao(ant.get("orgao", ""), M.por_codigo.get(ant.get("codigo_ibge") or ""))
            abertos.append(ant)

    for f in futuros:
        ant = anterior.get(f["id"])
        f["primeira_coleta"] = ant.get("primeira_coleta", hj) if ant else hj
        f["ultima_coleta"] = hj
    ligar_futuros(futuros, [a for a in abertos if a["situacao"] == "aberto"])
    # se uma fonte de futuros falhou, mantem os registros dela da execucao anterior
    prefixos_ok = {p for p, nome in (("p_", "PNCP"), ("d_", "Diário Oficial do Estado de SP"), ("q_", "Querido Diário"))
                   if any(s["nome"] == nome and s["ok"] for s in status)}
    ids_fut = {f["id"] for f in futuros}
    for rid, ant in anterior.items():
        if rid[:2] in ("p_", "d_", "q_") and rid[:2] not in prefixos_ok and rid not in ids_fut:
            ant = dict(ant)
            ant.setdefault("notas", {})["geral"] = "A fonte falhou na última execução; registro mantido da coleta anterior."
            futuros.append(ant)
    lim_fut = (hoje() - dt.timedelta(days=MOSTRAR_FUTURO_DIAS)).isoformat()
    futuros = [f for f in futuros if (f.get("data_ato") or hj) >= lim_fut]

    todos = abertos + futuros
    for r in todos:
        for k in [k for k in r if k.startswith("_")]:
            r.pop(k)
        r["a_conferir"] = sorted(set(r.get("a_conferir") or []))
    ordem = {"aberto": 0, "autorizado": 1, "banca em licitação": 2, "banca contratada": 3,
             "edital publicado": 4, "encerrado": 5}
    todos.sort(key=lambda r: (ordem.get(r["situacao"], 9), r.get("inscricao_fim") or r.get("data_ato") or "9",
                              r.get("orgao") or ""))

    # ------------------------------------------------------------ cobertura
    cont = lambda sit: sum(1 for r in todos if r["situacao"] == sit)  # noqa: E731
    por_mun: dict[str, dict] = {}
    for r in todos:
        c = r.get("codigo_ibge")
        if not c:
            continue
        d = por_mun.setdefault(c, {"abertos": 0, "futuros": 0})
        if r["situacao"] == "aberto":
            d["abertos"] += 1
        elif r["situacao"] in ("autorizado", "banca em licitação", "banca contratada"):
            d["futuros"] += 1
    cob = []
    for m in M.lista:
        c = m["codigo_ibge"]
        if m["populacao"] > 20000:
            pre = "PNCP (obrigatório)"
        elif c in observado:
            pre = "PNCP (já publicou)"
        elif m.get("querido_diario") and qd_ok:
            pre = "Querido Diário"
        else:
            pre = "sem cobertura"
        cob.append({"codigo_ibge": c, "nome": m["nome"], "regiao": m.get("regiao"), "populacao": m["populacao"],
                    "pre_edital": pre, "pncp_visto_em": observado.get(c),
                    "querido_diario": bool(m.get("querido_diario")),
                    **por_mun.get(c, {"abertos": 0, "futuros": 0})})
    resumo_cob = {}
    for x in cob:
        resumo_cob[x["pre_edital"]] = resumo_cob.get(x["pre_edital"], 0) + 1
    resumo = {
        "gerado_em": agora, "data": hj,
        "abertos": cont("aberto"), "autorizados": cont("autorizado"),
        "banca_em_licitacao": cont("banca em licitação"), "banca_contratada": cont("banca contratada"),
        "edital_publicado": cont("edital publicado"), "encerrados": cont("encerrado"),
        "municipios_total": len(M.lista),
        "municipios_ate_20mil": sum(1 for m in M.lista if m["populacao"] <= 20000),
        "municipios_com_aberto": sum(1 for v in por_mun.values() if v["abertos"]),
        "cobertura_pre_edital": resumo_cob, "querido_diario_ok": qd_ok,
        "fontes_ok": sum(1 for s in status if s["ok"]), "fontes_total": len(status),
    }

    gravar("concursos.json", {"gerado_em": agora, "resumo": resumo, "concursos": todos})
    gravar("fontes.json", {"gerado_em": agora, "fontes": status,
                           "testadas_sem_uso": ler("fontes_testadas.json", {}).get("fontes", [])})
    gravar("cobertura.json", {"gerado_em": agora, "resumo": resumo_cob, "municipios": cob})
    gravar("cache_detalhes.json", cache)
    gravar("pncp_observado.json", dict(sorted(observado.items())))
    hist = ler("historico.json", {"execucoes": []})
    hist["execucoes"] = (hist["execucoes"] + [{k: resumo[k] for k in (
        "gerado_em", "abertos", "autorizados", "banca_em_licitacao", "banca_contratada", "encerrados",
        "fontes_ok", "fontes_total")}])[-400:]
    gravar("historico.json", hist)

    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    for s in status:
        print(("OK  " if s["ok"] else "FALHA"), s["nome"], "|", s["itens"], "|", s["obs"] or s["erro"])
    # falha total (nenhuma fonte respondeu) e erro de execucao; falha parcial nao e
    return 0 if any(s["ok"] for s in status) else 1


if __name__ == "__main__":
    sys.exit(main())
