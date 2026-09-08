# Fiscaliza os Municípios — Arquitetura Técnica e Metodológica v2.0

**Sistema de inteligência cívica e fiscalização municipal**
Documento de referência: metodologia de pontuação, integração de fontes, modelagem de dados, avaliação de impacto e classificação automática de proposições.

---

## 0. Princípios de projeto

O sistema obedece a quatro princípios inegociáveis, herdados do protótipo em produção (fiscalizaosmunicipios.com.br):

**Verificabilidade radical.** Todo número publicado carrega metadados de proveniência (fonte, URL exata da consulta, data da coleta, status). O leitor confere qualquer dado na fonte oficial em um clique.

**Chave primária universal.** O código IBGE de 7 dígitos do município é a chave de integração de todas as fontes. Nenhum dado entra no sistema sem estar amarrado a um código IBGE válido.

**Honestidade metodológica.** Dados ausentes rebaixam o índice de confiança da nota, nunca são inventados. Estimativas (ex.: nº de vereadores pelo teto constitucional) são rotuladas como tais.

**Pessoas só com fonte.** Estatísticas atribuídas a vereadores nominais exigem link para o registro oficial da proposição/gasto. Associação estatística nunca é publicada como causalidade individual.

---

## 1. Metodologia de cálculo da Nota Final (0–100)

### 1.1 Fórmula geral

```
NOTA = 0,40 · F  +  0,30 · C  +  0,30 · Q

F = Gestão Fiscal (Executivo)
C = Custo do Legislativo
Q = Qualidade da Produção Legislativa
```

Cada dimensão é normalizada para 0–100 antes da ponderação. A nota é acompanhada de um **índice de confiança** (fração dos blocos de dados com fonte verificada), exibido junto à nota mas que não a altera — confiança < 100% rotula a nota como *preliminar*.

### 1.2 Dimensão F — Gestão Fiscal (peso 40%)

Três subcomponentes, com dados do SICONFI (RREO/RGF/DCA):

```
F = 0,50 · F_eq  +  0,30 · F_pes  +  0,20 · F_inv
```

**F_eq — Equilíbrio orçamentário.** Margem fiscal m = (Receita Corrente − Despesa Liquidada) / Receita Corrente:

```
F_eq = clamp( 50 + 400·m , 0, 100 )
```
Equilíbrio exato vale 50; cada ponto percentual de superávit soma 4 pontos; déficit subtrai na mesma razão. (Fórmula já em produção.)

**F_pes — Despesa com pessoal (LRF).** A Lei de Responsabilidade Fiscal limita a despesa de pessoal do Executivo municipal a 54% da Receita Corrente Líquida (art. 20, III, b). Sendo p = DespesaPessoalExecutivo / RCL (fonte: RGF, Anexo 1):

```
F_pes = clamp( (0,54 − p) / 0,54 · 100 · k , 0, 100 ),  k = 2,5
```
O fator k=2,5 faz a nota zerar apenas quando p ≥ 54% e atingir 100 quando p ≤ 32,4% — calibrado para que o limite prudencial (51,3%) valha ~12 pontos, criando gradiente punitivo na zona de alerta.

**F_inv — Capacidade de investimento.** Taxa i = DespesasDeCapital_Investimentos / Receita Corrente (RREO Anexo 01):

```
F_inv = clamp( i / 0,12 · 100 , 0, 100 )
```
Investir 12% ou mais da receita corrente vale nota máxima (referência: mediana histórica dos municípios superavitários fica entre 8–15%).

### 1.3 Dimensão C — Custo do Legislativo (peso 30%)

```
C = 0,50 · C_teto  +  0,30 · C_folha  +  0,20 · C_rel
```

**C_teto — Uso do teto do art. 29-A da CF/88.** O repasse à Câmara é limitado a um percentual L da receita tributária ampliada do exercício anterior (7% até 100 mil hab.; 6% até 300 mil; 5% até 500 mil; 4,5% até 3 mi; 4% até 8 mi; 3,5% acima). Sendo u = RepasseCâmara / BaseArt29A:

```
C_teto = clamp( (1 − u/L) · 100 , 0, 100 )
```

