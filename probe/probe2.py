#!/usr/bin/env python3
"""Sondagem, rodada 2: aprofunda as fontes que responderam na rodada 1.

- Querido Diario: diagnostico de TLS e, se conectar, cobertura e frescor em SP.
- PNCP: paginacao completa com espera e novas tentativas.
- DOE-SP: consultas por frases de autorizacao.
- PCI: pagina nacional e paginas de detalhe.
- Bancas com listagem acessivel.
- IBGE: municipios com regioes.
"""
import datetime as dt
import json
import os
import re
import ssl
import subprocess
import time

import requests
from requests.adapters import HTTPAdapter

UA = ("Mozilla/5.0 (compatible; concursos-sp-bot/0.1; "
      "+https://github.com/profcaiodaniel/concursos-sp)")
OUT = "probe_out"
RAW = os.path.join(OUT, "raw2")
os.makedirs(RAW, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
TODAY = dt.date.today()
summary = {"gerado_em_utc": dt.datetime.utcnow().isoformat() + "Z"}
log = []


def get(url, params=None, tries=4, wait=20, timeout=60, session=None):
    """GET com novas tentativas e espera crescente."""
    s = session or S
    last = None
    for i in range(tries):
        try:
            r = s.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504, 520, 522, 524):
                last = f"HTTP {r.status_code}"
                time.sleep(wait * (i + 1))
                continue
            return r, None
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:300]
            time.sleep(wait * (i + 1))
    return None, last


def save(name, r):
    if r is None:
        return None
    ext = "json" if "json" in r.headers.get("content-type", "") else "html"
    fn = os.path.join(RAW, f"{name}.{ext}")
    with open(fn, "wb") as f:
        f.write(r.content[:5_000_000])
    return fn


def sh(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + "\n" + p.stderr)[-3500:]
    except Exception as e:  # noqa: BLE001
        return repr(e)[:300]


# ------------------------------------------------------------ 1. QD / TLS
QD = "https://api.queridodiario.ok.org.br"
qd = {"diagnostico": {}}
qd["diagnostico"]["dns"] = sh("getent hosts api.queridodiario.ok.org.br; getent hosts queridodiario.ok.org.br")
qd["diagnostico"]["curl_default"] = sh(f"curl -sS -m 40 -o /dev/null -w '%{{http_code}} %{{ssl_verify_result}} %{{remote_ip}}' -A '{UA}' '{QD}/cities?city_name=campinas' -v 2>&1 | tail -25")
qd["diagnostico"]["curl_tls12"] = sh(f"curl -sS -m 40 --tlsv1.2 --tls-max 1.2 -o /dev/null -w '%{{http_code}}' -A '{UA}' '{QD}/cities?city_name=campinas' 2>&1 | tail -5")
qd["diagnostico"]["curl_http"] = sh(f"curl -sS -m 40 -o /dev/null -w '%{{http_code}} %{{redirect_url}}' -A '{UA}' 'http://api.queridodiario.ok.org.br/cities?city_name=campinas' 2>&1 | tail -5")
qd["diagnostico"]["openssl"] = sh("echo | openssl s_client -connect api.queridodiario.ok.org.br:443 -servername api.queridodiario.ok.org.br 2>&1 | head -40")


class LegacyTLS(HTTPAdapter):
    def init_poolmanager(self, *a, **k):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        k["ssl_context"] = ctx
        return super().init_poolmanager(*a, **k)


