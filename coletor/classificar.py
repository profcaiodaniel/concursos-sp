"""Classificacao de orgaos: esfera, municipio e chave de comparacao entre fontes."""
from __future__ import annotations

import re

from .base import Municipios, norm

RE_FEDERAL = re.compile(
    r"\bIBGE\b|\bINSS\b|\bfederal\b|\bfederais\b|\bTRF\b|\bTRT\b|\bTRE\b|\bTSE\b|\bTST\b|\bSTJ\b|\bSTF\b|\bSTM\b|"
    r"\bIF[A-Z]{2}\b|\bUF[A-Z]{2,6}\b|\bunifesp\b|\bufscar\b|\bufabc\b|"
    r"minist[eé]rio d[aeo]s?\b|minist[eé]rio p[uú]blico (federal|do trabalho|militar|da uni[aã]o)|"
    r"\bmarinha\b|\bex[eé]rcito\b|\baeron[aá]utica\b|for[cç]a a[eé]rea|\bFAB\b|\bEBSERH\b|\bHU BRASIL\b|"
    r"banco do brasil|caixa econ[oô]mica|\bcorreios\b|\bpetrobras\b|\bBNDES\b|\bdataprev\b|\bserpro\b|"
    r"conselho (regional|federal)|\bCR[A-Z]{1,4}[- /]?(SP|\d)|\bCRECI\b|\bCREA\b|\bCREMESP\b|\bCOREN\b|\bOAB\b|\bCREF\b|\bCRO\b|"
    r"\bANVISA\b|\bANS\b|\bANATEL\b|\bANEEL\b|\bANAC\b|\bANTT\b|\bANP\b|\bANA\b|\bBACEN\b|banco central|"
    r"\bPRF\b|\bABIN\b|\bTCU\b|\bCNEN\b|\bINB\b|\bIPEN\b|\bITA\b|\bINPE\b|\bCNPq\b|\bCAPES\b|\bDPU\b|\bMPU\b|\bAGU\b|\bCGU\b|"
    r"\bCNU\b|concurso (p[uú]blico )?nacional unificado|\bEMBRAPA\b|\bFIOCRUZ\b|\bINCRA\b|\bIBAMA\b|\bICMBIO\b|\bFUNAI\b|"
    r"\bda uni[aã]o\b|\bnuclebr[aá]s\b|\bamazul\b|\bIMBEL\b|\bCEAGESP\b|\bINFRAERO\b|\bTELEBRAS\b|\bFINEP\b", re.I)
RE_ESTADUAL = re.compile(
    r"estado de s[aã]o paulo|governo de s[aã]o paulo|\bTJ[- ]?SP\b|\bTJM[- ]?SP\b|\bMP[- ]?SP\b|\bTCE[- ]?SP\b|\bALESP\b|"
    r"\bUSP\b|\bUNESP\b|\bUNICAMP\b|\bFATEC\b|centro paula souza|\bCPS\b|\bCEETEPS\b|\bETEC\b|\bPM[- ]?SP\b|\bPC[- ]?SP\b|"
    r"pol[ií]cia (militar|civil|penal|t[eé]cnico)|\bSEDUC\b|\bSAP[- ]SP\b|funda[cç][aã]o casa|\bCETESB\b|\bSABESP\b|"
    r"\bDETRAN\b|\bDER[- ]SP\b|\bDAEE\b|\bPRODESP\b|\bIAMSPE\b|hospital das cl[ií]nicas|\bHC[A-Z]{0,5}\b|\bFAMESP\b|"
    r"\bFAMEMA\b|\bFAMERP\b|\bCOTIL\b|\bCOTUCA\b|\bUNIVESP\b|defensoria p[uú]blica|\bDPE[- ]?SP\b|\bPGE[- ]?SP\b|"
    r"\bSPPREV\b|\bIPA\b|\bITESP\b|\bCDHU\b|\bMETR[OÔ]\b|\bCPTM\b|\bEMTU\b|\bARTESP\b|\bARSESP\b|\bJUCESP\b|"
    r"\bPROCON[- ]SP\b|universidade estadual|\bestadual\b|\bSES[- ]SP\b|\bSEFAZ[- ]SP\b|\bFURP\b|\bIPT\b|\bIMESP\b|"
    r"\bSP ?[ÁA]GUAS\b|\bCIS SP\b|corpo de bombeiros|\bFUNAP\b|\bFDE\b|instituto butantan|\bIAL\b|\bSUCEN\b", re.I)