**C_folha — Folha do Legislativo (LRF).** A despesa de pessoal do Legislativo municipal é limitada a 6% da RCL (LRF art. 20, III, a). Sendo q = DespesaPessoalLegislativo / RCL (fonte: RGF da Câmara, Anexo 1):

```
C_folha = clamp( (0,06 − q) / 0,06 · 100 , 0, 100 )
```
O art. 29-A, §1º também proíbe que a folha (incluído o subsídio dos vereadores) ultrapasse 70% do repasse — violação desse teto zera C_folha independentemente do resultado da fórmula.

**C_rel — Custo relativo ao grupo de comparação.** Custo por habitante comparado a municípios do mesmo estrato populacional (os 6 estratos do art. 29-A). Sendo P_i o percentil do município dentro do estrato (0 = mais barato):

```
C_rel = 100 − P_i
```
Esse componente captura verbas de gabinete e estruturas infladas que cabem dentro dos tetos legais mas destoam dos pares — o caso típico de Câmaras "legais porém caras".

### 1.4 Dimensão Q — Qualidade da Produção Legislativa (peso 30%)

```
Q = 0,50 · Q_prop  +  0,30 · Q_aprov  +  0,20 · Q_tema
```

**Q_prop — Índice propositivo ponderado.** Cada proposição do ano recebe peso w pela classificação (seção 5): estrutural w=1,0; regulatória/fiscalizatória w=0,6; simbólica (homenagens, moções, denominações, datas) w=0,0. Sendo W = Σw/N a média dos pesos:

```
Q_prop = clamp( W / 0,35 · 100 , 0, 100 )
```
Calibração: uma Câmara cuja produção média pondere 0,35 (ex.: 25% estrutural + 25% regulatória + 50% simbólica) atinge nota máxima — meta exigente porém observada em Câmaras produtivas.

**Q_aprov — Efetividade.** Taxa de proposições de peso ≥ 0,6 que viraram norma jurídica (sanção/promulgação) em até 24 meses, via ligação matéria→norma no SAPL:

```
Q_aprov = clamp( aprovadas_peso_alto / apresentadas_peso_alto · 100 · 1,25 , 0, 100 )
```

**Q_tema — Aderência temática.** Entropia normalizada da distribuição de temas (Saúde, Educação, Saneamento, Mobilidade, Assistência, Administração) nas proposições estruturais. Produção concentrada num único tema (frequentemente Administração — cargos e estrutura interna) pontua menos que produção diversificada voltada a serviços públicos:

```
Q_tema = H(temas) / H_max · 100 ,  H = entropia de Shannon
```

### 1.5 Selo e apresentação

```
NOTA ≥ 70 → VIÁVEL   ·   45 ≤ NOTA < 70 → ATENÇÃO   ·   NOTA < 45 → CRÍTICO
```

---

## 2. Fontes de dados e arquitetura de ingestão

### 2.1 Mapa de fontes

| Domínio | Fonte | Método | Periodicidade | Chave |
|---|---|---|---|---|
| Finanças (receita, despesa, pessoal) | SICONFI — RREO/RGF/DCA | API REST (`apidatalake.tesouro.gov.br`) | Bimestral/Quadrim./Anual | cod_ibge |
| Auditoria fiscal, folha, licitações | TCE/TCM estaduais (ex.: TCE-SP `transparencia.tce.sp.gov.br/api`) | API JSON + scraping de painéis | Mensal/Anual | cod_ibge |
| Proposições, autoria, tramitação | SAPL/Interlegis (`sapl.<cidade>.<uf>.leg.br/api`) | API DRF paginada | Diária | cod_ibge → id_sapl |
| Câmaras sem SAPL | Portais próprios (SPLegis, Instar, Câmara Sem Papel…) | Conectores de scraping dedicados | Diária | cod_ibge |
| Diários Oficiais (leis publicadas, nomeações) | Querido Diário (OKBR) | API (`queridodiario.ok.org.br/api`) | Diária | territory_id = cod_ibge |
| Saúde — financiamento | SIOPS | API/planilhas DATASUS | Bimestral | cod_ibge |
| Saúde — resultados | TABNET/DATASUS (atenção básica, leitos CNES, cobertura vacinal PNI) | Scraping estruturado TABNET + FTP | Mensal/Anual | cod_ibge |
| Educação — financiamento | SIOPE/FNDE | API/planilhas | Anual | cod_ibge |
| Educação — resultados | INEP Data (IDEB, distorção idade-série, censo escolar/infraestrutura) | Microdados CSV + API | Bienal/Anual | cod_ibge |
| Saneamento | SNIS (água, esgoto, resíduos) | Planilhas/API SNIS | Anual | cod_ibge |
| Obras públicas | Obrasgov.br (Transferegov) | API | Mensal | cod_ibge |
| Perfil eleitoral dos vereadores | TSE — DivulgaCandContas | CSVs consolidados + API | Por eleição | sq_candidato → cpf(hash) → vereador |
| População e território | IBGE (agregados, localidades) | API | Anual | cod_ibge |

