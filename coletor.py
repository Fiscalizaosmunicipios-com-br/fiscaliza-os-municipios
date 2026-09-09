#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fiscaliza os Municípios — Coletor v2.0
Implementa a arquitetura do documento ARQUITETURA.md:

  NOTA = 0,40·F + 0,30·C + 0,30·Q
    F = 0,50·F_eq  + 0,30·F_pes  + 0,20·F_inv   (Gestão fiscal — Executivo)
    C = 0,50·C_teto + 0,30·C_folha + 0,20·C_rel (Custo do Legislativo)
    Q = 0,60·Q_prop + 0,40·Q_tema               (Qualidade legislativa)*
  * Q_aprov (efetividade) entra na Fase B, quando a ligação
    matéria→norma estiver coletada; os pesos foram renormalizados.

Fontes ao vivo: SICONFI (RREO, RGF Executivo e Legislativo, DCA),
IBGE (população/localidades), SAPL/Interlegis (proposições + autoria,
com classificação NLP estágio 1 sobre as ementas) e Querido Diário.
"""

import json
import re
import sys
import time
import math
import unicodedata
from datetime import datetime, timezone

import requests

# ═════════════════ CONFIGURAÇÃO DE CIDADES ═════════════════
CIDADES = [
    {"nome": "Charqueada", "uf": "SP", "ibge": "3511706", "vereadores": 11, "sapl": None,
     "transparencia": "https://webapp1-charqueada.cidade360.cloud/pronimtb/",
     "transparencia_sistema": "Pronim TB (Cidade360)",
     "siscam": "https://charqueada.siscam.com.br",
     "periodo_proposituras": ("01/01/2025", "09/09/2026"),
     "fontes_extra": [
        ("Proposituras — SisCam (Câmara de Charqueada)",
         "http://consulta.siscam.com.br/camaracharqueada/index/80/8"),
        ("Leis municipais — Legislação Digital",
         "https://legislacaodigital.com.br/Charqueada-sp"),
        ("Transparência da Câmara (portal próprio)",
         "http://186.250.144.166:5656/transparencia/"),
        ("Diário Oficial de Charqueada",
         "https://www.charqueada.sp.gov.br/portal/diario-oficial"),
     ]},
    {"nome": "São Pedro", "uf": "SP", "ibge": "3550407", "vereadores": 11, "sapl": None},
    {"nome": "Rio das Pedras", "uf": "SP", "ibge": "3544004", "vereadores": 10, "sapl": None},
    {"nome": "Piracicaba", "uf": "SP", "ibge": "3538709", "vereadores": 23, "sapl": None},
    {"nome": "Jacareí", "uf": "SP", "ibge": "3524402", "vereadores": 13, "sapl": None},
    {"nome": "Ilha Comprida", "uf": "SP", "ibge": None, "vereadores": 9,
     "sapl": "https://sapl.ilhacomprida.sp.leg.br"},
    {"nome": "Sales Oliveira", "uf": "SP", "ibge": "3544905", "vereadores": 9,
     "sapl": "https://sapl.salesoliveira.sp.leg.br"},
]

# Capitais (Brasília fora: DF não tem Câmara de Vereadores; art. 29-A não se aplica)
CAPITAIS = [
    ("Rio Branco", "AC", "1200401"), ("Maceió", "AL", "2704302"),
    ("Macapá", "AP", "1600303"), ("Manaus", "AM", "1302603"),
    ("Salvador", "BA", "2927408"), ("Fortaleza", "CE", "2304400"),
    ("Vitória", "ES", "3205309"), ("Goiânia", "GO", "5208707"),
    ("São Luís", "MA", "2111300"), ("Cuiabá", "MT", "5103403"),
    ("Campo Grande", "MS", "5002704"), ("Belo Horizonte", "MG", "3106200"),
    ("Belém", "PA", "1501402"), ("João Pessoa", "PB", "2507507"),
    ("Curitiba", "PR", "4106902"), ("Recife", "PE", "2611606"),
    ("Teresina", "PI", "2211001"), ("Rio de Janeiro", "RJ", "3304557"),
    ("Natal", "RN", "2408102"), ("Porto Alegre", "RS", "4314902"),
    ("Porto Velho", "RO", "1100205"), ("Boa Vista", "RR", "1400100"),
    ("Florianópolis", "SC", "4205407"), ("São Paulo", "SP", "3550308"),
    ("Aracaju", "SE", "2800308"), ("Palmas", "TO", "1721000"),
]
for _n, _uf, _cod in CAPITAIS:
    CIDADES.append({"nome": _n, "uf": _uf, "ibge": _cod,
                    "vereadores": None, "sapl": None, "capital": True})

SICONFI = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
TIMEOUT = 30
UA = {"User-Agent": "FiscalizaOsMunicipios/2.0 (projeto civico; dados publicos)"}

DOMINIO = "https://fiscalizaosmunicipios.com.br"
MARCA = "Fiscaliza os Municípios"
REPO = "https://github.com/Fiscalizaosmunicipios-com-br/fiscaliza-os-municipios"

# Demonstração (usada só quando a fonte falha; sempre status="demo")
DEMO_FIN = {
    "3511706": (15814, 118e6, 112.5e6, 52e6, 3.35e6),
    "3550407": (37000, 260e6, 252e6, 120e6, 8.2e6),
    "3544004": (36000, 240e6, 236e6, 112e6, 7.9e6),
    "3538709": (425000, 2600e6, 2510e6, 1300e6, 68e6),
    "3524402": (242093, 1512e6, 1448e6, 690e6, 32.8e6),
}
DEMO_PROPS = [
    {"tipo": "Projetos de Lei", "qtd": 40, "peso": "alta"},
    {"tipo": "Emendas e substitutivos", "qtd": 15, "peso": "alta"},
    {"tipo": "Requerimentos", "qtd": 60, "peso": "media"},
    {"tipo": "Indicações", "qtd": 250, "peso": "baixa"},
    {"tipo": "Moções e homenagens", "qtd": 85, "peso": "baixa"},
]


def demo_fin(c):
    return DEMO_FIN.get(c["ibge"], (500_000, 3_000_000_000, 2_950_000_000,
                                    1_400_000_000, 60_000_000))


# ═════════════════ UTILITÁRIOS ═════════════════
def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bloco(valor, fonte, url, status, detalhe=""):
    return {"valor": valor, "fonte": fonte, "url": url, "status": status,
            "coletado_em": agora(), "detalhe": detalhe}


def slug(nome):
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return s.lower().replace(" ", "")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


UF_COD = {"AC": 12, "AL": 27, "AP": 16, "AM": 13, "BA": 29, "CE": 23, "DF": 53,
          "ES": 32, "GO": 52, "MA": 21, "MT": 51, "MS": 50, "MG": 31, "PA": 15,
          "PB": 25, "PR": 41, "PE": 26, "PI": 22, "RJ": 33, "RN": 24, "RS": 43,
          "RO": 11, "RR": 14, "SC": 42, "SP": 35, "SE": 28, "TO": 17}
_cache_municipios = {}


def resolver_ibge(c):
    if c.get("ibge"):
        return True
    uf = c["uf"]
    if uf not in _cache_municipios:
        url = (f"https://servicodados.ibge.gov.br/api/v1/localidades/"
               f"estados/{UF_COD.get(uf, uf)}/municipios")
        for t in range(3):
            try:
                r = requests.get(url, timeout=TIMEOUT, headers=UA)
                r.raise_for_status()
                _cache_municipios[uf] = {slug(m["nome"]): str(m["id"])
                                         for m in r.json()}
                break
            except Exception as e:
                print(f"[{c['nome']}] localidades tentativa {t+1}: {e}", file=sys.stderr)
                time.sleep(4 * (t + 1))
        if uf not in _cache_municipios:
            return False
    cod = _cache_municipios[uf].get(slug(c["nome"]))
    if cod:
        c["ibge"] = cod
        return True
    print(f"[{c['nome']}] não encontrado na base do IBGE", file=sys.stderr)
    return False


# Teto de vereadores — art. 29, IV da CF (EC 58/2009)
_TETO_VEREADORES = [
    (15_000, 9), (30_000, 11), (50_000, 13), (80_000, 15), (120_000, 17),
    (160_000, 19), (300_000, 21), (450_000, 23), (600_000, 25), (750_000, 27),
    (900_000, 29), (1_050_000, 31), (1_200_000, 33), (1_350_000, 35),
    (1_500_000, 37), (1_800_000, 39), (2_400_000, 41), (3_000_000, 43),
    (4_000_000, 45), (5_000_000, 47), (6_000_000, 49), (7_000_000, 51),
    (8_000_000, 53),
]


def vereadores_teto(pop):
    for lim, n in _TETO_VEREADORES:
        if pop <= lim:
            return n
    return 55


def limite_art_29a(pop):
    if pop <= 100_000:
        return 0.07
    if pop <= 300_000:
        return 0.06
    if pop <= 500_000:
        return 0.05
    if pop <= 3_000_000:
        return 0.045
    if pop <= 8_000_000:
        return 0.04
    return 0.035


# ═════════════════ NLP ESTÁGIO 1 (regras de alta precisão) ═════════════════
PADROES_SIMBOLICA = [re.compile(p, re.I) for p in [
    r"\bden[oô]mina", r"\bpassa a denominar", r"\bd[áa] o nome\b",
    r"\bmo[çc][ãa]o de (aplauso|congratula|pesar|rep[úu]dio|louvor|apoio)",
    r"\bvoto de (congratula|pesar|louvor)",
    r"\binstitui\b.{0,40}\b(dia|semana|m[êe]s)\b.{0,30}\b(municipal|no calend)",
    r"\bt[íi]tulo de cidad[ãa]", r"\bhonra ao m[ée]rito", r"\bcomenda\b",
    r"\bhomenagem\b", r"\bdata comemorativa\b",
]]
TEMAS_RX = {
    "Saúde": r"sa[úu]de|\bsus\b|ubs\b|vacin|hospital|m[ée]dic|farm[áa]c",
    "Educação": r"educa|escola|ensino|creche|professor|merenda|alfabetiza",
    "Saneamento": r"saneamento|esgoto|[áa]gua pot|res[íi]duo|drenagem|lixo",
    "Mobilidade": r"tr[âa]nsito|transporte|ciclovia|pavimenta|mobilidade|estrada",
    "Assistência": r"assist[êe]ncia social|vulnerab|crian[çc]a|idoso|mulher|pcd\b",
    "Meio ambiente": r"ambient|arboriza|clim[áa]|polui|sustentab",
    "Segurança": r"seguran[çc]a|guarda municipal|monitoramento|ilumina[çc][ãa]o p",
    "Tributário": r"\biptu\b|\biss\b|\btaxa\b|tribut|isen[çc]",
    "Administração": r"\bcargo|servidor|estrutura administrativa|plano de carreira|subs[íi]dio",
}
TIPOS_ESTRUTURAIS = ("projeto de lei", "emenda", "substitutivo", "projeto de lei complementar")
TIPOS_REGULATORIOS = ("requerimento", "projeto de resolu", "projeto de decreto")


# Padrões de ementa — usados quando o tipo não vem preenchido (portais que
# agrupam por aba). A redação legislativa brasileira é formulaica, o que
# permite alta precisão sem modelo treinado.
RX_EMENTA_PEDIDO = re.compile(
    r"^\s*(solicita|solicito|requer|reitera|indica|sugere|pede)\b|"
    r"\bao (senhor |exmo|excelent)?.{0,25}(chefe do )?executivo\b|"
    r"\bao (senhor |exmo\.? sr\.? )?prefeito\b|"
    r"\bprovidenci|\bestudar a (possibilidade|viabilidade)|"
    r"\bde informa[çc][õo]es\b", re.I)
RX_EMENTA_ESTRUTURAL = re.compile(
    r"^\s*(institui|disp[õo]e sobre|cria|altera a lei|altera o|acrescenta|"
    r"revoga|estabelece|autoriza o poder|fixa|estima a receita|"
    r"emenda ao projeto|substitutivo ao projeto|projeto de lei)\b|"
    r"\bemenda ao projeto de lei\b|\bsubstitutivo\b", re.I)
RX_EMENTA_FISCALIZATORIA = re.compile(
    r"\bconvoca[çc][ãa]o\b|\bcomiss[ãa]o (especial|processante|de inqu[ée]rito)\b|"
    r"\baprova as contas\b|\brejeita as contas\b|\bparecer pr[ée]vio\b|"
    r"\bpresta[çc][ãa]o de contas\b|\baudi[êe]ncia p[úu]blica\b", re.I)


def classificar_materia(ementa, tipo_nome):
    """Classe (ESTRUTURAL 1,0 / REGULATORIA 0,6 / SIMBOLICA 0,0) + tema.

    Estágio 1: regras de alta precisão. Usa o tipo declarado quando existe;
    quando o portal não informa o tipo, infere pela redação da ementa —
    pedidos ao Executivo (indicações/requerimentos de providência) não
    criam norma e por isso não contam como produção estrutural.
    """
    e, t = ementa or "", norm(tipo_nome)
    tema = next((nome for nome, rx in TEMAS_RX.items() if re.search(rx, e, re.I)), None)

    # 1. Simbólicas (homenagens, moções, denominações) — pelo texto ou pelo tipo
    if any(rx.search(e) for rx in PADROES_SIMBOLICA) or \
       any(x in t for x in ("moc", "voto de", "homenagem", "pesar", "congratula")):
        return "SIMBOLICA", None, 0.0

    # 2. Tipo declarado tem prioridade
    if t:
        if "indica" in t:
            return "SIMBOLICA", tema, 0.0
        if any(x in t for x in TIPOS_ESTRUTURAIS):
            return "ESTRUTURAL", tema, 1.0
        if any(x in t for x in TIPOS_REGULATORIOS):
            return "REGULATORIA", tema, 0.6

    # 3. Sem tipo: inferir pela redação da ementa
    if RX_EMENTA_ESTRUTURAL.search(e):
        return "ESTRUTURAL", tema, 1.0
    if RX_EMENTA_FISCALIZATORIA.search(e):
        return "REGULATORIA", tema, 0.6
    if RX_EMENTA_PEDIDO.search(e):
        # Pedido ao Executivo: não cria norma. Vale como representação
        # do eleitor, mas com peso baixo na régua de produção legislativa.
        return "SIMBOLICA", tema, 0.0
    return "REGULATORIA", tema, 0.6


def entropia_norm(contagens):
    total = sum(contagens.values())
    if total == 0 or len(contagens) < 2:
        return 0.0
    h = -sum((q / total) * math.log(q / total) for q in contagens.values() if q)
    return h / math.log(len(TEMAS_RX))


DIAGNOSTICO = []


def diag(cidade, etapa, info):
    DIAGNOSTICO.append({"cidade": cidade, "etapa": etapa, "info": info})


# ═════════════════ COLETAS ═════════════════
def descobrir_sapl(c):
    """Sonda o padrão Interlegis sapl.<cidade>.<uf>.leg.br para cidades
    sem SAPL configurado. Ativa somente se a API responder com matérias."""
    if c.get("sapl") or c.get("sapl_sondado"):
        return
    c["sapl_sondado"] = True
    base = f"https://sapl.{slug(c['nome'])}.{c['uf'].lower()}.leg.br"
    try:
        r = requests.get(f"{base}/api/materia/materialegislativa/?page_size=1",
                         timeout=12, headers=UA)
        if r.status_code == 200 and isinstance(r.json().get("results"), list):
            c["sapl"] = base
            print(f"[{c['nome']}] SAPL descoberto automaticamente: {base}")
    except Exception:
        pass


def coletar_populacao(c):
    url = ("https://servicodados.ibge.gov.br/api/v3/agregados/6579/"
           f"periodos/-1/variaveis/9324?localidades=N6[{c['ibge']}]")
    for t in range(5):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            if r.status_code in (429, 503):
                raise RuntimeError(f"limite de chamadas ({r.status_code})")
            r.raise_for_status()
            serie = r.json()[0]["resultados"][0]["series"][0]["serie"]
            ano, valor = sorted(serie.items())[-1]
            return bloco(int(valor), f"IBGE — Estimativas de População ({ano})",
                         url, "verificada")
        except Exception as e:
            print(f"[{c['nome']}] IBGE pop tentativa {t+1}: {e}", file=sys.stderr)
            time.sleep(5 * (t + 1))
    return bloco(demo_fin(c)[0], "IBGE", url, "demo")


def _rreo_valor(itens, cod, padrao):
    for i in itens:
        if i.get("cod_conta") == cod and padrao in (i.get("coluna") or "").upper():
            return i.get("valor")
    return None


def coletar_rreo(c):
    ano_atual = datetime.now().year
    tentativas = [(ano_atual, p) for p in range(6, 0, -1)] + \
                 [(ano_atual - 1, p) for p in range(6, 0, -1)]
    for ano, periodo in tentativas:
        url = (f"{SICONFI}/rreo?an_exercicio={ano}&nr_periodo={periodo}"
               f"&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2001&id_ente={c['ibge']}")
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            itens = r.json().get("items", [])
            if not itens:
                continue
            rc = _rreo_valor(itens, "ReceitasCorrentes", "ATÉ O BIMESTRE")
            dt = _rreo_valor(itens, "TotalDespesas", "LIQUIDADAS ATÉ O BIMESTRE") or \
                _rreo_valor(itens, "TotalDespesas", "ATÉ O BIMESTRE")
            inv = _rreo_valor(itens, "Investimentos", "LIQUIDADAS ATÉ O BIMESTRE") or \
                _rreo_valor(itens, "Investimentos", "ATÉ O BIMESTRE")
            trib = _rreo_valor(itens, "ReceitaTributaria", "ATÉ O BIMESTRE") or 0
            transf = _rreo_valor(itens, "TransferenciasCorrentes", "ATÉ O BIMESTRE") or 0
            base = (trib + transf) or None
            if rc:
                det = f"RREO Anexo 01, {periodo}º bimestre {ano}"
                d = demo_fin(c)
                inv_b = (bloco(inv, "SICONFI/RREO", url, "verificada", det)
                         if inv is not None else
                         (_dca_investimentos(c) or bloco(None, "SICONFI", url, "demo")))
                return {
                    "receita": bloco(rc, "SICONFI/RREO", url, "verificada", det),
                    "despesa": bloco(dt or d[2], "SICONFI/RREO", url,
                                     "verificada" if dt else "demo", det),
                    "investimentos": inv_b,
                    "base29a": bloco(base or d[3],
                                     "SICONFI/RREO (base aprox. art. 29-A)", url,
                                     "verificada" if base else "demo",
                                     "Aproximação: tributária + transferências correntes"),
                }
        except Exception:
            pass
    dca = coletar_dca_anual(c)
    if dca:
        return dca
    d = demo_fin(c)
    print(f"[{c['nome']}] RREO e DCA indisponíveis — demo", file=sys.stderr)
    return {"receita": bloco(d[1], "SICONFI", SICONFI, "demo"),
            "despesa": bloco(d[2], "SICONFI", SICONFI, "demo"),
            "investimentos": bloco(None, "SICONFI", SICONFI, "demo"),
            "base29a": bloco(d[3], "SICONFI", SICONFI, "demo")}


def _dca_investimentos(c):
    """Investimentos do último exercício encerrado (DCA Anexo I-D)."""
    ano_atual = datetime.now().year
    for ano in (ano_atual - 1, ano_atual - 2):
        url = f"{SICONFI}/dca?an_exercicio={ano}&no_anexo=DCA-Anexo%20I-D&id_ente={c['ibge']}"
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            inv = None
            for i in r.json().get("items", []):
                conta = (i.get("conta") or "").lower()
                col = (i.get("coluna") or "").lower()
                if "investimento" in conta and "liquidad" in col:
                    v = i.get("valor")
                    if v is not None:
                        inv = max(inv or 0, v)
            if inv:
                return bloco(inv, "SICONFI/DCA — Investimentos", url,
                             "verificada", f"Exercício {ano}")
        except Exception:
            pass
    return None


def coletar_dca_anual(c):
    ano_atual = datetime.now().year
    for ano in (ano_atual - 1, ano_atual - 2):
        try:
            rec = desp = trib = transf = None
            url_c = f"{SICONFI}/dca?an_exercicio={ano}&no_anexo=DCA-Anexo%20I-C&id_ente={c['ibge']}"
            r = requests.get(url_c, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            for i in r.json().get("items", []):
                conta = (i.get("conta") or "").lower()
                col = (i.get("coluna") or "").lower()
                if "realizad" not in col and "receitas brutas" not in col:
                    continue
                v = i.get("valor")
                if v is None:
                    continue
                if "receitas correntes" in conta and "intra" not in conta:
                    rec = max(rec or 0, v)
                if conta.startswith("1.1") and "impostos" in conta:
                    trib = max(trib or 0, v)
                if "transferências correntes" in conta:
                    transf = max(transf or 0, v)
            url_d = f"{SICONFI}/dca?an_exercicio={ano}&no_anexo=DCA-Anexo%20I-D&id_ente={c['ibge']}"
            r = requests.get(url_d, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            for i in r.json().get("items", []):
                conta = (i.get("conta") or "").lower()
                col = (i.get("coluna") or "").lower()
                if "liquidad" in col and ("despesas correntes" in conta or "total" in conta):
                    v = i.get("valor")
                    if v is not None:
                        desp = max(desp or 0, v)
            if rec:
                det = f"DCA — contas anuais, exercício {ano}"
                d = demo_fin(c)
                base = ((trib or 0) + (transf or 0)) or None
                return {"receita": bloco(rec, "SICONFI/DCA", url_c, "verificada", det),
                        "despesa": bloco(desp or d[2], "SICONFI/DCA", url_d,
                                         "verificada" if desp else "demo", det),
                        "investimentos": (_dca_investimentos(c)
                                          or bloco(None, "SICONFI/DCA", url_d, "demo")),
                        "base29a": bloco(base or d[3],
                                         "SICONFI/DCA (base aprox. art. 29-A)", url_c,
                                         "verificada" if base else "demo",
                                         "Aproximação: impostos + transferências correntes")}
        except Exception as e:
            print(f"[{c['nome']}] DCA anual {ano} falhou: {e}", file=sys.stderr)
    return None


def coletar_rgf_pessoal(c, poder):
    """Despesa Total com Pessoal em % da RCL (RGF Anexo 01).

    Robusto porque o SICONFI varia bastante: municípios pequenos entregam
    semestralmente, o rótulo da conta muda entre versões do layout e nem
    sempre há coluna com o percentual — nesse caso calculamos DTP/RCL a
    partir dos valores absolutos do próprio anexo.
    """
    ano_atual = datetime.now().year
    tentativas = []
    for ano in (ano_atual, ano_atual - 1, ano_atual - 2):
        for p in (3, 2, 1):
            tentativas.append((ano, "Q", p))
        for p in (2, 1):
            tentativas.append((ano, "S", p))
    rotulo = "Executivo" if poder == "E" else "Legislativo"

    def extrai(itens):
        dtp = rcl = pct = None
        for i in itens:
            conta = norm(i.get("conta") or "")
            cod = norm(i.get("cod_conta") or "")
            col = norm(i.get("coluna") or "")
            v = i.get("valor")
            if v is None:
                continue
            eh_dtp = ("despesa total com pessoal" in conta or
                      "despesatotalcompessoal" in cod.replace(" ", "") or
                      conta.startswith("dtp"))
            eh_rcl = ("receita corrente liquida" in conta or
                      "receitacorrenteliquida" in cod.replace(" ", ""))
            if eh_dtp:
                if "%" in col or "percentual" in col or "sobre a rcl" in col:
                    pct = pct if pct is not None else float(v)
                elif "despesas liquidadas" in col or "valor" in col or col == "":
                    dtp = dtp if dtp is not None else float(v)
            if eh_rcl and rcl is None:
                rcl = float(v)
        if pct is not None and 0 < pct <= 100:
            return pct / 100.0
        if dtp and rcl and rcl > 0:
            return dtp / rcl
        return None

    for ano, perc, periodo in tentativas:
        url = (f"{SICONFI}/rgf?an_exercicio={ano}&in_periodicidade={perc}"
               f"&nr_periodo={periodo}&co_tipo_demonstrativo=RGF"
               f"&no_anexo=RGF-Anexo%2001&co_esfera=M&co_poder={poder}"
               f"&id_ente={c['ibge']}")
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            itens = r.json().get("items", [])
            if not itens:
                continue
            val = extrai(itens)
            if val is not None:
                per_txt = "quadrimestre" if perc == "Q" else "semestre"
                return bloco(val, f"SICONFI/RGF — {rotulo}", url, "verificada",
                             f"{periodo}º {per_txt} de {ano} (% da RCL)")
            diag(c["nome"], f"rgf_{poder}_sem_dtp",
                 f"{ano}/{perc}{periodo}: {len(itens)} itens, contas="
                 f"{sorted({(i.get('conta') or '')[:45] for i in itens})[:6]}")
        except Exception as e:
            diag(c["nome"], f"rgf_{poder}_erro", f"{ano}/{perc}{periodo}: {str(e)[:80]}")
    return bloco(None, f"SICONFI/RGF — {rotulo}", SICONFI, "demo",
                 "RGF não localizado no SICONFI para os períodos consultados")


def folha_legislativo_dca(c):
    """Plano B para a folha da Câmara: pessoal e encargos da função
    Legislativa no DCA, comparado ao repasse (art. 29-A, §1º: máx. 70%)."""
    ano_atual = datetime.now().year
    for ano in (ano_atual - 1, ano_atual - 2):
        url = (f"{SICONFI}/dca?an_exercicio={ano}"
               f"&no_anexo=DCA-Anexo%20I-E&id_ente={c['ibge']}")
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            pessoal = None
            for i in r.json().get("items", []):
                conta = norm(i.get("conta") or "")
                col = norm(i.get("coluna") or "")
                if "legislativa" not in conta:
                    continue
                if "pessoal" in conta and "liquidad" in col:
                    v = i.get("valor")
                    if v is not None:
                        pessoal = max(pessoal or 0, float(v))
            if pessoal:
                b = bloco(pessoal, "SICONFI/DCA — pessoal da função Legislativa",
                          url, "verificada", f"Exercício {ano}")
                b["exercicio"] = ano
                return b
        except Exception:
            pass
    return None


def coletar_custo_camara(c):
    ano_atual = datetime.now().year
    for ano in (ano_atual - 1, ano_atual - 2):
        url = f"{SICONFI}/dca?an_exercicio={ano}&no_anexo=DCA-Anexo%20I-E&id_ente={c['ibge']}"
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            for i in r.json().get("items", []):
                if "legislativa" in (i.get("conta") or "").lower() and \
                   "liquidada" in (i.get("coluna") or "").lower():
                    v = i.get("valor")
                    if v:
                        b = bloco(v, "SICONFI/DCA — função 01 Legislativa",
                                  url, "verificada", f"Exercício {ano}")
                        b["exercicio"] = ano
                        return b
        except Exception:
            pass
    b = bloco(demo_fin(c)[4], "SICONFI/DCA", SICONFI, "demo")
    b["exercicio"] = None
    return b


def coletar_base29a(c, exercicio):
    """Base do art. 29-A no EXERCÍCIO pedido (mesmo ano do custo da Câmara).

    A CF manda usar a receita tributária + transferências do exercício
    ANTERIOR ao do repasse; portanto, para um custo do exercício X,
    a base correta é a do exercício X-1. Fonte: DCA Anexo I-C (ano fechado).
    """
    if not exercicio:
        return None
    ano_base = exercicio - 1
    url = f"{SICONFI}/dca?an_exercicio={ano_base}&no_anexo=DCA-Anexo%20I-C&id_ente={c['ibge']}"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        trib = transf = None
        for i in r.json().get("items", []):
            conta = (i.get("conta") or "").lower()
            col = (i.get("coluna") or "").lower()
            if "realizad" not in col and "receitas brutas" not in col:
                continue
            v = i.get("valor")
            if v is None:
                continue
            if "impostos, taxas e contribuições de melhoria" in conta or \
               (conta.startswith("1.1") and "impostos" in conta):
                trib = max(trib or 0, v)
            if "transferências correntes" in conta and "intra" not in conta:
                transf = max(transf or 0, v)
        base = (trib or 0) + (transf or 0)
        if base:
            b = bloco(base, "SICONFI/DCA — base do art. 29-A", url, "verificada",
                      f"Exercício {ano_base} (base legal do repasse de {exercicio})")
            b["exercicio"] = ano_base
            return b
    except Exception as e:
        print(f"[{c['nome']}] base 29-A {ano_base} falhou: {e}", file=sys.stderr)
    return None


def _sapl_paginar(url_base, max_paginas=20):
    itens, url = [], url_base
    for _ in range(max_paginas):
        r = requests.get(url, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        j = r.json()
        itens.extend(j.get("results", []))
        url = j.get("next") or (j.get("pagination") or {}).get("links", {}).get("next")
        if not url:
            break
    return itens


def proposicoes_do_csv(c):
    """Distribuição de classes a partir do CSV curado, quando existir."""
    import csv as _csv
    import os
    caminho = f"docs/dados-manuais/{slug(c['nome'])}-{c['uf'].lower()}.csv"
    if not os.path.exists(caminho):
        return None
    periodo = c.get("periodo_proposituras")
    if periodo:
        d0 = datetime.strptime(periodo[0], "%d/%m/%Y")
        d1 = datetime.strptime(periodo[1], "%d/%m/%Y")
        rotulo = f"{periodo[0]} a {periodo[1]}"
    else:
        ano = int(c.get("ano_exercicio") or datetime.now().year - 1)
        d0, d1 = datetime(ano, 1, 1), datetime(ano, 12, 31)
        rotulo = f"exercício {ano}"
    classes = {"ESTRUTURAL": 0, "REGULATORIA": 0, "SIMBOLICA": 0}
    temas, tipos = {}, {}
    soma, total = 0.0, 0
    try:
        with open(caminho, encoding="utf-8-sig") as fh:
            for row in _csv.DictReader(fh, delimiter=";"):
                try:
                    dt_ = datetime.strptime((row.get("data") or "")[:10], "%d/%m/%Y")
                except ValueError:
                    continue
                if not (d0 <= dt_ <= d1):
                    continue
                cls, tema, peso = classificar_materia(row.get("ementa", ""),
                                                      row.get("tipo", ""))
                classes[cls] += 1
                soma += peso
                total += 1
                if tema and cls != "SIMBOLICA":
                    temas[tema] = temas.get(tema, 0) + 1
                rot = {"ESTRUTURAL": "Projetos, emendas e substitutivos",
                       "REGULATORIA": "Requerimentos e fiscalização",
                       "SIMBOLICA": "Indicações, moções e homenagens"}[cls]
                tipos[rot] = tipos.get(rot, 0) + 1
    except Exception as e:
        print(f"[{c['nome']}] CSV proposições falhou: {e}", file=sys.stderr)
        return None
    if not total:
        return None
    lista = [{"tipo": t, "qtd": q,
              "peso": "alta" if t.startswith("Projetos") else
                      "media" if t.startswith("Requer") else "baixa"}
             for t, q in sorted(tipos.items(), key=lambda x: -x[1])]
    print(f"[{c['nome']}] proposições do CSV: {total} ({rotulo})")
    return bloco({"tipos": lista, "classes": classes, "temas": temas,
                  "peso_medio": soma / total, "total": total,
                  "cobertura": "completa"},
                 "Portal oficial da Câmara (extração conferida) — classificação NLP",
                 c.get("siscam") or "#", "verificada",
                 f"Período {rotulo} · {total} proposituras, incluindo indicações")


def coletar_proposicoes(c):
    """Tipos + classificação NLP estágio 1 sobre as ementas."""
    do_csv = proposicoes_do_csv(c)
    if do_csv:
        return do_csv
    sapl = c.get("sapl")
    if not sapl:
        classes = {"ESTRUTURAL": 0, "REGULATORIA": 0, "SIMBOLICA": 0}
        soma_peso = 0.0
        for p in DEMO_PROPS:
            cls = {"alta": "ESTRUTURAL", "media": "REGULATORIA", "baixa": "SIMBOLICA"}[p["peso"]]
            classes[cls] += p["qtd"]
            soma_peso += {"alta": 1.0, "media": 0.6, "baixa": 0.0}[p["peso"]] * p["qtd"]
        total = sum(x["qtd"] for x in DEMO_PROPS)
        return bloco({"tipos": DEMO_PROPS, "classes": classes, "temas": {},
                      "peso_medio": soma_peso / total, "total": total},
                     "Portal da Câmara — sistema próprio, conector em desenvolvimento",
                     f"https://www.{slug(c['nome'])}.{c['uf'].lower()}.leg.br", "demo",
                     "Esta Câmara não usa o SAPL; a integração é a próxima etapa.")
    ano = datetime.now().year
    for a in (ano, ano - 1):
        try:
            tipos = {t["id"]: t.get("descricao") or t.get("sigla", "")
                     for t in _sapl_paginar(f"{sapl}/api/materia/tipomaterialegislativa/?page_size=100", 5)}
            mats = _sapl_paginar(f"{sapl}/api/materia/materialegislativa/?ano={a}&page_size=100")
            if not mats:
                continue
            cont_tipos, classes, temas = {}, {"ESTRUTURAL": 0, "REGULATORIA": 0, "SIMBOLICA": 0}, {}
            soma_peso = 0.0
            for m in mats:
                t = m.get("tipo")
                nome_tipo = tipos.get(t, str(t)) if not isinstance(t, dict) else t.get("descricao", "")
                cont_tipos[nome_tipo] = cont_tipos.get(nome_tipo, 0) + 1
                cls, tema, peso = classificar_materia(m.get("ementa", ""), nome_tipo)
                classes[cls] += 1
                soma_peso += peso
                if tema:
                    temas[tema] = temas.get(tema, 0) + 1
            lista = [{"tipo": t, "qtd": q,
                      "peso": "alta" if any(x in norm(t) for x in TIPOS_ESTRUTURAIS)
                      else "baixa" if classes else "media"}
                     for t, q in sorted(cont_tipos.items(), key=lambda x: -x[1])]
            print(f"[{c['nome']}] SAPL: {len(mats)} matérias {a} | "
                  f"E={classes['ESTRUTURAL']} R={classes['REGULATORIA']} S={classes['SIMBOLICA']}")
            # Um portal que publica só projetos de lei parece "mais produtivo"
            # que outro que publica também indicações. Marcamos a cobertura
            # para não premiar a opacidade na comparação entre cidades.
            frac_simb = classes["SIMBOLICA"] / len(mats)
            cobertura = "completa" if frac_simb >= 0.25 else "parcial"
            return bloco({"tipos": lista, "classes": classes, "temas": temas,
                          "peso_medio": soma_peso / len(mats), "total": len(mats),
                          "cobertura": cobertura},
                         "SAPL — Câmara Municipal (classificação NLP estágio 1)",
                         f"{sapl}/materia/pesquisar-materia?ano={a}", "verificada", f"Ano {a}")
        except Exception as e:
            print(f"[{c['nome']}] SAPL matérias {a}: {e}", file=sys.stderr)
    return coletar_proposicoes({**c, "sapl": None})


_robots_cache = {}


def robots_permite(url, ua="FiscalizaOsMunicipios"):
    """Consulta o robots.txt do domínio e diz se o caminho é permitido.
    Em caso de erro de rede, assume NÃO permitido (postura conservadora)."""
    from urllib.parse import urlparse
    from urllib import robotparser
    p = urlparse(url)
    raiz = f"{p.scheme}://{p.netloc}"
    if raiz not in _robots_cache:
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{raiz}/robots.txt")
        try:
            rp.read()
            _robots_cache[raiz] = rp
        except Exception as e:
            print(f"[robots] {raiz} ilegível ({e}) — assumindo bloqueio", file=sys.stderr)
            _robots_cache[raiz] = None
    rp = _robots_cache[raiz]
    if rp is None:
        return False
    return rp.can_fetch(ua, url) and rp.can_fetch("*", url)


RX_VEREADOR = re.compile(r'/Vereadores/Proposituras/(\d+)"[^>]*>\s*([^<]{3,80}?)\s*<', re.I)
RX_PROPOSITURA = re.compile(
    r"N[ºo°]\s*([\w/\s]+?)\s*-\s*(\d{2}/\d{2}/(\d{4}))\s*-\s*([^<\n]{10,400})", re.I)


def coletar_siscam(c):
    """Conector automático para Câmaras no SisCam.

    Só executa se o robots.txt do portal autorizar. Ritmo lento
    (1 requisição a cada 2s), User-Agent identificado, 1x por dia.
    """
    base = c.get("siscam")
    if not base:
        return None
    lista_url = f"{base}/Vereadores"
    if not robots_permite(lista_url):
        print(f"[{c['nome']}] SisCam: robots.txt do portal não autoriza coleta "
              f"automatizada — usando CSV curado, se houver", file=sys.stderr)
        diag(c["nome"], "siscam_robots", "bloqueado")
        return None
    ano_alvo = str(c.get("ano_exercicio") or datetime.now().year - 1)
    ua = {"User-Agent": ("FiscalizaOsMunicipios/2.0 (projeto civico de transparencia; "
                         "fiscalizaosmunicipios.com.br; coleta diaria de dados publicos - LAI)")}
    try:
        r = requests.get(lista_url, timeout=TIMEOUT, headers=ua)
        r.raise_for_status()
        vereadores = {}
        for vid, nome in RX_VEREADOR.findall(r.text):
            nome = " ".join(nome.split())
            if nome and vid not in vereadores:
                vereadores[vid] = nome
        diag(c["nome"], "siscam_vereadores_listados", len(vereadores))
        if not vereadores:
            return None
        agg, total = {}, 0
        for vid, nome in vereadores.items():
            url_v = f"{base}/Vereadores/Proposituras/{vid}"
            if not robots_permite(url_v):
                continue
            time.sleep(2)  # ritmo respeitoso
            try:
                rv = requests.get(url_v, timeout=TIMEOUT, headers=ua)
                rv.raise_for_status()
            except Exception as e:
                print(f"[{c['nome']}] SisCam vereador {vid}: {e}", file=sys.stderr)
                continue
            html = re.sub(r"<[^>]+>", "\n", rv.text)
            for num, data, ano, ementa in RX_PROPOSITURA.findall(html):
                if ano != ano_alvo:
                    continue
                tipo = num if not num.strip().isdigit() else ""
                cls, _, _ = classificar_materia(ementa, tipo)
                chave = {"ESTRUTURAL": "alta", "REGULATORIA": "media",
                         "SIMBOLICA": "baixa"}[cls]
                v = agg.setdefault(vid, {"nome": nome, "alta": 0, "media": 0,
                                         "baixa": 0, "total": 0, "link": url_v})
                v[chave] += 1
                v["total"] += 1
                total += 1
        diag(c["nome"], "siscam_proposituras_ano", total)
        if not agg:
            return None
        lista = sorted(agg.values(), key=lambda v: (-v["alta"], -v["total"]))
        print(f"[{c['nome']}] SisCam: {total} proposituras de {ano_alvo}, "
              f"{len(lista)} vereadores")
        return bloco(lista, "SisCam — portal oficial da Câmara Municipal",
                     lista_url, "verificada",
                     f"Exercício {ano_alvo} · {total} proposituras coletadas")
    except Exception as e:
        print(f"[{c['nome']}] SisCam falhou: {e}", file=sys.stderr)
        diag(c["nome"], "siscam_erro", str(e)[:200])
        return None


def carregar_producao_manual(c):
    """Lê proposituras curadas à mão em docs/dados-manuais/<slug>-<uf>.csv.

    Formato (cabeçalho obrigatório):
        vereador;tipo;numero;data;ementa;url

    Serve para Câmaras cujo sistema não expõe API e cujo portal não
    autoriza coleta automatizada: o dado é público, mas a extração é
    feita por pessoa, com link de conferência em cada linha.
    """
    import csv
    import os
    caminho = f"docs/dados-manuais/{slug(c['nome'])}-{c['uf'].lower()}.csv"
    if not os.path.exists(caminho):
        return None
    periodo = c.get("periodo_proposituras")  # ("01/01/2025", "09/09/2026")
    if periodo:
        d0 = datetime.strptime(periodo[0], "%d/%m/%Y")
        d1 = datetime.strptime(periodo[1], "%d/%m/%Y")
        rotulo = f"{periodo[0]} a {periodo[1]}"
    else:
        ano = int(c.get("ano_exercicio") or datetime.now().year - 1)
        d0, d1 = datetime(ano, 1, 1), datetime(ano, 12, 31)
        rotulo = f"exercício {ano}"
    agg, total = {}, 0
    try:
        with open(caminho, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                data = (row.get("data") or "").strip()
                try:
                    dt_ = datetime.strptime(data[:10], "%d/%m/%Y")
                except ValueError:
                    continue
                if not (d0 <= dt_ <= d1):
                    continue
                nome = (row.get("vereador") or "").strip()
                if not nome:
                    continue
                cls, _, _ = classificar_materia(row.get("ementa", ""),
                                                row.get("tipo", ""))
                chave = {"ESTRUTURAL": "alta", "REGULATORIA": "media",
                         "SIMBOLICA": "baixa"}[cls]
                v = agg.setdefault(nome, {"nome": nome, "alta": 0, "media": 0,
                                          "baixa": 0, "total": 0,
                                          "link": (row.get("url") or "").strip()})
                v[chave] += 1
                v["total"] += 1
                total += 1
    except Exception as e:
        print(f"[{c['nome']}] CSV manual falhou: {e}", file=sys.stderr)
        return None
    if not agg:
        return None
    lista = sorted(agg.values(), key=lambda v: (-v["alta"], -v["total"]))
    print(f"[{c['nome']}] produção curada: {total} proposituras ({rotulo}), "
          f"{len(lista)} vereadores")
    return bloco(lista, "SisCam — portal oficial da Câmara (extração conferida)",
                 c.get("siscam") or c.get("fontes_extra", [("", "#")])[0][1],
                 "verificada",
                 f"Período {rotulo} · {total} proposituras · cada vereador tem "
                 f"link para sua página oficial de proposituras")


def coletar_producao_vereadores(c):
    auto = coletar_siscam(c)
    if auto:
        return auto
    manual = carregar_producao_manual(c)
    if manual:
        return manual
    sapl = c.get("sapl")
    if not sapl:
        return bloco([], "Portal da Câmara — sem API de autoria",
                     f"https://www.{slug(c['nome'])}.{c['uf'].lower()}.leg.br", "demo",
                     "Nomes de vereadores só são publicados com fonte oficial verificável.")
    ano = datetime.now().year
    for a in (ano, ano - 1):
        try:
            parls = _sapl_paginar(f"{sapl}/api/parlamentar/parlamentar/?page_size=100", 5)
            nomes_parl = {p.get("nome_parlamentar") or p.get("nome_completo", "") for p in parls}
            autores = {x["id"]: x.get("nome", "")
                       for x in _sapl_paginar(f"{sapl}/api/base/autor/?page_size=100", 10)}
            tipos = {t["id"]: t.get("descricao") or t.get("sigla", "")
                     for t in _sapl_paginar(f"{sapl}/api/materia/tipomaterialegislativa/?page_size=100", 5)}
            mats = _sapl_paginar(f"{sapl}/api/materia/materialegislativa/?ano={a}&page_size=100")
            if not mats:
                continue
            parl_norm = {norm(x) for x in nomes_parl if x}

            def eh_parl(nome):
                n = norm(nome)
                return bool(n) and (n in parl_norm or
                                    any(p and (p in n or n in p) for p in parl_norm))

            NAO_PARL = ("prefeit", "executivo", "comiss", "mesa", "camara municipal",
                        "secretar", "poder", "procurador")

            # Muitas versões do SAPL não embutem "autores" na matéria:
            # a autoria vive em /api/materia/autoria/ (materia ↔ autor)
            amostra = mats[0] if mats else {}
            diag(c["nome"], "materia_keys", sorted(amostra.keys())[:40])
            diag(c["nome"], "materia_autores_exemplo", str(amostra.get("autores"))[:200])
            diag(c["nome"], "n_parlamentares", len(parls))
            diag(c["nome"], "n_autores_cadastro", len(autores))
            tem_campo_autores = any(m.get("autores") for m in mats)
            mapa_autoria = {}
            if not tem_campo_autores:
                ids_ano = {m.get("id") for m in mats}
                regs = []
                try:
                    regs = _sapl_paginar(
                        f"{sapl}/api/materia/autoria/?materia__ano={a}&page_size=100", 30)
                except Exception:
                    try:
                        regs = _sapl_paginar(f"{sapl}/api/materia/autoria/?page_size=100", 40)
                    except Exception as e:
                        print(f"[{c['nome']}] endpoint de autoria falhou: {e}", file=sys.stderr)
                diag(c["nome"], "n_regs_autoria", len(regs))
                if regs:
                    diag(c["nome"], "autoria_keys", sorted(regs[0].keys())[:30])
                    diag(c["nome"], "autoria_exemplo", str(regs[0])[:300])
                for reg in regs:
                    mid = reg.get("materia") or reg.get("materia_id") or \
                        (reg.get("materia", {}) or {}).get("id") if isinstance(reg.get("materia"), dict) else reg.get("materia")
                    aut = reg.get("autor")
                    if isinstance(aut, dict):
                        aut = aut.get("id")
                    if mid in ids_ano:
                        mapa_autoria.setdefault(mid, []).append(aut)
                diag(c["nome"], "materias_com_autoria_mapeada", len(mapa_autoria))

            def autores_da(m):
                return m.get("autores") or mapa_autoria.get(m.get("id")) or []

            def monta(filtro):
                agg = {}
                for m in mats:
                    t = m.get("tipo")
                    nome_tipo = tipos.get(t, str(t)) if not isinstance(t, dict) else t.get("descricao", "")
                    cls, _, _ = classificar_materia(m.get("ementa", ""), nome_tipo)
                    chave = {"ESTRUTURAL": "alta", "REGULATORIA": "media", "SIMBOLICA": "baixa"}[cls]
                    for aid in autores_da(m):
                        nome = autores.get(aid, "")
                        if not filtro(nome):
                            continue
                        v = agg.setdefault(aid, {"nome": nome, "alta": 0, "media": 0,
                                                 "baixa": 0, "total": 0})
                        v[chave] += 1
                        v["total"] += 1
                return agg

            agg = monta(eh_parl)
            diag(c["nome"], "agg_filtro_parlamentar", len(agg))
            if not agg:
                agg = monta(lambda nome: nome and not any(x in norm(nome) for x in NAO_PARL))
                diag(c["nome"], "agg_filtro_orgaos", len(agg))
            if not agg:
                diag(c["nome"], "resultado", "nenhum autor casado — ver keys acima")
                continue
            for aid, v in agg.items():
                v["link"] = f"{sapl}/materia/pesquisar-materia?autoria__autor={aid}&ano={a}"
            lista = sorted(agg.values(), key=lambda v: (-v["alta"], -v["total"]))
            return bloco(lista, "SAPL — autoria por parlamentar",
                         f"{sapl}/parlamentar/", "verificada", f"Ano {a}")
        except Exception as e:
            print(f"[{c['nome']}] SAPL autoria {a}: {e}", file=sys.stderr)
    return bloco([], "SAPL (autoria indisponível no momento)", sapl, "demo")


def coletar_diario_oficial(c):
    url = f"https://queridodiario.ok.org.br/api/gazettes?territory_ids={c['ibge']}&size=1"
    link = f"https://queridodiario.ok.org.br/pesquisa/?territory_ids={c['ibge']}"
    for t in range(4):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            if r.status_code in (429, 503):
                raise RuntimeError(f"limite de chamadas ({r.status_code})")
            r.raise_for_status()
            total = r.json().get("total_gazettes", 0)
            if total:
                return bloco(total, "Querido Diário — Open Knowledge Brasil",
                             link, "verificada", "Edições do Diário Oficial indexadas")
            break
        except Exception as e:
            print(f"[{c['nome']}] Querido Diário tentativa {t+1}: {e}", file=sys.stderr)
            time.sleep(4 * (t + 1))
    return bloco(0, "Querido Diário", link, "demo",
                 "Cidade ainda não coberta pelo Querido Diário")


def coletar_cidade(c):
    descobrir_sapl(c)
    pop_b = coletar_populacao(c)
    fin = coletar_rreo(c)
    rgf_e = coletar_rgf_pessoal(c, "E")
    rgf_l = coletar_rgf_pessoal(c, "L")
    custo_b = coletar_custo_camara(c)
    base29a_29 = coletar_base29a(c, custo_b.get("exercicio"))
    folha_leg_b = folha_legislativo_dca(c)
    props_b = coletar_proposicoes(c)
    prod_b = coletar_producao_vereadores(c)
    dia_b = coletar_diario_oficial(c)

    pop = pop_b["valor"]
    n_ver = c.get("vereadores") or vereadores_teto(pop)
    return {**c, "vereadores": n_ver,
            "base29a_legal": base29a_29,
            "folha_legislativo_dca": folha_leg_b,
            "vereadores_estimado": c.get("vereadores") is None,
            "populacao": pop_b, "financas": fin,
            "rgf_executivo": rgf_e, "rgf_legislativo": rgf_l,
            "custo_camara": custo_b, "proposicoes": props_b,
            "producao_vereadores": prod_b, "diario_oficial": dia_b}


# ═════════════════ MOTOR DE NOTAS (duas fases: coleta → pontuação) ═════════
def pontuar(cidades):
    # C_rel precisa do grupo: percentil do custo/hab dentro do estrato do 29-A
    for d in cidades:
        pop = d["populacao"]["valor"]
        d["_limite"] = limite_art_29a(pop)
        d["_custo_hab"] = d["custo_camara"]["valor"] / pop
    grupos = {}
    for d in cidades:
        grupos.setdefault(d["_limite"], []).append(d["_custo_hab"])

    for d in cidades:
        pop = d["populacao"]["valor"]
        rc = d["financas"]["receita"]["valor"]
        dt = d["financas"]["despesa"]["valor"]
        inv = d["financas"]["investimentos"]["valor"]
        base_legal = d.get("base29a_legal")
        base = base_legal["valor"] if base_legal else None
        cc = d["custo_camara"]["valor"]
        limite = d["_limite"]
        # Só compara custo e base do mesmo ciclo legal (custo X ↔ base X-1)
        comparavel = bool(base_legal and d["custo_camara"].get("exercicio")
                          and d["custo_camara"]["status"] == "verificada")

        # ── F: Gestão fiscal ──
        margem = (rc - dt) / rc if rc else 0
        f_eq = clamp(50 + margem * 400)
        p_exec = d["rgf_executivo"]["valor"]
        f_pes = clamp((0.54 - p_exec) / 0.54 * 100 * 2.5) if p_exec is not None else 50.0
        taxa_inv = (inv / rc) if (inv is not None and rc) else None
        f_inv = clamp(taxa_inv / 0.12 * 100) if taxa_inv is not None else 50.0
        F = 0.50 * f_eq + 0.30 * f_pes + 0.20 * f_inv

        # ── C: Custo do Legislativo ──
        uso = (cc / base) if (comparavel and base) else None
        # Sem base do mesmo exercício, o teto não é calculável: o pilar C é
        # renormalizado entre folha e comparação com o grupo, e a cidade
        # perde confiança — nunca recebe nota inventada nem zero indevido.
        c_teto = clamp((1 - uso / limite) * 100) if uso is not None else None
        q_leg = d["rgf_legislativo"]["valor"]
        # Art. 29-A, §1º: folha da Câmara não pode passar de 70% do repasse
        folha_leg = (d.get("folha_legislativo_dca") or {}).get("valor")
        razao_folha_repasse = (folha_leg / cc) if (folha_leg and cc) else None
        if q_leg is not None:
            c_folha = clamp((0.06 - q_leg) / 0.06 * 100)
        elif razao_folha_repasse is not None:
            # Sem RGF: pontua pela regra dos 70% (0 no limite, 100 se folha zero)
            c_folha = clamp((0.70 - razao_folha_repasse) / 0.70 * 100)
        else:
            c_folha = 50.0
        if razao_folha_repasse is not None and razao_folha_repasse > 0.70:
            c_folha = 0.0  # violação do teto do §1º zera o componente
        grupo = sorted(grupos[limite])
        if len(grupo) >= 3:
            pos = grupo.index(d["_custo_hab"])
            perc = pos / (len(grupo) - 1) * 100
            c_rel = 100 - perc
        else:
            c_rel, perc = 50.0, None
        if c_teto is not None:
            C = 0.50 * c_teto + 0.30 * c_folha + 0.20 * c_rel
        else:
            C = (0.30 * c_folha + 0.20 * c_rel) / 0.50  # renormalizado

        # ── Q: Qualidade legislativa ──
        pr = d["proposicoes"]["valor"]
        W = pr.get("peso_medio", 0)
        q_prop = clamp(W / 0.35 * 100)
        # Cobertura parcial (portal que não publica indicações) infla o peso
        # médio: a nota é apenas indicativa e fica limitada, para que a
        # cidade que publica tudo não seja punida pela própria transparência.
        cobertura_props = pr.get("cobertura", "desconhecida")
        if cobertura_props == "parcial":
            q_prop = min(q_prop, 70.0)
        temas = pr.get("temas") or {}
        q_tema = entropia_norm(temas) * 100 if temas else 50.0
        Q = 0.60 * q_prop + 0.40 * q_tema

        nota = 0.40 * F + 0.30 * C + 0.30 * Q
        selo = "VIÁVEL" if nota >= 70 else "ATENÇÃO" if nota >= 45 else "CRÍTICO"

        blocos = [d["populacao"], d["financas"]["receita"], d["financas"]["despesa"],
                  (base_legal or {"status": "demo"}), d["rgf_executivo"], d["rgf_legislativo"],
                  d["custo_camara"], d["proposicoes"], d["producao_vereadores"]]
        confianca = sum(1 for b in blocos if b["status"] == "verificada") / len(blocos)

        d["indicadores"] = {
            "resultado_fiscal": rc - dt, "margem_fiscal": margem,
            "pessoal_executivo_rcl": p_exec, "taxa_investimento": taxa_inv,
            "limite_art29a": limite, "uso_limite": uso,
            "teto_comparavel": comparavel,
            "exercicio_custo": d["custo_camara"].get("exercicio"),
            "exercicio_base29a": (base_legal or {}).get("exercicio"),
            "pessoal_legislativo_rcl": q_leg,
            "folha_legislativo_valor": folha_leg,
            "folha_sobre_repasse": razao_folha_repasse,
            "custo_por_habitante": d["_custo_hab"],
            "custo_por_vereador": cc / d["vereadores"],
            "percentil_custo_estrato": perc,
            "peso_medio_proposicoes": W,
            "indice_propositivo": (pr["classes"]["ESTRUTURAL"] / pr["total"]) if pr.get("total") else 0,
            "cobertura_proposicoes": cobertura_props,
        }
        d["nota"] = {"final": round(nota, 1), "selo": selo,
                     "confianca": round(confianca, 2),
                     "f": round(F, 1), "f_eq": round(f_eq, 1),
                     "f_pes": round(f_pes, 1), "f_inv": round(f_inv, 1),
                     "c": round(C, 1),
                     "c_teto": (round(c_teto, 1) if c_teto is not None else None),
                     "c_folha": round(c_folha, 1), "c_rel": round(c_rel, 1),
                     "q": round(Q, 1), "q_prop": round(q_prop, 1),
                     "q_tema": round(q_tema, 1)}
        del d["_limite"], d["_custo_hab"]
    return sorted(cidades, key=lambda x: -x["nota"]["final"])


# ═════════════════ ANÁLISE ESCRITA AUTOMÁTICA ═════════════════
def _brl(v):
    return "—" if v is None else "R$ " + f"{v:,.0f}".replace(",", ".")


def _num(v):
    return "—" if v is None else f"{v:,.0f}".replace(",", ".")


def _pct(v):
    return "—" if v is None else f"{v*100:.1f}".replace(".", ",") + "%"


def gerar_analise(d):
    ind, n = d["indicadores"], d["nota"]
    frases = []
    m = ind["margem_fiscal"]
    if m >= 0.02:
        frases.append(f"As contas do Executivo fecham com superávit de {_pct(m)} da receita corrente")
    elif m >= 0:
        frases.append("As contas do Executivo estão no fio do equilíbrio")
    else:
        frases.append(f"O Executivo gasta mais do que arrecada — déficit de {_pct(abs(m))} da receita corrente")
    p = ind["pessoal_executivo_rcl"]
    if p is not None:
        if p > 0.54:
            frases.append(f"e a folha de pessoal ({_pct(p)} da RCL) ESTOURA o limite de 54% da LRF")
        elif p > 0.513:
            frases.append(f"e a folha de pessoal ({_pct(p)} da RCL) está na zona de alerta da LRF")
        else:
            frases.append(f"com folha de pessoal em {_pct(p)} da RCL, dentro do limite da LRF")
    t = ind["taxa_investimento"]
    if t is not None:
        frases.append(f"investindo {_pct(t)} da receita" +
                      (" — capacidade robusta de obra e melhoria" if t >= 0.10 else ""))
    a1 = ", ".join(frases) + "."

    frases = []
    uso = ind["uso_limite"]
    if uso is None:
        frases.append("O uso do teto constitucional da Câmara não é calculável nesta coleta "
                      "(dados do repasse e da base de cálculo ainda não disponíveis no mesmo ciclo)")
    if uso is not None:
        pct_teto = uso / ind["limite_art29a"]
        if pct_teto >= 0.95:
            frases.append(f"A Câmara consome {_pct(uso)} da base — praticamente TODO o teto constitucional de {_pct(ind['limite_art29a'])}")
        elif pct_teto >= 0.7:
            frases.append(f"A Câmara usa {_pct(uso)} de um teto de {_pct(ind['limite_art29a'])} — folga pequena")
        else:
            frases.append(f"A Câmara usa {_pct(uso)} de um teto de {_pct(ind['limite_art29a'])} — custo contido")
    ql = ind["pessoal_legislativo_rcl"]
    if ql is not None:
        frases.append(f"folha do Legislativo em {_pct(ql)} da RCL (limite: 6%)")
    if ind["percentil_custo_estrato"] is not None:
        pr = ind["percentil_custo_estrato"]
        comp = ("entre as mais baratas" if pr <= 33 else
                "na média" if pr <= 66 else "entre as MAIS CARAS")
        frases.append(f"custo de {_brl(ind['custo_por_habitante'])} por habitante/ano, "
                      f"{comp} do seu grupo populacional")
    a2 = ". ".join(frases) + "." if frases else ""

    pr = d["proposicoes"]["valor"]
    cls = pr.get("classes", {})
    tot = pr.get("total", 0)
    if tot:
        s = cls.get("SIMBOLICA", 0) / tot
        e = cls.get("ESTRUTURAL", 0) / tot
        a3 = (f"Na produção legislativa, {_pct(e)} das {_num(tot)} matérias do ano têm caráter "
              f"estrutural (criam ou alteram políticas e serviços) e {_pct(s)} são simbólicas "
              f"(homenagens, moções, denominações).")
        temas = pr.get("temas") or {}
        if temas:
            top = sorted(temas.items(), key=lambda x: -x[1])[:3]
            a3 += " Temas mais presentes: " + ", ".join(f"{t[0]} ({t[1]})" for t in top) + "."
    else:
        a3 = ""
    fecho = {"VIÁVEL": "O conjunto indica uma cidade bem gerida nos critérios acompanhados.",
             "ATENÇÃO": "O conjunto pede atenção: há pontos sólidos, mas ao menos uma dimensão pressionada.",
             "CRÍTICO": "O conjunto acende alerta: mais de uma dimensão está pressionada."}[n["selo"]]
    return " ".join(x for x in (a1, a2, a3, fecho) if x)


# ═════════════════ GERADOR DO SITE ═════════════════
COR = {"VIÁVEL": "#1E6B4F", "ATENÇÃO": "#B0731A", "CRÍTICO": "#C22F2A"}


def _selo_html(status):
    if status == "verificada":
        return '<span class="selo selo-ok">✓ fonte oficial</span>'
    return '<span class="selo selo-demo">dados de demonstração</span>'


def _linha(rot, val, alerta=False):
    cls = ' class="linha-valor alerta"' if alerta else ' class="linha-valor"'
    return (f'<div class="linha"><span>{rot}</span>'
            f'<span class="linha-pontos"></span><span{cls}>{val}</span></div>')


def _shell(titulo, descricao, canonical, corpo, raiz=""):
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{titulo}</title>
<meta name="description" content="{descricao}" />
<link rel="canonical" href="{canonical}" />
<meta property="og:title" content="{titulo}" />
<meta property="og:description" content="{descricao}" />
<meta property="og:type" content="website" />
<link rel="stylesheet" href="{raiz}estilo.css" />
</head>
<body>
{corpo}
<p class="rodape">{MARCA} · fiscalizaosmunicipios.com.br · projeto cívico de código aberto ·
<a href="{raiz}metodologia.html">como calculamos</a> · dados públicos (LAI e Lei da Transparência)</p>
</body>
</html>"""


