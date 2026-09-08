# Radar dos Municípios

Base de pesquisa cívica: ranking de cidades por gestão fiscal, custo do legislativo e produção dos vereadores — com dados públicos verificáveis.

- **Coletor** (`coletor.py`): busca população (IBGE), receitas/despesas (SICONFI/RREO),
  custo da função Legislativa (SICONFI/DCA) e proposições (SAPL da Câmara, quando
  disponível). Gera `docs/dados.json` com metadados de verificação em cada número.
- **Site** (`docs/index.html`): página estática que lê o JSON e mostra veredicto,
  indicadores fiscais, produção legislativa e eficiência dos vereadores.
- **Automação** (`.github/workflows/coleta.yml`): roda o coletor todo dia às 06:00
  (Brasília) e publica o resultado sozinho.

## Rodar localmente

```bash
pip install requests
python coletor.py
# abra docs/index.html no navegador (ou: python -m http.server -d docs)
```

## Pôr no ar (grátis, ~15 minutos)

1. **Crie uma conta no GitHub** (github.com) se ainda não tiver.
2. **Crie um repositório novo** — ex.: `radar-municipios` — marcado como **Public**.
3. **Envie estes arquivos** (botão *Add file → Upload files*, arrastando a pasta
   inteira, inclusive `.github/`).
4. **Ative o site**: *Settings → Pages → Source: Deploy from a branch →
   Branch: `main` / pasta `/docs` → Save*.
5. **Ative a automação**: aba *Actions → habilitar workflows → Coleta diária →
   Run workflow* (primeira rodada manual).
6. Pronto. O site fica em `https://fiscalizaosmunicipios.com.br` (após configurar o DNS — ver abaixo)
   e se atualiza sozinho todos os dias.

### Domínio próprio (opcional)
Registre um domínio (ex.: `fiscalizacamara.com.br` no Registro.br, ~R$ 40/ano),
aponte um CNAME para `SEU-USUARIO.github.io` e cadastre-o em *Settings → Pages →
Custom domain*.

## Princípio inegociável

Estatística individual de vereador **só é publicada com nome real quando cada
número tiver link para a proposição no portal oficial** da Câmara. Enquanto a
coleta de autoria não estiver verificada, os nomes ficam anonimizados e o bloco
é marcado como demonstração.

## Próximas fases

1. Coleta de autoria por vereador via SAPL (substitui a demonstração).
2. "Impacto verificado": cruzar leis aprovadas com execução orçamentária e
   indicadores setoriais (a lei saiu do papel?).
3. Multi-cidades: transformar `CIDADE` em lista e gerar uma página por município.