### 2.2 Fluxo de dados

```
                     ┌────────────────────────────────────────────┐
                     │                ORQUESTRADOR                 │
                     │   (GitHub Actions/cron → Airflow na fase 3) │
                     └──────┬─────────┬─────────┬─────────┬───────┘
                            ▼         ▼         ▼         ▼
                      ┌─────────┐┌─────────┐┌─────────┐┌─────────┐
   CAMADA DE COLETA   │ conector││ conector││ conector││ conector│ ...
   (1 módulo/fonte)   │ SICONFI ││  SAPL   ││ DATASUS ││  INEP   │
                      └────┬────┘└────┬────┘└────┬────┘└────┬────┘
                           ▼          ▼          ▼          ▼
                     ┌────────────────────────────────────────────┐
   STAGING (bruto)   │  JSON/CSV brutos + hash + timestamp + URL  │
                     │  (imutável — trilha de auditoria)          │
                     └──────────────────┬─────────────────────────┘
                                        ▼
                     ┌────────────────────────────────────────────┐
   NORMALIZAÇÃO      │ • valida cod_ibge  • converte unidades     │
                     │ • deduplica        • NLP classifica PLs    │
                     │ • liga vereador ↔ autor ↔ candidato (TSE)  │
                     └──────────────────┬─────────────────────────┘
                                        ▼
                     ┌────────────────────────────────────────────┐
   BANCO RELACIONAL  │      PostgreSQL (schema da seção 3)        │
                     └──────┬──────────────────────┬──────────────┘
                            ▼                      ▼
                 ┌──────────────────┐   ┌─────────────────────────┐
   ANALÍTICO     │ MOTOR DE NOTAS   │   │ PAINEL ECONOMÉTRICO     │
                 │ (seção 1)        │   │ (defasagem temporal §4) │
                 └────────┬─────────┘   └───────────┬─────────────┘
                          ▼                         ▼
                     ┌────────────────────────────────────────────┐
   PUBLICAÇÃO        │ dados.json + páginas estáticas (SEO) + API │
                     │ pública somente-leitura                    │
                     └────────────────────────────────────────────┘
```

Regras da ingestão: cada conector é idempotente (rodar duas vezes não duplica), grava primeiro no staging bruto (auditável), e registra a coleta na tabela `fonte_coleta` com URL e hash do payload — é isso que alimenta os selos "✓ fonte oficial" do site.

---

## 3. Modelagem de dados relacional

### 3.1 Diagrama lógico

```
 municipio ──< legislatura ──< mandato >── vereador ──< perfil_eleitoral(TSE)
     │                            │
     │                            └──< gasto_gabinete
     │
     ├──< financas_periodo (RREO/RGF/DCA)
     ├──< indicador_social (DATASUS/INEP/SNIS — formato longo)
     ├──< diario_oficial (Querido Diário)
     └──< nota_municipio (resultado do motor, por exercício)

 proposicao >── municipio
 proposicao ──< autoria >── vereador
 proposicao ──1 classificacao_nlp
 proposicao ──< tramitacao
 proposicao ──1? norma_juridica (quando aprovada)

 fonte_coleta: proveniência de toda linha factual (FK em todas as tabelas de fatos)
```

