"""Infraestrutura comum: HTTP educado, texto, datas e municipios."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.robotparser
from urllib.parse import urlsplit

import requests

UA = ("Mozilla/5.0 (compatible; concursos-sp-bot/1.0; "
      "+https://github.com/profcaiodaniel/concursos-sp)")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, "dados")


def hoje() -> dt.date:
    """Data de hoje no fuso de Sao Paulo (UTC-3, sem horario de verao)."""
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).date()


def agora_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------- HTTP
class Cliente:
    """Sessao HTTP que respeita robots.txt, espera entre requisicoes por host
    e tenta de novo com espera crescente."""

    def __init__(self, intervalo: float = 1.5):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        self.intervalo = intervalo
        self._ultimo: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _host(self, url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def permitido(self, url: str) -> bool:
        host = self._host(url)
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(host + "/robots.txt", timeout=25)
                if r.status_code == 200 and "html" not in r.headers.get("content-type", "").lower():
                    rp.parse(r.text.splitlines())
                    self._robots[host] = rp
                else:
                    self._robots[host] = None  # sem robots.txt valido: nada proibido
            except requests.RequestException:
                self._robots[host] = None
            self._ultimo[host] = time.time()
        rp = self._robots[host]
        return True if rp is None else (rp.can_fetch(UA, url) and rp.can_fetch("*", url))

    def get(self, url: str, params: dict | None = None, *, robots: bool = True,
            tentativas: int = 4, espera: float = 15, timeout: float = 60,
            intervalo: float | None = None) -> requests.Response:
        """Devolve a resposta (status < 400) ou levanta ErroFonte."""
        cheio = requests.Request("GET", url, params=params).prepare().url
        if robots and not self.permitido(cheio):
            raise ErroFonte(f"robots.txt proíbe {url}")
        host = self._host(url)
        ultimo_erro = "?"
        for i in range(tentativas):
            falta = (intervalo or self.intervalo) - (time.time() - self._ultimo.get(host, 0))
            if falta > 0:
                time.sleep(falta)
            try:
                r = self.s.get(url, params=params, timeout=timeout)
                self._ultimo[host] = time.time()
                if r.status_code < 400:
                    return r
                ultimo_erro = f"HTTP {r.status_code}"
                if r.status_code in (401, 403, 404, 410):
                    break
            except requests.RequestException as e:
                self._ultimo[host] = time.time()
                ultimo_erro = type(e).__name__
            time.sleep(espera * (i + 1))
        raise ErroFonte(f"{ultimo_erro} em {url}")


class ErroFonte(Exception):
    """Falha ao acessar ou interpretar uma fonte. Vai para o relatorio da pagina."""


# -------------------------------------------------------------------- texto
def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """minusculas, sem acento, so letras e numeros separados por espaco."""
    return re.sub(r"[^a-z0-9]+", " ", sem_acento(s or "").lower()).strip()


def limpa_html(s: str) -> str:
    import html as _h
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", s, flags=re.I)
    s = _h.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\s*\n\s*", "\n", s).strip()


def id_de(*partes: str) -> str:
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:12]


def data_br(s: str | None) -> str | None:
    """'30/11/2026' -> '2026-11-30'. Devolve None se nao for uma data valida."""
    if not s:
        return None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s)
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def dinheiro(s: str | None) -> float | None:
    """'R$ 13.359,44' -> 13359.44"""
    if not s:
        return None
    m = re.search(r"R\$\s*([\d.]+,\d{2}|[\d.]+)", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


# --------------------------------------------------------------- municipios
class Municipios:
    """Os 645 municipios paulistas (IBGE), com busca por nome dentro de um texto."""

    def __init__(self, caminho: str | None = None):
        with open(caminho or os.path.join(DADOS, "municipios.json"), encoding="utf-8") as f:
            self.lista = json.load(f)["municipios"]
        self.por_codigo = {m["codigo_ibge"]: m for m in self.lista}
        self.por_norm = {norm(m["nome"]): m for m in self.lista}
        # nomes mais longos primeiro, para "Salto de Pirapora" ganhar de "Salto"
        self._ordem = sorted(self.lista, key=lambda m: -len(m["nome"]))
        self._re = {m["codigo_ibge"]: re.compile(
            r"(?<![A-Za-zÀ-ÿ])" + re.escape(norm(m["nome"])).replace(r"\ ", r"[\s'’-]+") + r"(?![A-Za-zÀ-ÿ])")
            for m in self.lista}

    def achar(self, texto: str) -> dict | None:
        """Acha um municipio paulista citado em `texto`.

        Exige que o nome apareca com inicial maiuscula no texto original, para
        nao confundir nomes como Registro, Salto ou Socorro com palavras comuns.
        Devolve None se nao achar ou se achar mais de um candidato distinto.
        """
        if not texto:
            return None
        base = sem_acento(texto)
        baixo = re.sub(r"[^a-z0-9'’\s-]", " ", base.lower())
        achados, ocupado = [], []
        for m in self._ordem:
            for mt in self._re[m["codigo_ibge"]].finditer(baixo):
                a, b = mt.span()
                if any(a < fb and fa < b for fa, fb in ocupado):
                    continue
                if not base[a].isupper():
                    continue
                ocupado.append((a, b))
                achados.append((a, m))
        if not achados:
            return None
        cods = {m["codigo_ibge"] for _, m in achados}
        if len(cods) > 1:
            # "Estado de Sao Paulo" nao e o municipio de Sao Paulo
            cods_sem_capital = {c for c in cods if c != "3550308"}
            if len(cods_sem_capital) == 1:
                return self.por_codigo[cods_sem_capital.pop()]
            return None
        return achados[0][1]


RE_ESTADO_SP = re.compile(r"estado de s[aã]o paulo|governo de s[aã]o paulo|paulista\b", re.I)