def _subnotas(pares):
    return " · ".join(f"{r} {v:.0f}".replace(".", ",") for r, v in pares)


def pagina_cidade(c, pos, total, gerado_em):
    ind, n = c["indicadores"], c["nota"]
    rc, dt = c["financas"]["receita"], c["financas"]["despesa"]
    cc = c["custo_camara"]
    cor = COR[n["selo"]]
    s = slug(c["nome"]) + "-" + c["uf"].lower()
    url = f"{DOMINIO}/cidades/{s}.html"

    titulo = (f"Quanto custa a Câmara de {c['nome']} ({c['uf']})? "
              f"Nota {n['final']:.0f}/100 no ranking | {MARCA}")
    descricao = (f"{c['nome']}-{c['uf']}: Câmara custa {_brl(cc['valor'])}/ano "
                 f"({_brl(ind['custo_por_habitante'])} por habitante). Gestão fiscal, folha de "
                 f"pessoal (LRF), produção legislativa e análise completa com fontes oficiais.")

    props_html = "".join(_linha(f"{p['tipo']}", _num(p["qtd"]))
                         for p in c["proposicoes"]["valor"]["tipos"][:10])
    uso_pct = min((ind["uso_limite"] / ind["limite_art29a"]) * 100, 100) if ind["uso_limite"] else 0
    cor_uso = "#1E6B4F" if ind["uso_limite"] and ind["uso_limite"] <= ind["limite_art29a"] else "#C22F2A"
    if ind.get("uso_limite") is not None:
        bloco_teto = (
            f'<div class="barra"><div style="width:{uso_pct:.0f}%;background:{cor_uso}"></div></div>'
            f'<p class="legenda">Uso do teto do art. 29-A: {_pct(ind["uso_limite"])} de '
            f'{_pct(ind["limite_art29a"])} permitidos · repasse do exercício '
            f'{ind.get("exercicio_custo")} sobre a base de {ind.get("exercicio_base29a")}, '
            f'como manda a CF</p>')
    else:
        bloco_teto = ('<div class="nota">Uso do teto do art. 29-A: <b>não calculável</b> nesta '
                      'coleta — o SICONFI ainda não tem, para este município, o custo da Câmara e a '
                      'base de cálculo do exercício anterior no mesmo ciclo. Comparar anos '
                      'diferentes produziria um percentual falso, então preferimos não publicar. '
                      'O pilar C foi calculado apenas com folha do Legislativo e comparação com o '
                      'grupo populacional, e a confiança da cidade caiu.</div>')
    prelim = ("" if n["confianca"] >= 1 else
              f'<div class="conf">nota preliminar — {n["confianca"]:.0%} das fontes verificadas</div>')

    prod = c.get("producao_vereadores") or {}
    if prod.get("status") == "verificada" and prod.get("valor"):
        max_alta = max(v["alta"] for v in prod["valor"]) or 1
        linhas_v = ""
        for pv, v in enumerate(prod["valor"], 1):
            linhas_v += (
                f'<div class="ver"><div class="ver-topo">'
                f'<span class="ver-nome">{pv}º · {v["nome"]}</span>'
                f'<span class="ver-efic">{v["alta"]} estruturais</span></div>'
                f'<div class="ver-detalhe">{v["total"]} proposições no ano — '
                f'{v["alta"]} estruturais · {v["media"]} regulatórias · {v["baixa"]} simbólicas · '
                f'<a href="{v["link"]}" target="_blank" rel="noreferrer">conferir no portal oficial</a></div>'
                f'<div class="ver-barra"><div style="width:{(v["alta"]/max_alta*100):.0f}%"></div></div></div>')
        vers_html = (
            f'<h2 style="margin-top:26px">Produção por vereador {_selo_html("verificada")}</h2>'
            f'<p class="sub">{prod.get("detalhe","")} · classificação automática das ementas '
            f'(NLP estágio 1) · fonte: <a href="{prod["url"]}" target="_blank" rel="noreferrer">SAPL da Câmara</a></p>'
            + linhas_v +
            '<p class="legenda" style="margin-top:10px">Cada link abre a lista oficial de proposições do vereador. Estruturais criam/alteram políticas e serviços; simbólicas são homenagens, moções e denominações.</p>')
    else:
        vers_html = ('<div class="nota">Produção individual por vereador: esta Câmara usa sistema próprio, '
                     'sem API pública de autoria — o conector está em desenvolvimento. '
                     'Nomes de vereadores só são publicados com fonte oficial verificável.</div>')

    extra_li = "".join(
        f'<li><a href="{u}" target="_blank" rel="noreferrer">{r}</a></li>'
        for r, u in (c.get("fontes_extra") or []))
    transp_li = ""
    if c.get("transparencia"):
        sist = c.get("transparencia_sistema", "portal municipal")
        transp_li = (f'<li><a href="{c["transparencia"]}" target="_blank" rel="noreferrer">'
                     f'Portal da Transparência do Executivo ({sist})</a> — folha por servidor, '
                     f'empenhos, diárias e licitações (conector Fase B)</li>')
    dia = c.get("diario_oficial") or {}
    diario_txt = (f" — {_num(dia['valor'])} edições indexadas"
                  if dia.get("status") == "verificada" and dia.get("valor") else "")
    pr = c["proposicoes"]["valor"]
    cls = pr.get("classes", {})
    cob = ind.get("cobertura_proposicoes")
    if cob == "parcial":
        aviso_cobertura = ('<div class="nota">O portal desta Câmara publica sobretudo projetos '
                           'de lei; indicações e moções aparecem pouco ou não aparecem. Como isso '
                           'infla artificialmente o peso médio das matérias, a nota deste pilar é '
                           'limitada e serve apenas como indicação — não é comparável com cidades '
                           'que publicam a produção completa.</div>')
    elif cob == "completa":
        aviso_cobertura = ('<div class="nota">Cobertura completa: o portal publica a produção '
                           'inteira, incluindo indicações e moções. A comparação com cidades de '
                           'cobertura parcial deve levar isso em conta — transparência maior '
                           'costuma revelar índices propositivos menores.</div>')
    else:
        aviso_cobertura = ""

    corpo = f"""<a class="voltar" href="../index.html">← voltar ao ranking</a>
<header class="cabecalho">
  <div class="protocolo">RETRATO DO MUNICÍPIO · {pos}º DE {total} NO RANKING · ATUALIZADO EM {gerado_em[:10]}</div>
  <h1>{c['nome']} — {c['uf']}
    <small>{_num(c['populacao']['valor'])} habitantes {_selo_html(c['populacao']['status'])} ·
    {'≈ ' if c.get('vereadores_estimado') else ''}{c['vereadores']} vereadores{' (teto do art. 29 da CF — confirmar na Lei Orgânica)' if c.get('vereadores_estimado') else ''}</small>
  </h1>
  <div class="carimbo" style="color:{cor}">{n['selo']}</div>
  <span class="nota-grande" style="color:{cor}">nota {n['final']}/100</span>
  {prelim}
</header>

<div class="nota"><b>Leitura do retrato:</b> {gerar_analise(c)}</div>

<section>
  <h2>Gestão fiscal — Executivo {_selo_html(rc['status'])}</h2>
  <p class="sub">{rc.get('detalhe') or 'SICONFI'} · pilar F = {n['f']}/100 ({_subnotas([('equilíbrio', n['f_eq']), ('pessoal LRF', n['f_pes']), ('investimento', n['f_inv'])])})</p>
  {_linha("Receita corrente realizada", _brl(rc['valor']))}
  {_linha("Despesa total liquidada", _brl(dt['valor']))}
  {_linha("Resultado", _brl(ind['resultado_fiscal']), ind['resultado_fiscal'] < 0)}
  {_linha("Pessoal do Executivo (% RCL — limite 54%)", _pct(ind['pessoal_executivo_rcl']), (ind['pessoal_executivo_rcl'] or 0) > 0.54)}
  {_linha("Investimentos (% da receita)", _pct(ind['taxa_investimento']))}
</section>

<section>
  <h2>Custo do Legislativo {_selo_html(cc['status'])}</h2>
  <p class="sub">Pilar C = {n['c']}/100 ({_subnotas(([('teto 29-A', n['c_teto'])] if n['c_teto'] is not None else []) + [('folha LRF', n['c_folha']), ('vs. grupo', n['c_rel'])])})</p>
  {bloco_teto}
  {_linha("Custo anual da função Legislativa", _brl(cc['valor']))}
  {_linha("Folha do Legislativo (% RCL — limite 6%)", _pct(ind['pessoal_legislativo_rcl']), (ind['pessoal_legislativo_rcl'] or 0) > 0.06)}
  {_linha("Pessoal da Câmara (valor anual)", _brl(ind.get('folha_legislativo_valor')))}
  {_linha("Folha sobre o repasse (art. 29-A §1º — limite 70%)", _pct(ind.get('folha_sobre_repasse')), (ind.get('folha_sobre_repasse') or 0) > 0.70)}
  {_linha("Custo por habitante / ano", _brl(ind['custo_por_habitante']))}
  {_linha("Custo por vereador / ano", _brl(ind['custo_por_vereador']))}
</section>

<section>
  <h2>Qualidade da produção legislativa {_selo_html(c['proposicoes']['status'])}</h2>
  {aviso_cobertura}
  <p class="sub">Pilar Q = {n['q']}/100 ({_subnotas([('peso das matérias', n['q_prop']), ('diversidade de temas', n['q_tema'])])}) · {c['proposicoes'].get('detalhe','')}</p>
  {_linha("Matérias estruturais (criam/alteram políticas)", _num(cls.get('ESTRUTURAL')))}
  {_linha("Matérias regulatórias/fiscalizatórias", _num(cls.get('REGULATORIA')))}
  {_linha("Matérias simbólicas (homenagens, denominações)", _num(cls.get('SIMBOLICA')))}
  {props_html}
  {vers_html}
</section>

<section class="fontes">
  <h2>Fontes e verificação</h2>
  <ul>
    <li><a href="{rc['url']}" target="_blank" rel="noreferrer">SICONFI — receitas/despesas (consulta desta página)</a></li>
    <li><a href="{c['rgf_executivo']['url']}" target="_blank" rel="noreferrer">SICONFI/RGF — pessoal do Executivo</a></li>
    <li><a href="{c['rgf_legislativo']['url']}" target="_blank" rel="noreferrer">SICONFI/RGF — pessoal do Legislativo</a></li>
    <li><a href="{cc['url']}" target="_blank" rel="noreferrer">SICONFI/DCA — custo da função Legislativa</a></li>
    <li><a href="{c['populacao']['url']}" target="_blank" rel="noreferrer">IBGE — população</a></li>
    <li><a href="{c['proposicoes']['url']}" target="_blank" rel="noreferrer">Portal da Câmara — proposições</a></li>
    <li><a href="{dia.get('url','#')}" target="_blank" rel="noreferrer">Querido Diário — Diário Oficial do município</a>{diario_txt}</li>
    {extra_li}{transp_li}<li><a href="https://divulgacandcontas.tse.jus.br" target="_blank" rel="noreferrer">TSE / DivulgaCandContas — bens e campanhas dos eleitos</a></li>
    <li><a href="https://radardatransparencia.atricon.org.br" target="_blank" rel="noreferrer">Radar da Transparência Pública (Atricon)</a></li>
  </ul>
  <div class="nota">Números com "✓ fonte oficial" foram coletados automaticamente na data indicada; os links abrem exatamente a consulta usada. A régua completa está em <a href="../metodologia.html">como calculamos</a>.</div>
</section>"""
    return s, url, _shell(titulo, descricao, url, corpo, raiz="../")