qs = requests.Session()
qs.headers.update({"User-Agent": UA})
qs.mount("https://", LegacyTLS())
qd_session = None
for label, sess, base in [("requests_padrao", S, QD), ("requests_seclevel1", qs, QD),
                          ("http_sem_tls", S, "http://api.queridodiario.ok.org.br")]:
    r, err = get(base + "/cities", params={"city_name": ""}, tries=2, wait=10, session=sess)
    ok = False
    if r is not None:
        try:
            ok = "cities" in r.json()
        except Exception:  # noqa: BLE001
            ok = False
    qd["diagnostico"][label] = {"status": getattr(r, "status_code", None), "erro": err, "ok": ok,
                                "url_final": getattr(r, "url", None)}
    if ok and qd_session is None:
        qd_session, qd_base = sess, base
        save("qd_cities", r)
        cities = r.json()["cities"]
        sp = [c for c in cities if c.get("state_code") == "SP"]
        qd.update(total_brasil=len(cities), cidades_sp=len(sp), via=label,
                  exemplo=sp[0] if sp else None)
        with open(os.path.join(OUT, "qd_cidades_sp.json"), "w") as f:
            json.dump(sp, f, ensure_ascii=False)

if qd_session:
    fresh = {}
    for c in sp:
        tid = c["territory_id"]
        r, err = get(qd_base + "/gazettes", params={"territory_ids": tid, "size": 1,
                                                    "sort_by": "descending_date"},
                     tries=2, wait=5, session=qd_session)
        try:
            j = r.json()
            g = (j.get("gazettes") or [{}])[0]
            fresh[tid] = {"nome": c.get("territory_name"), "total": j.get("total_gazettes"),
                          "ultima_data": g.get("date")}
        except Exception:  # noqa: BLE001
            fresh[tid] = {"nome": c.get("territory_name"), "erro": err or "json"}
        time.sleep(1.1)
    with open(os.path.join(OUT, "qd_frescor_sp.json"), "w") as f:
        json.dump(fresh, f, ensure_ascii=False, indent=0)
    for d in (30, 90, 180):
        lim = (TODAY - dt.timedelta(days=d)).isoformat()
        qd[f"sp_atualizado_{d}d"] = sum(1 for v in fresh.values() if (v.get("ultima_data") or "") >= lim)
    qd["sp_com_algum_diario"] = sum(1 for v in fresh.values() if v.get("ultima_data"))
    for nome, q in [("concurso_publico", '"concurso público"'),
                    ("autoriza_concurso", '"autoriza" + "concurso público"'),
                    ("banca_concurso", '"concurso público" + ("contratação de empresa" | "banca")')]:
        r, err = get(qd_base + "/gazettes",
                     params={"querystring": q, "published_since": (TODAY - dt.timedelta(days=60)).isoformat(),
                             "size": 100, "sort_by": "descending_date",
                             "territory_ids": [c["territory_id"] for c in sp],
                             "excerpt_size": 500, "number_of_excerpts": 2},
                     tries=2, wait=5, session=qd_session)
        fn = save("qd_busca_" + nome, r)
        try:
            j = r.json()
            qd["busca_" + nome] = {"total": j.get("total_gazettes"), "arquivo": fn,
                                   "municipios_na_pagina": len({g.get("territory_id") for g in j.get("gazettes", [])})}
        except Exception:  # noqa: BLE001
            qd["busca_" + nome] = {"erro": err, "status": getattr(r, "status_code", None)}
        time.sleep(1.5)
summary["querido_diario"] = qd

# ---------------------------------------------------------------- 2. PNCP
KEEP = ["title", "description", "item_url", "numero_controle_pncp", "orgao_nome", "orgao_cnpj",
        "unidade_nome", "esfera_nome", "poder_nome", "municipio_nome", "codigo_ibge", "uf",
        "modalidade_licitacao_nome", "situacao_nome", "data_publicacao_pncp", "data_atualizacao_pncp",
        "cancelado", "valor_global", "tipo_nome", "document_type", "fornecedor_nome", "ano",
        "data_assinatura", "data_inicio_vigencia", "data_fim_vigencia", "tem_resultado"]