### 3.2 DDL de referência (PostgreSQL)

```sql
CREATE TABLE municipio (
    cod_ibge        CHAR(7) PRIMARY KEY,
    nome            TEXT NOT NULL,
    uf              CHAR(2) NOT NULL,
    populacao_ref   INTEGER,
    estrato_29a     SMALLINT,          -- 1..6, define teto e grupo de comparação
    capital         BOOLEAN DEFAULT FALSE,
    sistema_legis   TEXT,              -- 'SAPL', 'SPLEGIS', 'INSTAR', ...
    url_sapl        TEXT
);

CREATE TABLE fonte_coleta (
    id              BIGSERIAL PRIMARY KEY,
    fonte           TEXT NOT NULL,      -- 'SICONFI/RREO', 'SAPL', 'INEP/IDEB'...
    url_consulta    TEXT NOT NULL,
    coletado_em     TIMESTAMPTZ NOT NULL,
    hash_payload    CHAR(64) NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('verificada','falha'))
);

CREATE TABLE vereador (
    id              BIGSERIAL PRIMARY KEY,
    nome_civil      TEXT NOT NULL,
    nome_parlamentar TEXT,
    cpf_hash        CHAR(64) UNIQUE,    -- liga TSE ↔ Câmara sem expor CPF
    dt_nascimento   DATE
);

CREATE TABLE legislatura (
    id              BIGSERIAL PRIMARY KEY,
    cod_ibge        CHAR(7) REFERENCES municipio,
    ano_inicio      SMALLINT, ano_fim SMALLINT,
    n_cadeiras      SMALLINT,
    n_cadeiras_estimado BOOLEAN DEFAULT FALSE
);

CREATE TABLE mandato (
    id              BIGSERIAL PRIMARY KEY,
    vereador_id     BIGINT REFERENCES vereador,
    legislatura_id  BIGINT REFERENCES legislatura,
    partido         TEXT, situacao TEXT,           -- titular/suplente/licenciado
    UNIQUE (vereador_id, legislatura_id)
);

CREATE TABLE perfil_eleitoral (            -- TSE DivulgaCandContas
    id              BIGSERIAL PRIMARY KEY,
    vereador_id     BIGINT REFERENCES vereador,
    ano_eleicao     SMALLINT,
    sq_candidato    BIGINT,
    bens_declarados NUMERIC(14,2),
    receita_campanha NUMERIC(14,2),
    fonte_id        BIGINT REFERENCES fonte_coleta
);

CREATE TABLE proposicao (
    id              BIGSERIAL PRIMARY KEY,
    cod_ibge        CHAR(7) REFERENCES municipio,
    id_externo      TEXT,                          -- id no SAPL/portal
    tipo            TEXT NOT NULL,                 -- 'PL','PLC','EMENDA','MOCAO',...
    numero          TEXT, ano SMALLINT,
    ementa          TEXT,
    apresentada_em  DATE,
    fonte_id        BIGINT REFERENCES fonte_coleta,
    UNIQUE (cod_ibge, tipo, numero, ano)
);

CREATE TABLE autoria (
    proposicao_id   BIGINT REFERENCES proposicao,
    mandato_id      BIGINT REFERENCES mandato,
    principal       BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (proposicao_id, mandato_id)
);

CREATE TABLE classificacao_nlp (
    proposicao_id   BIGINT PRIMARY KEY REFERENCES proposicao,
    classe          TEXT NOT NULL,       -- 'ESTRUTURAL','REGULATORIA','SIMBOLICA'
    tema            TEXT,                -- 'SAUDE','EDUCACAO','SANEAMENTO',...
    peso            NUMERIC(3,2) NOT NULL,        -- 1.00 / 0.60 / 0.00
    confianca       NUMERIC(4,3) NOT NULL,        -- do classificador
    revisado_humano BOOLEAN DEFAULT FALSE,
    modelo_versao   TEXT
);

CREATE TABLE tramitacao (
    id              BIGSERIAL PRIMARY KEY,
    proposicao_id   BIGINT REFERENCES proposicao,
    data            DATE, unidade TEXT, status TEXT
);

CREATE TABLE norma_juridica (
    id              BIGSERIAL PRIMARY KEY,
    proposicao_id   BIGINT UNIQUE REFERENCES proposicao,
    tipo            TEXT, numero TEXT, ano SMALLINT,
    publicada_em    DATE,
    url_diario      TEXT                 -- link Querido Diário da publicação
);

CREATE TABLE gasto_gabinete (
    id              BIGSERIAL PRIMARY KEY,
    mandato_id      BIGINT REFERENCES mandato,
    competencia     DATE NOT NULL,       -- mês de referência
    categoria       TEXT,                -- 'VERBA_INDENIZATORIA','DIARIA','PESSOAL'
    valor           NUMERIC(14,2) NOT NULL,
    fonte_id        BIGINT REFERENCES fonte_coleta
);

CREATE TABLE financas_periodo (          -- fatos SICONFI/TCE
    id              BIGSERIAL PRIMARY KEY,
    cod_ibge        CHAR(7) REFERENCES municipio,
    exercicio       SMALLINT, periodo SMALLINT,   -- bimestre/quadrimestre; 0=anual
    demonstrativo   TEXT,                -- 'RREO','RGF_EXEC','RGF_LEGIS','DCA'
    conta           TEXT, valor NUMERIC(16,2),
    fonte_id        BIGINT REFERENCES fonte_coleta
);
CREATE INDEX ix_fin ON financas_periodo (cod_ibge, exercicio, demonstrativo, conta);

CREATE TABLE indicador_social (          -- formato longo: 1 linha por indicador/ano
    id              BIGSERIAL PRIMARY KEY,
    cod_ibge        CHAR(7) REFERENCES municipio,
    dominio         TEXT NOT NULL,       -- 'SAUDE','EDUCACAO','SANEAMENTO','OBRAS'
    codigo          TEXT NOT NULL,       -- 'IDEB_AI','COB_VACINAL_PENTA','SNIS_IN055'
    ano             SMALLINT NOT NULL,
    valor           NUMERIC(14,4),
    fonte_id        BIGINT REFERENCES fonte_coleta,
    UNIQUE (cod_ibge, codigo, ano)
);

CREATE TABLE nota_municipio (
    cod_ibge        CHAR(7) REFERENCES municipio,
    exercicio       SMALLINT,
    nota_final      NUMERIC(4,1), f NUMERIC(4,1), c NUMERIC(4,1), q NUMERIC(4,1),
    confianca       NUMERIC(3,2),
    selo            TEXT,
    calculada_em    TIMESTAMPTZ,
    PRIMARY KEY (cod_ibge, exercicio)
);
```