def pagina_index(dados):
    cidades = dados["cidades"]
    titulo = f"Ranking das cidades mais bem geridas | {MARCA}"
    descricao = ("Quanto custa a Câmara da sua cidade? Ranking com capitais e municípios por "
                 "gestão fiscal, custo do legislativo e qualidade da produção dos vereadores — "
                 "dados oficiais verificáveis.")
    itens = []
    for i, c in enumerate(cidades, 1):
        n = c["nota"]
        s = slug(c["nome"]) + "-" + c["uf"].lower()
        cor = COR[n["selo"]]
        prelim = ("" if n["confianca"] >= 1 else
                  f'<div class="conf">nota preliminar — {n["confianca"]:.0%} das fontes verificadas</div>')
        pil = "".join(
            f'<div class="pilar"><div class="pilar-rotulo">{r} · {v:.0f}</div>'
            f'<div class="pilar-barra"><div style="width:{v:.0f}%"></div></div></div>'
            for r, v in [("Gestão fiscal", n["f"]), ("Custo do legislativo", n["c"]),
                         ("Produção legislativa", n["q"])])
        itens.append(f"""<a class="cidade" href="cidades/{s}.html">
  <div class="topo"><span class="pos">{i}º</span>
  <span class="nome">{c['nome']} — {c['uf']}{' · capital' if c.get('capital') else ''}</span>
  <span class="selo-cidade" style="color:{cor}">{n['selo']}</span>
  <span class="nota-rank" style="color:{cor}">{str(n['final']).replace('.', ',')}</span></div>
  <div class="pilares">{pil}</div>{prelim}</a>""")

    corpo = f"""<header class="cabecalho">
  <div class="protocolo">{MARCA.upper()} · BASE DE PESQUISA CÍVICA</div>
  <h1>Quais cidades são bem geridas?
    <small>{len(cidades)} cidades analisadas · atualizado em {dados['gerado_em'][:10]} · gestão fiscal, custo do legislativo e qualidade da produção dos vereadores, com dados públicos verificáveis</small>
  </h1>
</header>
<div class="metodo"><b>Como a nota é calculada:</b> 40% gestão fiscal (equilíbrio, folha de pessoal da LRF e investimento),
30% custo do legislativo (teto do art. 29-A, folha parlamentar e comparação com o grupo populacional) e
30% qualidade legislativa (peso real das matérias, por classificação automática das ementas, e diversidade de temas).
Fórmulas em <a href="metodologia.html">como calculamos</a> · lacunas declaradas em <a href="cobertura.html">cobertura de dados</a>. Notas com fontes pendentes são preliminares.</div>
{''.join(itens)}"""
    return _shell(titulo, descricao, DOMINIO + "/", corpo)