pncp = {}
for nome, q, tipo, maxp in [
    ("edital_concurso_publico", "concurso público", "edital", 25),
    ("contrato_concurso_publico", "concurso público", "contrato", 12),
    ("edital_processo_seletivo", "processo seletivo", "edital", 4),
]:
    out, total, erros = [], None, []
    for pag in range(1, maxp + 1):
        r, err = get("https://pncp.gov.br/api/search/",
                     params={"q": q, "tipos_documento": tipo, "ordenacao": "-data", "pagina": pag,
                             "tam_pagina": 100, "status": "todos", "ufs": "SP"}, tries=5, wait=15)
        if r is None:
            erros.append({"pagina": pag, "erro": err})
            break
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            erros.append({"pagina": pag, "erro": f"nao-json HTTP {r.status_code}"})
            break
        its = j.get("items") or []
        total = j.get("total", total)
        out += [{k: it.get(k) for k in KEEP} for it in its]
        if len(its) < 100:
            break
        time.sleep(4)
    with open(os.path.join(OUT, f"pncp_{nome}.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)
    pncp[nome] = {"total": total, "lidos": len(out), "erros": erros,
                  "municipios_distintos": len({x.get("codigo_ibge") for x in out if x.get("codigo_ibge")}),
                  "mais_antigo": min((x.get("data_publicacao_pncp") or "9" for x in out), default=None)}
    time.sleep(8)
summary["pncp"] = pncp

# -------------------------------------------------------------- 3. DOE-SP
doe = {}
DOE = "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications"
d0 = (TODAY - dt.timedelta(days=120)).isoformat()
for nome, termo, extra in [
    ("autoriza_abertura", "autoriza a abertura de concurso público", {}),
    ("autorizo_abertura", "autorizo a abertura de concurso público", {}),
    ("autorizacao_concurso", "autorização para abertura de concurso público", {}),
    ("abertura_inscricoes", "abertura de inscrições concurso público", {}),
    ("concurso_publico_desc", "concurso público", {"SortDirection": "desc"}),
    ("concurso_publico_desc2", "concurso público", {"SortOrder": "Descending"}),
]:
    p = {"periodStartingDate": "personalized", "PageNumber": 1, "Terms[0]": termo, "FromDate": d0,
         "ToDate": TODAY.isoformat(), "PageSize": 50, "SortField": "Date"}
    p.update(extra)
    r, err = get(DOE, params=p, tries=3, wait=10)
    fn = save("doe_" + nome, r)
    try:
        j = r.json()
        its = j.get("items", [])
        doe[nome] = {"totalItems": j.get("totalItems"), "totalPages": j.get("totalPages"),
                     "primeira_data": its[0]["date"][:10] if its else None,
                     "ultima_data": its[-1]["date"][:10] if its else None, "arquivo": fn}
    except Exception:  # noqa: BLE001
        doe[nome] = {"erro": err, "status": getattr(r, "status_code", None),
                     "corpo": (r.text[:300] if r is not None else None)}
    time.sleep(2)
# pagina de uma publicacao (para saber se o texto integral e acessivel)
try:
    j = json.load(open(os.path.join(RAW, "doe_autoriza_abertura.json")))
    it = j["items"][0]
    for nome, url in [("doe_pub_pagina", "https://www.doe.sp.gov.br/" + it["slug"]),
                      ("doe_pub_api", "https://do-api-web-search.doe.sp.gov.br/v2/publications/" + it["id"]),
                      ("doe_pub_api_slug", "https://do-api-web-search.doe.sp.gov.br/v2/publications/" + it["slug"])]:
        r, err = get(url, tries=1)
        doe[nome] = {"status": getattr(r, "status_code", None), "bytes": len(r.content) if r is not None else None,
                     "erro": err, "arquivo": save(nome, r)}
        time.sleep(1)
except Exception as e:  # noqa: BLE001
    doe["pub_erro"] = repr(e)[:200]
summary["doe_sp"] = doe

# ----------------------------------------------------------------- 4. PCI
pci = {}
for nome, url in [("pci_nacional", "https://www.pciconcursos.com.br/concursos/nacional/"),
                  ("pci_sudeste", "https://www.pciconcursos.com.br/concursos/sudeste/")]:
    r, err = get(url, tries=2, wait=10)
    pci[nome] = {"status": getattr(r, "status_code", None), "erro": err, "arquivo": save(nome, r)}
    if nome == "pci_sudeste" and r is not None:
        t = r.text
        a, b = t.find('<div class="uf">SÃO PAULO</div>'), t.find('<div class="uf">RIO DE JANEIRO</div>')
        urls = re.findall(r'data-url="([^"]+)"', t[a:b])
        pci["entradas_sp"] = len(urls)
        for i, u in enumerate(urls[:1] + urls[40:41] + urls[120:121] + urls[-1:]):
            time.sleep(2)
            rr, e2 = get(u, tries=2, wait=10)
            pci[f"detalhe_{i}"] = {"url": u, "status": getattr(rr, "status_code", None), "erro": e2,
                                   "arquivo": save(f"pci_detalhe_{i}", rr)}
    time.sleep(2)
summary["pci"] = pci

# -------------------------------------------------------------- 5. Bancas
bancas = {}
for nome, url in [
    ("institutomais_abertos", "https://www.institutomais.org.br/Concursos/ConcursosAbertos"),
    ("ibfc_abertos", "https://ibfc.selecao.net.br/index/abertos/"),
    ("zambini_concursos", "https://www.zambini.org.br/portal/concursos"),
    ("fgv_concursos", "https://conhecimento.fgv.br/concursos"),
    ("nossorumo_home", "https://www.nossorumo.org.br/"),
    ("cebraspe_api", "https://api.cebraspe.org.br/concursos/api/concursos/andamento"),
    ("indepac_home", "https://www.indepac.org.br/"),
    ("rbo_home", "https://www.rboconcursos.com.br/"),
    ("publiconsult_home", "https://www.publiconsult.com.br/"),
    ("concursosnobrasil_sp", "https://concursosnobrasil.com/concursos/sp/"),
    ("concursosnobrasil_previstos_sp", "https://concursosnobrasil.com/concursos/previstos/sp/"),
]:
    host = re.match(r"https?://[^/]+", url).group(0)
    rb, _ = get(host + "/robots.txt", tries=1, timeout=20)
    r, err = get(url, tries=2, wait=8)
    bancas[nome] = {"status": getattr(r, "status_code", None), "bytes": len(r.content) if r is not None else None,
                    "erro": err, "arquivo": save("banca_" + nome, r),
                    "robots_status": getattr(rb, "status_code", None)}
    if rb is not None and rb.status_code == 200:
        with open(os.path.join(RAW, f"robots_{nome}.txt"), "w") as f:
            f.write(rb.text[:50000])
    time.sleep(1.5)
summary["bancas"] = bancas

# ---------------------------------------------------------------- 6. IBGE
ib = {}
r, err = get("https://servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios", tries=4, wait=15, timeout=90)
ib["localidades"] = {"status": getattr(r, "status_code", None), "erro": err}
if r is not None and r.status_code == 200:
    with open(os.path.join(OUT, "ibge_municipios_sp.json"), "wb") as f:
        f.write(r.content)
    ib["localidades"]["n"] = len(r.json())
r, err = get("https://apisidra.ibge.gov.br/values/t/6579/n6/in%20n3%2035/v/9324/p/last%201", tries=3, wait=10)
if r is not None and r.status_code == 200:
    rows = r.json()[1:]
    with open(os.path.join(OUT, "ibge_pop_estimada.json"), "w") as f:
        json.dump({x["D1C"]: {"nome": x["D1N"], "pop": x["V"], "ano": x["D3N"]} for x in rows}, f, ensure_ascii=False)
    ib["sidra"] = {"n": len(rows), "campos": list(rows[0].keys())}
summary["ibge"] = ib

with open(os.path.join(OUT, "summary2.json"), "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1, default=str)
print(json.dumps(summary, ensure_ascii=False, indent=1, default=str)[:12000])
