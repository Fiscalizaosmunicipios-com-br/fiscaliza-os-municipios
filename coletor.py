#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar dos Municípios — Coletor autônomo multi-cidades
Base de pesquisa: cidades bem geridas, legislativos produtivos.

Para cada cidade coleta:
  IBGE     — população
  SICONFI  — RREO (receitas/despesas -> gestão fiscal do Executivo)
  SICONFI  — DCA função 01-Legislativa (custo real da Câmara)
  SAPL     — proposições (produção legislativa), quando o portal expõe API

E calcula a NOTA DA CIDADE (0-100) em três pilares:
  40% Gestão fiscal      (Executivo/prefeito: equilíbrio das contas)
  30% Custo do Legislativo (quanto do teto do art. 29-A a Câmara consome)
  30% Produção legislativa (proposições de peso vs. homenagens)

Saída: docs/dados.json — ranking + detalhe por cidade, cada número com
metadados de verificação (fonte, URL, status verificada/demo).
"""

import json
import sys
import time
import unicodedata
from datetime import datetime, timezone

import requests

# ─────────────────────────────────────────────
# Cidades analisadas — para adicionar uma cidade,
# basta acrescentar uma linha aqui.
# vereadores: conferir na Lei Orgânica de cada município.
# ─────────────────────────────────────────────
CIDADES = [
    {"nome": "Charqueada", "uf": "SP", "ibge": "3511706", "vereadores": 9, "sapl": None},
    {"nome": "São Pedro", "uf": "SP", "ibge": "3550407", "vereadores": 11, "sapl": None},
    {"nome": "Rio das Pedras", "uf": "SP", "ibge": "3544004", "vereadores": 10, "sapl": None},
    {"nome": "Piracicaba", "uf": "SP", "ibge": "3538709", "vereadores": 23, "sapl": None},
    {"nome": "Jacareí", "uf": "SP", "ibge": "3524402", "vereadores": 13, "sapl": None},
    # Câmaras com SAPL (Interlegis): produção por vereador com nome real e link
    {"nome": "Ilha Comprida", "uf": "SP", "ibge": None, "vereadores": 9,
     "sapl": "https://sapl.ilhacomprida.sp.leg.br"},
    {"nome": "Sales Oliveira", "uf": "SP", "ibge": "3544905", "vereadores": 9,
     "sapl": "https://sapl.salesoliveira.sp.leg.br"},
]

# Capitais (Brasília fica fora: o DF não tem Câmara de Vereadores e o
# art. 29-A não se aplica à CLDF). vereadores=None → estimado pelo teto
# constitucional (EC 58/2009) a partir da população.
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

IBGE_POP = "https://servicodados.ibge.gov.br/api/v1/projecoes/populacao/{ibge}"
SICONFI = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
TIMEOUT = 30
UA = {"User-Agent": "RadarMunicipios/0.2 (projeto civico; dados publicos)"}

# Demonstração por cidade (escala aproximada) — usada só se a fonte falhar,
# sempre marcada status="demo".
DEMO_FIN = {
    "3511706": (15814, 118e6, 112.5e6, 52e6, 3.35e6),
    "3550407": (37000, 260e6, 252e6, 120e6, 8.2e6),
    "3544004": (36000, 240e6, 236e6, 112e6, 7.9e6),
    "3538709": (425000, 2600e6, 2510e6, 1300e6, 68e6),
    "3524402": (242093, 1512e6, 1448e6, 690e6, 32.8e6),
}

def demo_fin(c):
    return DEMO_FIN.get(c["ibge"], (500_000, 3_000_000_000, 2_950_000_000,
                                    1_400_000_000, 60_000_000))


DEMO_PROPS = [
    {"tipo": "Projetos de Lei", "qtd": 40, "peso": "alta"},
    {"tipo": "Emendas e substitutivos", "qtd": 15, "peso": "alta"},
    {"tipo": "Requerimentos", "qtd": 60, "peso": "media"},
    {"tipo": "Indicações", "qtd": 250, "peso": "baixa"},
    {"tipo": "Moções e homenagens", "qtd": 85, "peso": "baixa"},
]


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bloco(valor, fonte, url, status, detalhe=""):
    return {"valor": valor, "fonte": fonte, "url": url, "status": status,
            "coletado_em": agora(), "detalhe": detalhe}


def slug(nome):
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return s.lower().replace(" ", "")


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


UF_COD = {"SP": 35, "RJ": 33, "MG": 31, "PR": 41, "RS": 43, "SC": 42,
          "BA": 29, "GO": 52, "ES": 32, "MT": 51, "MS": 50, "DF": 53}
_cache_municipios = {}


def resolver_ibge(c):
    """Preenche c['ibge'] pelo nome, via API de localidades do IBGE."""
    if c.get("ibge"):
        return True
    uf = c["uf"]
    if uf not in _cache_municipios:
        url = (f"https://servicodados.ibge.gov.br/api/v1/localidades/"
               f"estados/{UF_COD.get(uf, uf)}/municipios")
        for tentativa in range(3):
            try:
                r = requests.get(url, timeout=TIMEOUT, headers=UA)
                r.raise_for_status()
                _cache_municipios[uf] = {slug(m["nome"]): str(m["id"])
                                         for m in r.json()}
                break
            except Exception as e:
                print(f"[{c['nome']}] localidades IBGE tentativa {tentativa+1}: {e}",
                      file=sys.stderr)
                time.sleep(4 * (tentativa + 1))
        if uf not in _cache_municipios:
            return False
    cod = _cache_municipios[uf].get(slug(c["nome"]))
    if cod:
        c["ibge"] = cod
        print(f"[{c['nome']}] código IBGE resolvido: {cod}")
        return True
    print(f"[{c['nome']}] não encontrado na base do IBGE", file=sys.stderr)
    return False


def _sapl_paginar(url_base, max_paginas=20):
    """Percorre a paginação da API do SAPL (Django REST: next/results)."""
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


# ───────────── Coletas ─────────────
def coletar_populacao(c):
    # 1ª opção: API de agregados (estimativas oficiais de população,
    # agregado 6579 / variável 9324) — endpoint atual do IBGE
    url_v3 = ("https://servicodados.ibge.gov.br/api/v3/agregados/6579/"
              f"periodos/-1/variaveis/9324?localidades=N6[{c['ibge']}]")
    for tentativa in range(3):
        try:
            r = requests.get(url_v3, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            serie = r.json()[0]["resultados"][0]["series"][0]["serie"]
            ano, valor = sorted(serie.items())[-1]
            pop = int(valor)
            return bloco(pop, f"IBGE — Estimativas de População ({ano})",
                         url_v3, "verificada")
        except Exception as e:
            print(f"[{c['nome']}] IBGE agregados tentativa {tentativa+1}: {e}",
                  file=sys.stderr)
            time.sleep(3 * (tentativa + 1))
    # 2ª opção: API de projeções (antiga)
    url = IBGE_POP.format(ibge=c["ibge"])
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        pop = r.json()["projecao"]["populacao"]
        return bloco(pop, "IBGE — Projeções de População", url, "verificada")
    except Exception as e:
        print(f"[{c['nome']}] IBGE projeções falhou: {e}", file=sys.stderr)
        return bloco(demo_fin(c)[0], "IBGE", url, "demo", str(e))


def coletar_rreo(c):
    ano_atual = datetime.now().year
    tentativas = [(ano_atual, p) for p in range(6, 0, -1)] + \
                 [(ano_atual - 1, p) for p in range(6, 0, -1)]
    for ano, periodo in tentativas:
        url = (f"{SICONFI}/rreo?an_exercicio={ano}&nr_periodo={periodo}"
               f"&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2001"
               f"&id_ente={c['ibge']}")
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            itens = r.json().get("items", [])
            if not itens:
                continue

            def valor(cod, padrao):
                for i in itens:
                    if i.get("cod_conta") == cod and padrao in (i.get("coluna") or "").upper():
                        return i.get("valor")
                return None

            rc = valor("ReceitasCorrentes", "ATÉ O BIMESTRE")
            dt = valor("TotalDespesas", "LIQUIDADAS ATÉ O BIMESTRE") or \
                 valor("TotalDespesas", "ATÉ O BIMESTRE")
            trib = valor("ReceitaTributaria", "ATÉ O BIMESTRE") or 0
            transf = valor("TransferenciasCorrentes", "ATÉ O BIMESTRE") or 0
            base = (trib + transf) or None
            if rc:
                det = f"RREO Anexo 01, {periodo}º bimestre {ano}"
                d = demo_fin(c)
                return {
                    "receita": bloco(rc, "SICONFI/RREO", url, "verificada", det),
                    "despesa": bloco(dt or d[2], "SICONFI/RREO", url,
                                     "verificada" if dt else "demo", det),
                    "base29a": bloco(base or d[3],
                                     "SICONFI/RREO (base aprox. art. 29-A)", url,
                                     "verificada" if base else "demo",
                                     "Aproximação: tributária + transferências correntes"),
                }
        except Exception as e:
            pass
    # Plano B: DCA anual (cidades pequenas atrasam a entrega do RREO)
    dca = coletar_dca_anual(c)
    if dca:
        return dca
    d = demo_fin(c)
    print(f"[{c['nome']}] SICONFI/RREO e DCA indisponíveis — demo", file=sys.stderr)
    return {"receita": bloco(d[1], "SICONFI", SICONFI, "demo"),
            "despesa": bloco(d[2], "SICONFI", SICONFI, "demo"),
            "base29a": bloco(d[3], "SICONFI", SICONFI, "demo")}


def coletar_dca_anual(c):
    """Receita/despesa do último exercício encerrado via DCA (anexos I-C e I-D)."""
    ano_atual = datetime.now().year
    for ano in (ano_atual - 1, ano_atual - 2):
        try:
            rec = desp = trib = transf = None
            url_c = (f"{SICONFI}/dca?an_exercicio={ano}"
                     f"&no_anexo=DCA-Anexo%20I-C&id_ente={c['ibge']}")
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
            url_d = (f"{SICONFI}/dca?an_exercicio={ano}"
                     f"&no_anexo=DCA-Anexo%20I-D&id_ente={c['ibge']}")
            r = requests.get(url_d, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            for i in r.json().get("items", []):
                conta = (i.get("conta") or "").lower()
                col = (i.get("coluna") or "").lower()
                if "liquidad" in col and ("despesas correntes" in conta or
                                          "total" in conta):
                    v = i.get("valor")
                    if v is not None:
                        desp = max(desp or 0, v)
            if rec:
                det = f"DCA — contas anuais, exercício {ano}"
                print(f"[{c['nome']}] plano B DCA {ano}: receita={rec:,.0f}")
                d = demo_fin(c)
                base = ((trib or 0) + (transf or 0)) or None
                return {
                    "receita": bloco(rec, "SICONFI/DCA", url_c, "verificada", det),
                    "despesa": bloco(desp or d[2], "SICONFI/DCA", url_d,
                                     "verificada" if desp else "demo", det),
                    "base29a": bloco(base or d[3],
                                     "SICONFI/DCA (base aprox. art. 29-A)", url_c,
                                     "verificada" if base else "demo",
                                     "Aproximação: impostos + transferências correntes"),
                }
        except Exception as e:
            print(f"[{c['nome']}] DCA anual {ano} falhou: {e}", file=sys.stderr)
    return None


def coletar_custo_camara(c):
    ano_atual = datetime.now().year
    for ano in (ano_atual - 1, ano_atual - 2):
        url = (f"{SICONFI}/dca?an_exercicio={ano}"
               f"&no_anexo=DCA-Anexo%20I-E&id_ente={c['ibge']}")
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            for i in r.json().get("items", []):
                if "legislativa" in (i.get("conta") or "").lower() and \
                   "liquidada" in (i.get("coluna") or "").lower():
                    v = i.get("valor")
                    if v:
                        return bloco(v, "SICONFI/DCA — função 01 Legislativa",
                                     url, "verificada", f"Exercício {ano}")
        except Exception:
            pass
    print(f"[{c['nome']}] SICONFI/DCA indisponível — demo", file=sys.stderr)
    return bloco(demo_fin(c)[4], "SICONFI/DCA", SICONFI, "demo")


PESOS_TIPO = {
    "alta": ["projeto de lei", "emenda", "substitutivo"],
    "baixa": ["indicaç", "moção", "mocao", "voto de", "homenagem", "pesar", "congratula"],
}


def classificar_peso(nome_tipo):
    t = (nome_tipo or "").lower()
    for chave in PESOS_TIPO["baixa"]:
        if chave in t:
            return "baixa"
    for chave in PESOS_TIPO["alta"]:
        if chave in t:
            return "alta"
    return "media"


def coletar_proposicoes(c):
    sapl = c.get("sapl")
    if not sapl:
        return bloco(DEMO_PROPS, "Portal da Câmara — sistema próprio, conector em desenvolvimento",
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
            cont = {}
            for m in mats:
                t = m.get("tipo")
                nome_tipo = tipos.get(t, str(t)) if not isinstance(t, dict) else t.get("descricao", "")
                cont[nome_tipo] = cont.get(nome_tipo, 0) + 1
            props = [{"tipo": t, "qtd": q, "peso": classificar_peso(t)}
                     for t, q in sorted(cont.items(), key=lambda x: -x[1])]
            print(f"[{c['nome']}] SAPL: {len(mats)} matérias de {a}")
            return bloco(props, "SAPL — Câmara Municipal",
                         f"{sapl}/materia/pesquisar-materia?ano={a}", "verificada",
                         f"Ano {a}")
        except Exception as e:
            print(f"[{c['nome']}] SAPL matérias {a} falhou: {e}", file=sys.stderr)
    return bloco(DEMO_PROPS, "SAPL (indisponível no momento)", sapl, "demo")


def coletar_producao_vereadores(c):
    """Produção por vereador — só com SAPL: nome real + link verificável."""
    sapl = c.get("sapl")
    if not sapl:
        return bloco([], "Portal da Câmara — sem API de autoria",
                     f"https://www.{slug(c['nome'])}.{c['uf'].lower()}.leg.br", "demo",
                     "Nomes de vereadores só são publicados com fonte oficial verificável.")
    ano = datetime.now().year
    for a in (ano, ano - 1):
        try:
            parls = _sapl_paginar(f"{sapl}/api/parlamentar/parlamentar/?page_size=100", 5)
            nomes_parl = {p.get("nome_parlamentar") or p.get("nome_completo", "")
                          for p in parls}
            autores = {x["id"]: x.get("nome", "")
                       for x in _sapl_paginar(f"{sapl}/api/base/autor/?page_size=100", 10)}
            tipos = {t["id"]: t.get("descricao") or t.get("sigla", "")
                     for t in _sapl_paginar(f"{sapl}/api/materia/tipomaterialegislativa/?page_size=100", 5)}
            mats = _sapl_paginar(f"{sapl}/api/materia/materialegislativa/?ano={a}&page_size=100")
            if not mats:
                continue
            def _norm(s):
                s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
                return " ".join(s.lower().split())

            parl_norm = {_norm(x) for x in nomes_parl if x}

            def eh_parlamentar(nome):
                n = _norm(nome)
                if not n:
                    return False
                if n in parl_norm:
                    return True
                # nome do cadastro de autores pode ser mais longo/curto
                return any(p and (p in n or n in p) for p in parl_norm)

            NAO_PARLAMENTAR = ("prefeit", "executivo", "comiss", "mesa",
                               "camara municipal", "câmara municipal",
                               "secretar", "poder", "procurador")

            def monta_agg(filtro):
                agg = {}
                for m in mats:
                    t = m.get("tipo")
                    nome_tipo = tipos.get(t, str(t)) if not isinstance(t, dict) else t.get("descricao", "")
                    peso = classificar_peso(nome_tipo)
                    for aid in (m.get("autores") or []):
                        nome = autores.get(aid, "")
                        if not filtro(nome):
                            continue
                        v = agg.setdefault(aid, {"nome": nome, "alta": 0, "media": 0,
                                                 "baixa": 0, "total": 0})
                        v[peso] += 1
                        v["total"] += 1
                return agg

            agg = monta_agg(eh_parlamentar)
            if not agg:
                # plano B: todos os autores, exceto órgãos (Prefeito, comissões…)
                agg = monta_agg(lambda nome: nome and not any(
                    x in _norm(nome) for x in NAO_PARLAMENTAR))
            if not agg:
                continue
            lista = sorted(agg.values(), key=lambda v: (-v["alta"], -v["total"]))
            for aid, v in agg.items():
                v["link"] = f"{sapl}/materia/pesquisar-materia?autoria__autor={aid}&ano={a}"
            print(f"[{c['nome']}] SAPL autoria: {len(lista)} vereadores com produção em {a}")
            return bloco(lista, "SAPL — autoria por parlamentar",
                         f"{sapl}/parlamentar/", "verificada", f"Ano {a}")
        except Exception as e:
            print(f"[{c['nome']}] SAPL autoria {a} falhou: {e}", file=sys.stderr)
    return bloco([], "SAPL (autoria indisponível no momento)", sapl, "demo")


def coletar_diario_oficial(c):
    """Querido Diário (Open Knowledge Brasil) — Diários Oficiais indexados."""
    url = (f"https://queridodiario.ok.org.br/api/gazettes?"
           f"territory_ids={c['ibge']}&size=1")
    link = f"https://queridodiario.ok.org.br/pesquisa/?territory_ids={c['ibge']}"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        total = r.json().get("total_gazettes", 0)
        if total:
            return bloco(total, "Querido Diário — Open Knowledge Brasil",
                         link, "verificada", "Edições do Diário Oficial indexadas")
    except Exception as e:
        print(f"[{c['nome']}] Querido Diário falhou: {e}", file=sys.stderr)
    return bloco(0, "Querido Diário", link, "demo",
                 "Cidade ainda não coberta pelo Querido Diário")


# ───────────── Nota da cidade ─────────────
# Tabela do art. 29, IV da CF (redação da EC 58/2009): teto de vereadores
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
    return 0.045


def avaliar(c):
    pop_b = coletar_populacao(c)
    fin = coletar_rreo(c)
    custo_b = coletar_custo_camara(c)
    props_b = coletar_proposicoes(c)
    prod_b = coletar_producao_vereadores(c)

    pop = pop_b["valor"]
    n_ver = c.get("vereadores") or vereadores_teto(pop)
    ver_estimado = c.get("vereadores") is None
    dia_b = coletar_diario_oficial(c)
    rc, dt = fin["receita"]["valor"], fin["despesa"]["valor"]
    base, cc = fin["base29a"]["valor"], custo_b["valor"]

    limite = limite_art_29a(pop)
    uso = cc / base if base else None
    resultado = rc - dt
    margem = resultado / rc if rc else 0

    lista = props_b["valor"]
    total = sum(p["qtd"] for p in lista)
    altas = sum(p["qtd"] for p in lista if p["peso"] == "alta")
    indice_prop = altas / total if total else 0

    # Pilares (0-100) — fórmulas transparentes e publicadas no site:
    # Fiscal: 50 pts no equilíbrio; +-4 pts por ponto percentual de margem
    nota_fiscal = clamp(50 + margem * 400)
    # Custo legislativo: 100 se custo zero, 0 se consumir todo o teto
    nota_custo = clamp((1 - (uso / limite)) * 100) if uso is not None else 0
    # Produção: 100 quando 30% das peças têm peso alto
    nota_prod = clamp(indice_prop / 0.30 * 100)

    nota = 0.4 * nota_fiscal + 0.3 * nota_custo + 0.3 * nota_prod

    blocos = [pop_b, fin["receita"], fin["despesa"], fin["base29a"], custo_b, props_b, prod_b]
    verificados = sum(1 for b in blocos if b["status"] == "verificada")
    confianca = verificados / len(blocos)

    selo = ("VIÁVEL" if nota >= 70 else "ATENÇÃO" if nota >= 45 else "CRÍTICO")

    return {
        **c,
        "vereadores": n_ver,
        "vereadores_estimado": ver_estimado,
        "diario_oficial": dia_b,
        "populacao": pop_b,
        "financas": fin,
        "custo_camara": custo_b,
        "proposicoes": props_b,
        "producao_vereadores": prod_b,
        "indicadores": {
            "resultado_fiscal": resultado,
            "margem_fiscal": margem,
            "limite_art29a": limite,
            "uso_limite": uso,
            "custo_por_habitante": cc / pop,
            "custo_por_vereador": cc / n_ver,
            "indice_propositivo": indice_prop,
        },
        "nota": {
            "final": round(nota, 1),
            "fiscal": round(nota_fiscal, 1),
            "custo_legislativo": round(nota_custo, 1),
            "producao_legislativa": round(nota_prod, 1),
            "selo": selo,
            "confianca": round(confianca, 2),  # % dos blocos com fonte verificada
        },
    }


# ═════════════════════════════════════════════
# GERADOR DE PÁGINAS ESTÁTICAS (SEO)
# Domínio: fiscalizaosmunicipios.com.br
# Cada cidade vira uma URL própria com título que
# responde às buscas reais do Google.
# ═════════════════════════════════════════════
DOMINIO = "https://fiscalizaosmunicipios.com.br"
MARCA = "Fiscaliza os Municípios"

COR = {"VIÁVEL": "#1E6B4F", "ATENÇÃO": "#B0731A", "CRÍTICO": "#C22F2A"}


def _brl(v):
    return "—" if v is None else "R$ " + f"{v:,.0f}".replace(",", ".")


def _num(v):
    return "—" if v is None else f"{v:,.0f}".replace(",", ".")


def _pct(v):
    return "—" if v is None else f"{v*100:.1f}".replace(".", ",") + "%"


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
<p class="rodape">{MARCA} · fiscalizaosmunicipios.com.br · projeto cívico de código aberto · dados públicos (LAI e Lei da Transparência)</p>
</body>
</html>"""


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
                 f"({_brl(ind['custo_por_habitante'])} por habitante). Gestão fiscal, "
                 f"gastos dos vereadores e produção legislativa com fontes oficiais "
                 f"(SICONFI, IBGE).")

    props_html = "".join(
        _linha(f"{p['tipo']} ({p['peso']})", _num(p["qtd"])) for p in c["proposicoes"]["valor"]
    )
    uso_pct = min((ind["uso_limite"] / ind["limite_art29a"]) * 100, 100) if ind["uso_limite"] else 0
    cor_uso = "#1E6B4F" if ind["uso_limite"] and ind["uso_limite"] <= ind["limite_art29a"] else "#C22F2A"
    ok_prod = ind["indice_propositivo"] >= 0.15
    prelim = ("" if n["confianca"] >= 1 else
              f'<div class="conf">nota preliminar — {n["confianca"]:.0%} das fontes verificadas</div>')

    prod = c.get("producao_vereadores") or {}
    if prod.get("status") == "verificada" and prod.get("valor"):
        max_alta = max(v["alta"] for v in prod["valor"]) or 1
        linhas_v = ""
        for pos_v, v in enumerate(prod["valor"], 1):
            largura = (v["alta"] / max_alta * 100) if max_alta else 0
            linhas_v += (
                f'<div class="ver"><div class="ver-topo">'
                f'<span class="ver-nome">{pos_v}º · {v["nome"]}</span>'
                f'<span class="ver-efic">{v["alta"]} de peso alto</span></div>'
                f'<div class="ver-detalhe">{v["total"]} proposições no ano — '
                f'{v["alta"]} peso alto · {v["media"]} médio · {v["baixa"]} baixo · '
                f'<a href="{v["link"]}" target="_blank" rel="noreferrer">conferir no portal oficial</a></div>'
                f'<div class="ver-barra"><div style="width:{largura:.0f}%"></div></div></div>'
            )
        vers_html = (
            f'<h2 style="margin-top:26px">Produção por vereador {_selo_html("verificada")}</h2>'
            f'<p class="sub">{prod.get("detalhe","")} · ordenado por proposições de peso alto '
            f'(PLs, PLCs, emendas) · fonte: <a href="{prod["url"]}" target="_blank" rel="noreferrer">SAPL da Câmara</a></p>'
            + linhas_v +
            '<p class="legenda" style="margin-top:10px">Cada link abre a lista oficial de proposições do vereador no portal da Câmara — confira qualquer número na fonte. Homenagens, moções e indicações contam como peso baixo.</p>'
        )
    else:
        vers_html = ('<div class="nota">Produção individual por vereador: esta Câmara usa sistema próprio, '
                     'sem API pública de autoria — o conector está em desenvolvimento. '
                     'Nomes de vereadores só são publicados com fonte oficial verificável.</div>')

    dia = c.get("diario_oficial") or {}
    diario_txt = (f" — {_num(dia['valor'])} edições indexadas"
                  if dia.get("status") == "verificada" and dia.get("valor") else "")

    corpo = f"""<a class="voltar" href="../index.html">← voltar ao ranking</a>
<header class="cabecalho">
  <div class="protocolo">RETRATO DO MUNICÍPIO · {pos}º DE {total} NO RANKING · ATUALIZADO EM {gerado_em[:10]}</div>
  <h1>{c['nome']} — {c['uf']}
    <small>{_num(c['populacao']['valor'])} habitantes {_selo_html(c['populacao']['status'])} · {'≈ ' if c.get('vereadores_estimado') else ''}{c['vereadores']} vereadores{' (teto do art. 29 da CF — confirmar na Lei Orgânica)' if c.get('vereadores_estimado') else ''}</small>
  </h1>
  <div class="carimbo" style="color:{cor}">{n['selo']}</div>
  <span class="nota-grande" style="color:{cor}">nota {n['final']}/100</span>
  {prelim}
</header>

<section>
  <h2>Gestão fiscal — Executivo {_selo_html(rc['status'])}</h2>
  <p class="sub">{rc.get('detalhe') or 'RREO/SICONFI (Tesouro Nacional)'} · pilar vale 40% da nota ({n['fiscal']}/100)</p>
  {_linha("Receita corrente realizada", _brl(rc['valor']))}
  {_linha("Despesa total liquidada", _brl(dt['valor']))}
  {_linha("Resultado", _brl(ind['resultado_fiscal']), ind['resultado_fiscal'] < 0)}
  {_linha("Margem fiscal", _pct(ind['margem_fiscal']), ind['margem_fiscal'] < 0)}
</section>

<section>
  <h2>Quanto custa a Câmara Municipal {_selo_html(cc['status'])}</h2>
  <p class="sub">Teto do art. 29-A da CF: {_pct(ind['limite_art29a'])} da receita tributária ampliada · pilar vale 30% da nota ({n['custo_legislativo']}/100)</p>
  <div class="barra"><div style="width:{uso_pct:.0f}%;background:{cor_uso}"></div></div>
  <p class="legenda">Uso do teto: {_pct(ind['uso_limite'])} de {_pct(ind['limite_art29a'])} permitidos</p>
  {_linha("Custo anual da função Legislativa", _brl(cc['valor']))}
  {_linha("Custo por habitante / ano", _brl(ind['custo_por_habitante']))}
  {_linha("Custo por vereador / ano", _brl(ind['custo_por_vereador']))}
</section>

<section>
  <h2>O que os vereadores estão propondo {_selo_html(c['proposicoes']['status'])}</h2>
  <p class="sub">Proposições por peso real de transformação · pilar vale 30% da nota ({n['producao_legislativa']}/100)</p>
  {props_html}
  <div class="barra"><div style="width:{min(ind['indice_propositivo']/0.30*100,100):.0f}%;background:{'#1E6B4F' if ok_prod else '#C22F2A'}"></div></div>
  <p class="legenda">Índice propositivo: {_pct(ind['indice_propositivo'])} das peças têm peso alto (PLs, emendas). Homenagens, moções e indicações não contam ponto.</p>
  {vers_html}
</section>

<section class="fontes">
  <h2>Fontes e verificação</h2>
  <ul>
    <li><a href="{rc['url']}" target="_blank" rel="noreferrer">SICONFI — consulta de receitas/despesas usada nesta página</a></li>
    <li><a href="{cc['url']}" target="_blank" rel="noreferrer">SICONFI/DCA — custo da função Legislativa</a></li>
    <li><a href="{c['populacao']['url']}" target="_blank" rel="noreferrer">API IBGE — população</a></li>
    <li><a href="{c['proposicoes']['url']}" target="_blank" rel="noreferrer">Portal da Câmara — proposições</a></li>
    <li><a href="{(c.get('diario_oficial') or {}).get('url','#')}" target="_blank" rel="noreferrer">Querido Diário — Diário Oficial do município</a>{diario_txt}</li>
    <li><a href="https://divulgacandcontas.tse.jus.br" target="_blank" rel="noreferrer">TSE / DivulgaCandContas — bens e campanhas dos eleitos</a></li>
    <li><a href="https://radardatransparencia.atricon.org.br" target="_blank" rel="noreferrer">Radar da Transparência Pública (Atricon) — portal auditado da cidade</a></li>
  </ul>
  <div class="nota">Números com "✓ fonte oficial" foram coletados automaticamente na data indicada; os links abrem exatamente a consulta usada — qualquer pessoa pode conferir.</div>
</section>"""
    return s, url, _shell(titulo, descricao, url, corpo, raiz="../")