def pagina_metodologia(dados):
    titulo = f"Como calculamos a nota | {MARCA}"
    descricao = "Metodologia aberta: fórmulas da nota de gestão municipal, fontes oficiais e limites legais usados."
    corpo = f"""<a class="voltar" href="index.html">← voltar ao ranking</a>
<header class="cabecalho">
  <div class="protocolo">METODOLOGIA ABERTA · VERSÃO 2.0</div>
  <h1>Como calculamos<small>Toda régua é pública. Mudanças de fórmula são versionadas e anunciadas.</small></h1>
</header>
<section>
  <h2>A nota (0–100)</h2>
  <p>NOTA = 40% × Gestão Fiscal + 30% × Custo do Legislativo + 30% × Qualidade Legislativa.</p>
  {_linha("Gestão Fiscal (F)", "50% equilíbrio · 30% pessoal LRF · 20% investimento")}
  {_linha("Custo do Legislativo (C)", "50% teto art. 29-A · 30% folha LRF · 20% vs. grupo populacional")}
  {_linha("Qualidade Legislativa (Q)", "60% peso das matérias · 40% diversidade de temas")}
  <div class="nota">Equilíbrio: 50 pontos no empate receita×despesa, ±4 pontos por ponto percentual de margem.
  Pessoal do Executivo: limite de 54% da RCL (LRF, art. 20); do Legislativo: 6% da RCL.
  Teto do art. 29-A da CF: de 7% (até 100 mil hab.) a 3,5% (acima de 8 mi) da receita tributária ampliada <b>do exercício anterior</b> — comparamos sempre o repasse de um ano com a base do ano anterior, ambos de exercícios encerrados (DCA). Quando os dois não existem no mesmo ciclo, o indicador é publicado como não calculável em vez de gerar um percentual falso.
  Peso das matérias: estruturais valem 1,0; regulatórias 0,6; simbólicas (homenagens, moções, denominações) 0,0 —
  classificadas automaticamente pelas ementas (regras de alta precisão), com revisão humana prevista para casos ambíguos.
  Diversidade: entropia dos temas (Saúde, Educação, Saneamento, Mobilidade, etc.).
  A efetividade (matérias aprovadas que viraram norma) entra na próxima versão, quando a ligação matéria→norma
  estiver coletada para todas as Câmaras.</div>
</section>
<section>
  <h2>Confiança e limites</h2>
  <p>Cada número carrega fonte, URL da consulta e data. A fração de blocos verificados vira o índice de confiança da
  cidade; abaixo de 100%, a nota é preliminar. Estimativas (como o nº de vereadores pelo teto do art. 29 da CF)
  são sempre rotuladas. Resultados de impacto de leis sobre indicadores sociais serão publicados apenas como
  associação estatística com metodologia aberta — nunca como crédito causal individual a um vereador.</p>
</section>
<section class="fontes">
  <h2>Fontes</h2>
  <ul>
    <li><a href="https://apidatalake.tesouro.gov.br/docs/siconfi/" target="_blank" rel="noreferrer">SICONFI/Tesouro Nacional — RREO, RGF e DCA</a></li>
    <li><a href="https://servicodados.ibge.gov.br/api/docs" target="_blank" rel="noreferrer">IBGE — população e localidades</a></li>
    <li><a href="https://www12.senado.leg.br/interlegis/produtos/sapl" target="_blank" rel="noreferrer">SAPL/Interlegis — proposições e autoria</a></li>
    <li><a href="https://queridodiario.ok.org.br" target="_blank" rel="noreferrer">Querido Diário (Open Knowledge Brasil)</a></li>
    <li><a href="https://divulgacandcontas.tse.jus.br" target="_blank" rel="noreferrer">TSE — DivulgaCandContas</a></li>
    <li><a href="{REPO}" target="_blank" rel="noreferrer">Código aberto e documento completo de arquitetura (GitHub)</a></li>
  </ul>
</section>"""
    return _shell(titulo, descricao, DOMINIO + "/metodologia.html", corpo)


