#!/usr/bin/env python3
"""Sondagem, rodada 3: diagnostico curto do Querido Diario e do IBGE."""
import json, os, subprocess, time
OUT = "probe_out"; os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (compatible; concursos-sp-bot/0.1; +https://github.com/profcaiodaniel/concursos-sp)"
def sh(cmd, timeout=90):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + "\n" + p.stderr)[-4000:]
    except Exception as e:
        return repr(e)[:300]
d = {}
H = "api.queridodiario.ok.org.br"
d["dns"] = sh(f"getent ahosts {H} | head -5; getent ahosts queridodiario.ok.org.br | head -3")
d["openssl"] = sh(f"echo | timeout 30 openssl s_client -connect {H}:443 -servername {H} 2>&1 | head -30")
d["openssl_tls12"] = sh(f"echo | timeout 30 openssl s_client -tls1_2 -connect {H}:443 -servername {H} 2>&1 | head -12")
d["curl_v"] = sh(f"curl -sS -m 40 -o {OUT}/qd_cities_campinas.json -w 'HTTP %{{http_code}} ip %{{remote_ip}}' -A '{UA}' 'https://{H}/cities?city_name=campinas' -v 2>&1 | tail -30")
d["curl_http"] = sh(f"curl -sS -m 40 -o /dev/null -w 'HTTP %{{http_code}} -> %{{redirect_url}}' -A '{UA}' 'http://{H}/cities?city_name=campinas' 2>&1 | tail -3")
d["curl_all_cities"] = sh(f"curl -sS -m 80 -o {OUT}/qd_cities.json -w 'HTTP %{{http_code}} bytes %{{size_download}}' -A '{UA}' 'https://{H}/cities?city_name=' 2>&1 | tail -3")
d["curl_gazettes"] = sh(f"curl -sS -m 80 -o {OUT}/qd_gazettes_jundiai.json -w 'HTTP %{{http_code}} bytes %{{size_download}}' -A '{UA}' 'https://{H}/gazettes?territory_ids=3525904&size=2&sort_by=descending_date' 2>&1 | tail -3")
d["curl_front_api"] = sh(f"curl -sS -m 40 -o /dev/null -w 'HTTP %{{http_code}}' -A '{UA}' 'https://queridodiario.ok.org.br/api/cities?city_name=campinas' -L 2>&1 | tail -3")
d["ibge_localidades"] = sh(f"curl -sS -m 120 --retry 3 --retry-delay 10 -o {OUT}/ibge_municipios_sp.json -w 'HTTP %{{http_code}} bytes %{{size_download}}' 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios' 2>&1 | tail -3", timeout=420)
d["cebraspe_api"] = sh(f"curl -sS -m 30 -o /dev/null -w 'HTTP %{{http_code}}' -A '{UA}' 'https://api.cebraspe.org.br/' 2>&1 | tail -2")
json.dump(d, open(f"{OUT}/summary3.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(d, ensure_ascii=False, indent=1))