O formato longo de `indicador_social` é deliberado: adicionar um indicador novo (ex.: mortalidade infantil) não altera o schema — apenas insere linhas com novo `codigo`, e o dicionário de indicadores vive numa tabela de metadados.

---

## 4. Avaliação de impacto: painel com defasagem temporal

### 4.1 O problema

A pergunta "a lei do vereador X melhorou o IDEB?" não pode ser respondida com correlação simples: municípios que legislam mais sobre educação frequentemente já estavam melhorando (causalidade reversa), e fatores omitidos (FUNDEB, gestão da secretaria, ciclo econômico) movem os dois lados. O sistema trata isso com **análise em painel** — as mesmas cidades observadas ao longo dos anos — usando a variação *dentro* de cada município.

### 4.2 Especificação de referência

Para um indicador Y (ex.: IDEB anos iniciais) e a produção legislativa temática L (nº ponderado de normas estruturais do tema aprovadas), com defasagem de 1 a 2 anos:

```
Y[i,t] = β1·L[i,t-1] + β2·L[i,t-2] + γ·X[i,t] + μ[i] + λ[t] + ε[i,t]

μ[i] = efeito fixo do município  (absorve tudo que é constante na cidade)
λ[t] = efeito fixo do ano        (absorve choques nacionais: pandemia, FUNDEB novo)
X    = controles variantes: gasto per capita no tema (SIOPE/SIOPS),
       população, receita per capita, execução de obras (Obrasgov)
```