ROTULOS_BLOCOS = [
    ("populacao", "População (IBGE)"),
    ("receita", "Receita (SICONFI)"),
    ("investimentos", "Investimentos"),
    ("base29a", "Base art. 29-A"),
    ("rgf_executivo", "Pessoal Executivo (RGF)"),
    ("rgf_legislativo", "Pessoal Legislativo (RGF)"),
    ("custo_camara", "Custo da Câmara (DCA)"),
    ("proposicoes", "Proposições"),
    ("producao_vereadores", "Autoria por vereador"),
    ("diario_oficial", "Diário Oficial (QD)"),
]

MOTIVOS_PENDENCIA = {
    "proposicoes": "a Câmara não usa o SAPL/Interlegis; conector para o sistema próprio em desenvolvimento",
    "producao_vereadores": "sem API pública de autoria no sistema da Câmara",
    "diario_oficial": "município ainda não coberto pelo Querido Diário",
    "investimentos": "linha não localizada no RREO/DCA do período",
    "rgf_executivo": "RGF do período ainda não homologado no SICONFI",
    "rgf_legislativo": "RGF do Legislativo ainda não homologado no SICONFI",
}


def _bloco_de(c, chave):
    if chave in ("receita", "investimentos", "base29a"):
        return c["financas"][chave]
    return c.get(chave) or {"status": "demo"}