def pagina_index(dados):
    cidades = dados["cidades"]
    titulo = f"Ranking das cidades mais bem geridas | {MARCA}"
    descricao = ("Quanto custa a Câmara da sua cidade? Ranking de municípios por gestão "
                 "fiscal, gastos dos vereadores e produção legislativa — só com dados "
                 "públicos verificáveis (SICONFI, IBGE, Câmaras).")
    itens = []
    for i, c in enumerate(cidades, 1):
        n = c["nota"]
        s = slug(c["nome"]) + "-" + c["uf"].lower()
        cor = COR[n["selo"]]
        prelim = ("" if n["confianca"] >= 1 else
                  f'<div class="conf">nota preliminar — {n["confianca"]:.0%} das fontes verificadas</div>')
        pil = "".join(
            f'<div class="pilar"><div class="pilar-rotulo">{r} · {v}</div>'
            f'<div class="pilar-barra"><div style="width:{v:.0f}%"></div></div></div>'
            for r, v in [("Gestão fiscal", n["fiscal"]),
                         ("Custo do legislativo", n["custo_legislativo"]),
                         ("Produção legislativa", n["producao_legislativa"])]
        )
        itens.append(f"""<a class="cidade" href="cidades/{s}.html">
  <div class="topo"><span class="pos">{i}º</span><span class="nome">{c['nome']} — {c['uf']}{' · capital' if c.get('capital') else ''}</span>
  <span class="selo-cidade" style="color:{cor}">{n['selo']}</span>
  <span class="nota-rank" style="color:{cor}">{str(n['final']).replace('.', ',')}</span></div>
  <div class="pilares">{pil}</div>{prelim}</a>""")

    corpo = f"""<header class="cabecalho">
  <div class="protocolo">{MARCA.upper()} · BASE DE PESQUISA CÍVICA</div>
  <h1>Quais cidades são bem geridas?
    <small>{len(cidades)} cidades analisadas · atualizado em {dados['gerado_em'][:10]} · gestão fiscal, custo do legislativo e produção dos vereadores, com dados públicos verificáveis</small>
  </h1>
</header>
<div class="metodo"><b>Como a nota é calculada:</b> 40% gestão fiscal (equilíbrio das contas — responsabilidade do Executivo),
30% custo do legislativo (fração usada do teto do art. 29-A da CF) e
30% produção legislativa (proposições de peso vs. homenagens).
Cidades com fontes ainda não verificadas aparecem com nota preliminar.</div>
{''.join(itens)}"""
    return _shell(titulo, descricao, DOMINIO + "/", corpo)