Implementação: `linearmodels.PanelOLS` (Python) com erros-padrão agrupados por município (cluster robusto). A defasagem t−1/t−2 respeita o tempo de maturação de política pública — lei aprovada em 2023 só toca o IDEB de 2025.

### 4.3 Guarda-corpos contra falsa causalidade

**Teste de placebo (leads).** Incluir L[i,t+1] na regressão: se a produção legislativa *futura* "explica" o indicador presente, há tendência pré-existente, não efeito da lei — o resultado é descartado.

**Estudo de eventos.** Para leis marcantes (ex.: criação de programa municipal), plotar o indicador nos anos −3…+3 em torno da aprovação, comparando com municípios do mesmo estrato sem a lei (dif-em-dif com adoção escalonada, estimadores robustos tipo Callaway–Sant'Anna, que evitam o viés de comparações entre adotantes precoces e tardios).

**Dose-resposta.** Efeito deve crescer com a implementação real: cruzar a lei com execução orçamentária (a lei virou empenho? — `financas_periodo`) e com publicações no Diário Oficial (nomeações, regulamentos — Querido Diário). Lei sem execução não deveria "causar" nada; se causar, é ruído.

**Regra editorial.** O site publica os resultados como **associação com metodologia aberta** ("municípios que aprovaram leis estruturais de saneamento apresentaram, dois anos depois, melhora média de X pontos no índice de coleta, controlando por..."), nunca como crédito causal individual a um vereador. O crédito individual publicado se limita ao verificável: autoria, aprovação e execução.

### 4.4 Fluxo do módulo

```
indicador_social ─┐
financas_periodo ─┤→ montagem do painel (município × ano) → PanelOLS FE
norma_juridica  ──┤        │
classificacao_nlp ┘        ├→ testes: placebo leads, dif-em-dif escalonado
                           └→ tabela resultado_painel (coef, IC95%, n, versão)
                                    → camada de publicação (com nota metodológica)
```

---

## 5. Pipeline de NLP para classificação de proposições

### 5.1 Taxonomia de saída

```
CLASSE (peso na nota)                 TEMA (quando classe ≠ SIMBOLICA)
─ ESTRUTURAL   (1,0)  cria/altera     SAUDE · EDUCACAO · SANEAMENTO ·
  política pública, serviço, obra     MOBILIDADE · ASSISTENCIA ·
─ REGULATORIA  (0,6)  fiscaliza,      MEIO_AMBIENTE · SEGURANCA ·
  regulamenta, organiza a gestão      ADMINISTRACAO · TRIBUTARIO
─ SIMBOLICA    (0,0)  homenagens,
  moções, denominações, datas
```

### 5.2 Arquitetura em três estágios (precisão > recall no estágio barato)

**Estágio 1 — Regras de alta precisão.** Padrões regex na ementa capturam a maior parte das simbólicas com precisão ~99% (denominações de via e datas comemorativas são fórmulas fixas na redação legislativa brasileira). O que casar aqui não vai ao modelo.

**Estágio 2 — Classificador supervisionado.** Baseline TF-IDF + SVM linear treinado num corpus rotulado (500–1.000 ementas anotadas manualmente cobre bem; a linguagem de ementa é padronizada). Evolução: fine-tuning de BERTimbau (`neuralmind/bert-base-portuguese-cased`), que capta ementas ambíguas.

**Estágio 3 — Humano no circuito.** Predições com confiança < 0,80 caem numa fila de revisão manual; cada revisão realimenta o corpus (`revisado_humano = TRUE`). A versão do modelo fica gravada em `classificacao_nlp.modelo_versao` — reclassificações são reproduzíveis.

### 5.3 Implementação de referência

```python
import re, joblib
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV

# ── Estágio 1: regras de alta precisão para SIMBOLICA ──
PADROES_SIMBOLICA = [
    r"\bden[oô]mina\b.*\b(rua|avenida|pra[çc]a|viaduto|escola|pr[óo]prio)",
    r"\bmo[çc][ãa]o de (aplauso|congratula|pesar|repúdio|louvor)",
    r"\bvoto de (congratula|pesar|louvor)",
    r"\binstitui\b.*\b(dia|semana|m[êe]s) (municipal )?(do|da|de)\b",
    r"\bt[íi]tulo de cidad[ãa]o\b|\bhonra ao m[ée]rito\b|\bcomenda\b",
]
RX = [re.compile(p, re.I) for p in PADROES_SIMBOLICA]

TEMAS = {
    "SAUDE": r"sa[úu]de|sus\b|ubs|vacin|hospital|m[ée]dic",
    "EDUCACAO": r"educa|escola|ensino|creche|professor|merenda",
    "SANEAMENTO": r"saneamento|esgoto|[áa]gua pot|res[íi]duo|drenagem",
    "MOBILIDADE": r"tr[âa]nsito|transporte|ciclovia|pavimenta|mobilidade",
    "ASSISTENCIA": r"assist[êe]ncia social|vulnerab|crianca|idoso|mulher",
    "MEIO_AMBIENTE": r"ambiental|arboriza|clima|polui",
    "TRIBUTARIO": r"iptu|iss\b|taxa|tribut|isen[çc]",
    "ADMINISTRACAO": r"cargo|servidor|estrutura administrativa|plano de carreira",
}

def classificar(ementa: str, modelo) -> dict:
    if any(rx.search(ementa) for rx in RX):
        return {"classe": "SIMBOLICA", "tema": None, "peso": 0.0,
                "confianca": 0.99, "estagio": "regra"}
    # ── Estágio 2: modelo calibrado (probabilidades reais) ──
    proba = modelo.predict_proba([ementa])[0]
    classe = modelo.classes_[proba.argmax()]
    conf = float(proba.max())
    tema = next((t for t, p in TEMAS.items() if re.search(p, ementa, re.I)), None)
    peso = {"ESTRUTURAL": 1.0, "REGULATORIA": 0.6, "SIMBOLICA": 0.0}[classe]
    return {"classe": classe, "tema": tema, "peso": peso,
            "confianca": conf,
            "estagio": "modelo" if conf >= 0.80 else "revisao_humana"}

def treinar(ementas, rotulos):
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True,
                                  min_df=2, strip_accents="unicode")),
        ("clf", CalibratedClassifierCV(LinearSVC(class_weight="balanced"))),
    ])
    pipe.fit(ementas, rotulos)
    joblib.dump(pipe, "modelo_proposicoes_v1.joblib")
    return pipe
```

O classificador alimenta diretamente `Q_prop` e `Q_tema` (seção 1.4) e o filtro de leis estruturais do painel econométrico (seção 4).

---

## 6. Roadmap de implantação

O sistema em produção hoje (coletor Python + GitHub Actions diário + site estático com selos de verificação) é o embrião das camadas de coleta e publicação deste documento. A evolução recomendada preserva o que funciona:

**Fase A (atual → +2 meses).** Migrar o armazenamento de `dados.json` para SQLite versionado no próprio repositório usando o schema da seção 3 (Postgres só quando o volume exigir); ativar RGF (folha Executivo/Legislativo) e completar F_pes, C_folha; anotar as primeiras 500 ementas e treinar o classificador v1.

**Fase B (+2 → +6 meses).** Conectores TCE-SP (gastos de gabinete e folha auditada), SIOPS/SIOPE, INEP e SNIS alimentando `indicador_social`; expansão para todas as Câmaras com SAPL do país (varredura do domínio `*.leg.br` do Interlegis); vínculo TSE↔vereador por nome+município+partido com hash de CPF quando disponível.

**Fase C (+6 → +12 meses).** Painel econométrico com 3+ anos de série própria; publicação dos primeiros estudos de associação com nota metodológica; API pública somente-leitura; migração do orquestrador para Airflow se o nº de conectores passar de ~20.

---

*Documento vivo — versão 2.0. Alterações de metodologia devem ser versionadas e anunciadas no site: mudança de fórmula muda ranking, e transparência sobre a régua é tão importante quanto sobre os dados.*