def pagina_cobertura(dados):
    titulo = f"Cobertura de dados por cidade | {MARCA}"
    descricao = ("Transparência sobre a própria base: o que está verificado em fonte "
                 "oficial e o que está pendente em cada cidade do ranking.")
    total_v = total_b = 0
    linhas = []
    for c in dados["cidades"]:
        celulas = ""
        pend = []
        for chave, rotulo in ROTULOS_BLOCOS:
            ok = _bloco_de(c, chave)["status"] == "verificada"
            total_b += 1
            total_v += ok
            celulas += ("<span class='selo selo-ok'>✓</span>" if ok
                        else "<span class='selo selo-demo'>—</span>")
            if not ok:
                pend.append(MOTIVOS_PENDENCIA.get(chave, rotulo))
        s = slug(c["nome"]) + "-" + c["uf"].lower()
        motivo = ("Completa nos blocos acompanhados." if not pend
                  else "Pendências: " + "; ".join(sorted(set(pend))) + ".")
        linhas.append(
            f"<div class='ver'><div class='ver-topo'>"
            f"<span class='ver-nome'><a href='cidades/{s}.html'>{c['nome']} — {c['uf']}</a></span>"
            f"<span class='ver-efic'>{c['nota']['confianca']:.0%}</span></div>"
            f"<div style='margin-top:4px'>{celulas}</div>"
            f"<div class='ver-detalhe'>{motivo}</div></div>")
    cab = " · ".join(r for _, r in ROTULOS_BLOCOS)
    corpo = f"""<a class="voltar" href="index.html">← voltar ao ranking</a>
<header class="cabecalho">
  <div class="protocolo">TRANSPARÊNCIA DA PRÓPRIA BASE</div>
  <h1>Cobertura de dados<small>{total_v} de {total_b} blocos verificados em fonte oficial
  ({total_v/total_b:.0%}) · atualizado em {dados['gerado_em'][:10]}. Lacunas não são escondidas:
  são listadas com o motivo e entram na nota como confiança reduzida.</small></h1>
</header>
<p class="sub">Ordem dos blocos: {cab}.</p>
{''.join(linhas)}
<div class="nota">Sabe onde encontrar um dado pendente da sua cidade (portal da Câmara,
sistema de proposituras)? Envie o link pelo repositório do projeto — foi assim que
Charqueada ganhou suas fontes.</div>"""
    return _shell(titulo, descricao, DOMINIO + "/cobertura.html", corpo)