def gerar_site(dados):
    import os
    os.makedirs("docs/cidades", exist_ok=True)
    urls = [DOMINIO + "/"]
    for i, c in enumerate(dados["cidades"], 1):
        s, url, html = pagina_cidade(c, i, len(dados["cidades"]), dados["gerado_em"])
        with open(f"docs/cidades/{s}.html", "w", encoding="utf-8") as fh:
            fh.write(html)
        urls.append(url)
    with open("docs/index.html", "w", encoding="utf-8") as fh:
        fh.write(pagina_index(dados))
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
    print(f"✓ site gerado: index + {len(urls)-1} páginas de cidade + sitemap + robots + CNAME")


if __name__ == "__main__":
    cidades = []
    for c in CIDADES:
        print(f"→ Coletando {c['nome']}-{c['uf']}…")
        if not resolver_ibge(c):
            print(f"  (pulada: sem código IBGE)")
            continue
        cidades.append(avaliar(c))
        time.sleep(2)

    ranking = sorted(cidades, key=lambda x: -x["nota"]["final"])
    saida = {
        "gerado_em": agora(),
        "metodologia": {
            "pesos": {"gestao_fiscal": 0.4, "custo_legislativo": 0.3,
                      "producao_legislativa": 0.3},
            "descricao": (
                "Gestão fiscal: equilíbrio receita×despesa (Executivo). "
                "Custo do legislativo: fração consumida do teto do art. 29-A da CF. "
                "Produção legislativa: proporção de proposições de peso alto "
                "(PLs, emendas) sobre o total — homenagens e indicações não contam. "
                "Confiança: fração dos dados com fonte oficial verificada; "
                "notas com confiança < 1 são preliminares."
            ),
        },
        "cidades": ranking,
    }
    with open("docs/dados.json", "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=2)
    print("\n✓ docs/dados.json gerado")
    gerar_site(saida)
    for i, x in enumerate(ranking, 1):
        n = x["nota"]
        print(f"  {i}º {x['nome']}-{x['uf']}: {n['final']} ({n['selo']}, confiança {n['confianca']:.0%})")