RE_NAO_E_CAPITAL = re.compile(
    r"(estado|universidade|governo|federal|justi[cç]a|tecnologia|regional|trabalho|eleitoral|contas|"
    r"regi[aã]o metropolitana|metropolitano|companhia|ambiental|paulista|hospital|medicina|corretores de im[oó]veis do estado)"
    r"( do estado)? de s[aã]o paulo", re.I)
RE_PREFEITURA = re.compile(r"\bprefeitura\b|^\s*munic[ií]pio d", re.I)
RE_CAMARA = re.compile(r"\bc[aâ]mara\b", re.I)


def municipio_de(M: Municipios, *textos: str) -> dict | None:
    """Primeiro municipio paulista achado nos textos, ignorando 'Estado de Sao Paulo' e similares."""
    for t in textos:
        if not t:
            continue
        m = M.achar(RE_NAO_E_CAPITAL.sub(" ", t))
        if m:
            return m
    return None


def esfera_de(orgao: str, titulo: str, mun: dict | None, esfera_fonte: str | None = None) -> str:
    """'municipal', 'estadual', 'federal' ou 'a conferir'."""
    if esfera_fonte:
        e = norm(esfera_fonte)
        if e in ("municipal", "estadual", "federal"):
            return e
    alvo = f"{orgao} | {titulo}"
    if re.search(r"c[aâ]mara dos deputados|senado federal|c[aâ]mara legislativa", orgao, re.I):
        return "federal" if not re.search(r"legislativa", orgao, re.I) else "a conferir"
    if RE_PREFEITURA.search(orgao) or RE_CAMARA.search(orgao):
        return "municipal"
    if RE_FEDERAL.search(alvo):
        return "federal"
    if RE_ESTADUAL.search(alvo):
        return "estadual"
    if mun is not None:
        return "municipal"
    return "a conferir"


def chave_orgao(orgao: str, mun: dict | None) -> str:
    """Chave para reconhecer o mesmo orgao em fontes diferentes."""
    cod = mun["codigo_ibge"] if mun else ""
    if RE_PREFEITURA.search(orgao) and cod:
        return f"prefeitura:{cod}"
    if RE_CAMARA.search(orgao) and cod:
        return f"camara:{cod}"
    sigla = re.match(r"^\s*([A-Z][A-Za-z0-9]{1,11})\s+[-–]\s+", orgao)
    if sigla:
        return f"orgao:{norm(sigla.group(1))}:{cod}"
    n = norm(orgao)
    n = re.sub(r"\b(de|da|do|das|dos|e|em|sp|s a|sa|ltda)\b", " ", n)
    return f"orgao:{' '.join(n.split())}:{cod}"


def tipo_de(titulo: str) -> str:
    n = norm(titulo)
    c = bool(re.search(r"\bconcursos?\b", n)) and not re.search(r"\bconcurso de (redacao|fotografia|musica)", n)
    p = bool(re.search(r"processos? seletivos?|selecao|selecoes|seletivo", n))
    if c and p:
        return "concurso e processo seletivo"
    if c:
        return "concurso público"
    if p:
        return "processo seletivo"
    return "a conferir"


def sigla_de(orgao: str) -> str:
    """'TJSP - Tribunal de Justica...' -> 'tjsp'; '' se o nome nao comeca por sigla."""
    partes = re.split(r"\s+[-–]\s+", orgao, maxsplit=1)
    if len(partes) < 2:
        return ""
    n = norm(partes[0])
    return n.replace(" ", "") if len(n.split()) <= 3 else ""


def mesmo_orgao_por_sigla(nome_curto: str, orgao_longo: str) -> bool:
    """'TJ SP' x 'TJSP - Tribunal...', 'SETEC de Campinas' x 'SETEC - Servicos...'."""
    sig = sigla_de(orgao_longo)
    n = norm(nome_curto)
    if not sig or not n:
        return False
    compacto = n.replace(" ", "")
    return compacto == sig or (len(sig) >= 4 and (compacto.startswith(sig) or n.split()[0] == sig))