def gerar_site(dados):
    import os
    os.makedirs("docs/cidades", exist_ok=True)
    urls = [DOMINIO + "/", DOMINIO + "/metodologia.html", DOMINIO + "/cobertura.html"]
    for i, c in enumerate(dados["cidades"], 1):
        s, url, html = pagina_cidade(c, i, len(dados["cidades"]), dados["gerado_em"])
        with open(f"docs/cidades/{s}.html", "w", encoding="utf-8") as fh:
            fh.write(html)
        urls.append(url)
    with open("docs/index.html", "w", encoding="utf-8") as fh:
        fh.write(pagina_index(dados))
    with open("docs/metodologia.html", "w", encoding="utf-8") as fh:
        fh.write(pagina_metodologia(dados))
    with open("docs/cobertura.html", "w", encoding="utf-8") as fh:
        fh.write(pagina_cobertura(dados))
    with open("docs/CNAME", "w") as fh:
        fh.write("fiscalizaosmunicipios.com.br\n")
    with open("docs/robots.txt", "w") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {DOMINIO}/sitemap.xml\n")
    hoje = dados["gerado_em"][:10]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f"  <url><loc>{u}</loc><lastmod>{hoje}</lastmod></url>")
    sm.append("</urlset>")
    with open("docs/sitemap.xml", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sm))
    print(f"✓ site gerado: index + metodologia + {len(urls)-2} cidades + sitemap")


