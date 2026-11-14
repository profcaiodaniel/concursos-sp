#!/usr/bin/env python3
"""Sondagem das fontes do concursos-sp.

Roda no GitHub Actions. Para cada fonte candidata registra: robots.txt,
status HTTP, tamanho e o corpo bruto (para desenhar os coletores depois).
Faz tambem tres medicoes de cobertura: municipios de SP e populacao (IBGE),
municipios cobertos e atualizados no Querido Diario, e municipios que
aparecem no PNCP em contratacoes ligadas a concurso.

Saida: probe_out/summary.json, probe_out/summary.md e probe_out/raw/*.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.robotparser
from urllib.parse import urlsplit

import requests

UA = ("Mozilla/5.0 (compatible; concursos-sp-bot/0.1; "
      "+https://github.com/profcaiodaniel/concursos-sp)")
OUT = "probe_out"
RAW = os.path.join(OUT, "raw")
os.makedirs(RAW, exist_ok=True)

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})

TODAY = dt.date.today()
D30 = TODAY - dt.timedelta(days=30)
D90 = TODAY - dt.timedelta(days=90)
D180 = TODAY - dt.timedelta(days=180)

results = []      # uma linha por requisicao
robots_cache = {}  # host -> dict


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:80]


def robots_for(url):
    """Baixa e interpreta o robots.txt do host (uma vez por host)."""
    p = urlsplit(url)
    host = f"{p.scheme}://{p.netloc}"
    if host in robots_cache:
        return robots_cache[host]
    info = {"host": host, "status": None, "error": None}
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = S.get(host + "/robots.txt", timeout=25)
        info["status"] = r.status_code
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and "html" not in ctype.lower():
            rp.parse(r.text.splitlines())
            info["parsed"] = True
            with open(os.path.join(RAW, "robots_" + slug(p.netloc) + ".txt"), "w") as f:
                f.write(r.text[:200000])
        else:
            # sem robots.txt valido: nada e proibido
            rp.parse([])
            info["parsed"] = False
    except Exception as e:  # noqa: BLE001
        info["error"] = repr(e)[:300]
        rp.parse([])
        info["parsed"] = False
    info["rp"] = rp
    robots_cache[host] = info
    return info


def fetch(name, url, params=None, group="", save=True, timeout=45, check_robots=True,
          accept=None):
    """GET com registro. Devolve (response|None, linha_de_resultado)."""
    row = {"name": name, "group": group, "url": url, "params": params}
    rb = robots_for(url)
    row["robots_status"] = rb["status"]
    full = requests.Request("GET", url, params=params).prepare().url
    row["robots_allowed"] = rb["rp"].can_fetch(UA, full) if rb.get("parsed") else True
    row["robots_allowed_generic"] = rb["rp"].can_fetch("*", full) if rb.get("parsed") else True
    if check_robots and not (row["robots_allowed"] and row["robots_allowed_generic"]):
        row["skipped"] = "robots.txt proibe"
        results.append(row)
        return None, row
    t0 = time.time()
    try:
        h = {"Accept": accept} if accept else {}
        r = S.get(url, params=params, timeout=timeout, headers=h)
        row.update(status=r.status_code, bytes=len(r.content),
                   content_type=r.headers.get("content-type", ""),
                   final_url=r.url, elapsed=round(time.time() - t0, 2))
        if save:
            ext = "json" if "json" in row["content_type"] else "html"
            fn = os.path.join(RAW, f"{slug(group)}__{slug(name)}.{ext}")
            with open(fn, "wb") as f:
                f.write(r.content[:4_000_000])
            row["file"] = fn
        results.append(row)
        return r, row
    except Exception as e:  # noqa: BLE001
        row.update(error=repr(e)[:400], elapsed=round(time.time() - t0, 2))
        results.append(row)
        return None, row


def jget(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return None


summary = {"gerado_em_utc": dt.datetime.utcnow().isoformat() + "Z", "ua": UA}

# IP de saida (para diagnosticar bloqueio geografico)
try:
    summary["ip_info"] = S.get("https://ipinfo.io/json", timeout=15).json()
except Exception as e:  # noqa: BLE001
    summary["ip_info"] = repr(e)[:200]

# ---------------------------------------------------------------- 1. IBGE
ibge = {}
r, _ = fetch("municipios_sp", "https://servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios",
             group="ibge")
munis = jget(r) if r is not None else None
if munis:
    ibge["n_municipios"] = len(munis)
# populacao: Censo 2022 (tabela 4714, var 93) e estimativa mais recente (tabela 6579, var 9324)
for nome, path in [
    ("pop_censo2022", "https://apisidra.ibge.gov.br/values/t/4714/n6/in%20n3%2035/v/93/p/2022"),
    ("pop_estimativa_ultima", "https://apisidra.ibge.gov.br/values/t/6579/n6/in%20n3%2035/v/9324/p/last%201"),
]:
    r, _ = fetch(nome, path, group="ibge")
    data = jget(r) if r is not None else None
    if data and len(data) > 1:
        rows = data[1:]
        pops = {}
        for x in rows:
            try:
                pops[x["D1C"]] = int(x["V"])
            except Exception:  # noqa: BLE001
                pass
        ibge[nome] = {
            "n": len(pops),
            "periodo": rows[0].get("D3N") or rows[0].get("D2N"),
            "ate_20mil": sum(1 for v in pops.values() if v <= 20000),
            "acima_20mil": sum(1 for v in pops.values() if v > 20000),
        }
        with open(os.path.join(OUT, f"{nome}.json"), "w") as f:
            json.dump(pops, f)
summary["ibge"] = ibge

# ------------------------------------------------------- 2. Querido Diario
qd = {"bases_testadas": []}
qd_base = None
for base in ["https://api.queridodiario.ok.org.br", "https://queridodiario.ok.org.br/api",
             "https://api.queridodiario.org.br", "https://queridodiario.org.br/api"]:
    # A API e publica e documentada para uso por scripts (referencia: 60 req/min),
    # por isso nao aplicamos o robots.txt do host aqui; apenas o registramos.
    r, row = fetch("cities_" + slug(base), base + "/cities", params={"city_name": ""},
                   group="querido_diario", check_robots=False)
    ok = r is not None and r.status_code == 200 and jget(r) is not None
    qd["bases_testadas"].append({"base": base, "status": row.get("status"),
                                 "erro": row.get("error"), "json": ok,
                                 "robots_allowed": row.get("robots_allowed_generic")})
    if ok and qd_base is None:
        qd_base = base
        cities = jget(r).get("cities", [])
        sp = [c for c in cities if c.get("state_code") == "SP"]
        qd["total_cidades_brasil"] = len(cities)
        qd["cidades_sp"] = len(sp)
        qd["niveis_sp"] = {}
        for c in sp:
            qd["niveis_sp"][str(c.get("level"))] = qd["niveis_sp"].get(str(c.get("level")), 0) + 1
        qd["exemplo_cidade"] = sp[0] if sp else None
        with open(os.path.join(OUT, "qd_cidades_sp.json"), "w") as f:
            json.dump(sp, f, ensure_ascii=False)
qd["base_escolhida"] = qd_base

if qd_base:
    # Frescor: data do diario mais recente de cada municipio de SP
    fresh = {}
    with open(os.path.join(OUT, "qd_cidades_sp.json")) as f:
        sp = json.load(f)
    for i, c in enumerate(sp):
        tid = c["territory_id"]
        try:
            r = S.get(qd_base + "/gazettes", params={"territory_ids": tid, "size": 1,
                                                     "sort_by": "descending_date"}, timeout=40)
            j = r.json()
            g = (j.get("gazettes") or [{}])[0]
            fresh[tid] = {"nome": c.get("territory_name"), "total": j.get("total_gazettes"),
                          "ultima_data": g.get("date"), "status": r.status_code}
        except Exception as e:  # noqa: BLE001
            fresh[tid] = {"nome": c.get("territory_name"), "erro": repr(e)[:200]}
        time.sleep(1.1)  # bem abaixo de 60 req/min
    with open(os.path.join(OUT, "qd_frescor_sp.json"), "w") as f:
        json.dump(fresh, f, ensure_ascii=False, indent=0)

    def n_since(d):
        return sum(1 for v in fresh.values() if (v.get("ultima_data") or "") >= d.isoformat())
    qd["sp_com_algum_diario"] = sum(1 for v in fresh.values() if v.get("ultima_data"))
    qd["sp_atualizado_30d"] = n_since(D30)
    qd["sp_atualizado_90d"] = n_since(D90)
    qd["sp_atualizado_180d"] = n_since(D180)

    # Busca de teste: atos sobre concurso nos ultimos 90 dias, so SP
    for nome, q in [("busca_concurso_publico", '"concurso público"'),
                    ("busca_autoriza_concurso", '"autoriza" "concurso público"'),
                    ("busca_banca", '"concurso público" "contratação" (empresa | instituição | banca)')]:
        r, row = fetch(nome, qd_base + "/gazettes",
                       params={"querystring": q, "published_since": D90.isoformat(),
                               "size": 50, "sort_by": "descending_date", "state_code": "SP",
                               "excerpt_size": 400, "number_of_excerpts": 2},
                       group="querido_diario", check_robots=False)
        j = jget(r) if r is not None else None
        if j:
            gz = j.get("gazettes", [])
            qd[nome] = {"total": j.get("total_gazettes"),
                        "ufs_na_pagina": sorted({g.get("state_code") for g in gz if g.get("state_code")}),
                        "campos": sorted(gz[0].keys()) if gz else []}
        time.sleep(1.1)
summary["querido_diario"] = qd

# ----------------------------------------------------------------- 3. PNCP
pncp = {}
PNCP_SEARCH = "https://pncp.gov.br/api/search/"
for nome, q, tipo in [
    ("edital_concurso_publico", "concurso público", "edital"),
    ("edital_organizacao_concurso", "organização concurso público provas", "edital"),
    ("contrato_concurso_publico", "concurso público", "contrato"),
    ("edital_processo_seletivo", "processo seletivo", "edital"),
]:
    munis_seen, itens, total, campos, exemplo = set(), 0, None, [], None
    for pag in range(1, 11):  # ate 1000 itens por consulta
        r, row = fetch(f"{nome}_p{pag}", PNCP_SEARCH,
                       params={"q": q, "tipos_documento": tipo, "ordenacao": "-data",
                               "pagina": pag, "tam_pagina": 100, "status": "todos", "ufs": "SP"},
                       group="pncp", save=(pag <= 2))
        j = jget(r) if r is not None else None
        if not j:
            break
        its = j.get("items") or []
        total = j.get("total", total)
        if its and not campos:
            campos, exemplo = sorted(its[0].keys()), its[0]
        for it in its:
            itens += 1
            if it.get("municipio_nome"):
                munis_seen.add(it["municipio_nome"])
        if len(its) < 100:
            break
        time.sleep(1.0)
    pncp[nome] = {"total": total, "itens_lidos": itens, "municipios_distintos": len(munis_seen),
                  "campos": campos, "exemplo": exemplo, "municipios": sorted(munis_seen)}
# API oficial de consulta (dados abertos)
r, row = fetch("consulta_v1_dispensa", "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao",
               params={"dataInicial": D30.strftime("%Y%m%d"), "dataFinal": TODAY.strftime("%Y%m%d"),
                       "codigoModalidadeContratacao": 8, "uf": "SP", "pagina": 1, "tamanhoPagina": 50},
               group="pncp")
j = jget(r) if r is not None else None
if j:
    d = j.get("data") or []
    pncp["consulta_v1"] = {"status": row.get("status"), "totalRegistros": j.get("totalRegistros"),
                           "totalPaginas": j.get("totalPaginas"),
                           "campos": sorted(d[0].keys()) if d else []}
summary["pncp"] = pncp

# ------------------------------------------- 4. Agregadores, bancas, diarios
ymd = TODAY.strftime("%Y-%m-%d")
dmy_prev = (TODAY - dt.timedelta(days=1)).strftime("%d-%m-%Y")
PAGES = [
    # agregadores
    ("agregador", "pci_sudeste", "https://www.pciconcursos.com.br/concursos/sudeste/"),
    ("agregador", "pci_sp", "https://www.pciconcursos.com.br/concursos/sp/"),
    ("agregador", "pci_home", "https://www.pciconcursos.com.br/"),
    ("agregador", "concursosnobrasil_sp", "https://concursosnobrasil.com/concursos/sp/"),
    ("agregador", "jcconcursos_sp", "https://jcconcursos.com.br/concursos/sp"),
    # bancas
    ("banca", "vunesp", "https://www.vunesp.com.br/"),
    ("banca", "fgv", "https://conhecimento.fgv.br/concursos"),
    ("banca", "cebraspe", "https://www.cebraspe.org.br/concursos/"),
    ("banca", "fcc", "https://www.concursosfcc.com.br/"),
    ("banca", "ibfc", "https://www.ibfc.org.br/"),
    ("banca", "instituto_mais", "https://www.institutomais.org.br/"),
    ("banca", "avanca_sp", "https://www.avancasp.org.br/"),
    ("banca", "nosso_rumo", "https://www.nossorumo.org.br/"),
    ("banca", "rbo", "https://www.rboconcursos.com.br/"),
    ("banca", "ibam_sp", "https://www.ibamsp-concursos.org.br/"),
    ("banca", "consulplan", "https://www.institutoconsulplan.org.br/"),
    ("banca", "shdias", "https://www.shdias.com.br/"),
    ("banca", "publiconsult", "https://www.publiconsult.com.br/"),
    ("banca", "indepac", "https://www.indepac.org.br/"),
    ("banca", "zambini", "https://www.zambini.org.br/"),
    ("banca", "aocp", "https://www.institutoaocp.org.br/"),
    ("banca", "access", "https://www.access.org.br/"),
    ("banca", "dedalus", "https://www.dedalusconcursos.com.br/"),
    ("banca", "aplicativa", "https://www.aplicativa.com.br/"),
    # diarios e portais oficiais
    ("dou", "busca_concurso", "https://www.in.gov.br/consulta/-/buscar/dou?q=%22concurso+p%C3%BAblico%22+autoriza&s=todos&exactDate=mes&sortType=0"),
    ("dou", "leitura_secao1", f"https://www.in.gov.br/leiturajornal?data={dmy_prev}&secao=do1"),
    ("dou", "home", "https://www.in.gov.br/"),
    ("federal", "mgi_concursos", "https://www.gov.br/gestao/pt-br/assuntos/concursos"),
    ("federal", "servidor_concursos", "https://www.gov.br/servidor/pt-br/assuntos/concursos"),
    ("doe_sp", "home", "https://www.doe.sp.gov.br/"),
    ("doe_sp", "api_busca", "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications"
     f"?periodStartingDate=personalized&PageNumber=1&Terms%5B0%5D=concurso%20p%C3%BAblico&FromDate={D30.isoformat()}&ToDate={ymd}&PageSize=20&SortField=Date"),
    ("doe_sp", "api_sumario", f"https://do-api-web-search.doe.sp.gov.br/v2/summary/structured?Date={(TODAY - dt.timedelta(days=1)).isoformat()}"),
    ("doe_sp", "imprensa_oficial", "https://www.imprensaoficial.com.br/"),
    ("estado_sp", "portal_concursos", "https://www.concursopublico.sp.gov.br/"),
    ("municipio_sp", "diario_oficial_capital", "https://diariooficial.prefeitura.sp.gov.br/"),
]
for group, name, url in PAGES:
    fetch(name, url, group=group)
    time.sleep(0.8)

# --------------------------------------------------------------- relatorio
summary["robots"] = [{"host": v["host"], "status": v["status"], "erro": v["error"],
                      "interpretado": v.get("parsed")} for v in robots_cache.values()]
summary["requisicoes"] = results
with open(os.path.join(OUT, "summary.json"), "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1, default=str)

lines = ["# Sondagem de fontes", "", f"Gerado em {summary['gerado_em_utc']}", "",
         "| grupo | fonte | status | bytes | robots | observação |", "|---|---|---|---|---|---|"]
for x in results:
    if x["group"] in ("pncp", "querido_diario") and re.search(r"_p([3-9]|10)$", x["name"]):
        continue
    obs = x.get("skipped") or x.get("error") or ""
    rb = "ok" if x.get("robots_allowed_generic") else "PROIBE"
    lines.append(f"| {x['group']} | {x['name']} | {x.get('status', '-')} | {x.get('bytes', '-')} | {rb} | {str(obs)[:90]} |")
with open(os.path.join(OUT, "summary.md"), "w") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
print(json.dumps({k: summary[k] for k in ("ibge", "querido_diario")}, ensure_ascii=False, indent=1, default=str)[:6000])