# ═════════════════ MAIN ═════════════════
if __name__ == "__main__":
    brutos = []
    for c in CIDADES:
        print(f"→ Coletando {c['nome']}-{c['uf']}…")
        if not resolver_ibge(c):
            print("  (pulada: sem código IBGE)")
            continue
        brutos.append(coletar_cidade(c))
        time.sleep(2)

    ranking = pontuar(brutos)
    saida = {
        "gerado_em": agora(),
        "metodologia": {
            "versao": "2.0",
            "pesos": {"gestao_fiscal": 0.4, "custo_legislativo": 0.3,
                      "qualidade_legislativa": 0.3},
            "descricao": ("F = 50% equilíbrio + 30% pessoal LRF(54%) + 20% investimento. "
                          "C = 50% teto art.29-A + 30% folha LRF(6%) + 20% custo vs. estrato. "
                          "Q = 60% peso NLP das matérias + 40% entropia temática. "
                          "Confiança = fração de blocos com fonte verificada."),
        },
        "cidades": ranking,
    }
    with open("docs/dados.json", "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=2)
    with open("docs/diagnostico.json", "w", encoding="utf-8") as fh:
        json.dump(DIAGNOSTICO, fh, ensure_ascii=False, indent=2)
    print("\n✓ docs/dados.json gerado")
    gerar_site(saida)
    for i, x in enumerate(ranking[:10], 1):
        n = x["nota"]
        print(f"  {i}º {x['nome']}-{x['uf']}: {n['final']} "
              f"(F{n['f']} C{n['c']} Q{n['q']}, conf {n['confianca']:.0%})")
