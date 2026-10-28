# Radar Cordeiro — painel automatizado

O Radar Cordeiro busca todo dia notícias que sinalizam demanda por locação de guindastes e área
(energia, portos, mineração, indústria, logística, saneamento, óleo e gás e infraestrutura) e grava
tudo num banco SQLite. Um painel em Streamlit, no visual da newsletter, mostra o resultado.

```
app.py                     painel Streamlit (só lê o banco; tem o botão de coleta manual)
scheduler.py               agendador APScheduler: coleta todo dia às 08:00, America/Fortaleza
radar/
  config.py                .env, fuso, caminhos, leitura e gravação de config/termos.yaml
  db.py                    esquema SQLite, deduplicação por URL, controle de uso do Exa, log de erros
  engines.py               clientes Exa API e DuckDuckGo (Brasil, português)
  classify.py              classificação por regras: tema, vertical, UF, potencial, prazo, impacto
  collector.py             rotina de coleta (também roda pela linha de comando)
  dossier.py               Ficha do executivo: importação da newsletter e ficha preliminar automática
  images.py                até 2 imagens por notícia, baixadas em static/imagens/
  tvdeck.py, tv.html       dados e layout do Modo TV (carrossel)
  obras.py, obras.html     Mapa de Obras: importação, painel com mapa e dados do Modo TV de obras
  tv_obras.html            layout do Modo TV do Mapa de Obras
  brasil_mapa.json         contorno dos estados usado nos mapas de obras
  ui.py                    CSS e blocos HTML da identidade visual da newsletter
pages/tv.py                rota /tv — carrossel em tela cheia para a TV
mapa_obras.py              app separado do Mapa de Obras (streamlit run mapa_obras.py)
obras_app/painel.py        página inicial do Mapa de Obras (mapa, fichas, Bitrix, Excel, importação)
obras_app/tv.py            rota /tv do Mapa de Obras — carrossel das obras para a TV
config/termos.yaml         termos de busca por tema (também editáveis na aba Configuração)
scripts/agendar_tarefa_windows.ps1   registra a coleta diária no Agendador de Tarefas do Windows
data/radar.db              banco (criado automaticamente)
logs/coleta.log            log em texto das coletas
```

## 1. Instalação

Precisa de Python 3.10 ou mais novo (foi testado com o 3.14).

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No Linux ou macOS, troque `.venv\Scripts\python.exe` por `.venv/bin/python` em todos os comandos.

## 2. Chave do Exa

1. Copie `.env.example` para `.env`.
2. Crie uma chave em https://dashboard.exa.ai/api-keys e preencha `EXA_API_KEY=` no `.env`.

A chave fica apenas no `.env`, que está no `.gitignore`. Sem a chave, a coleta roda só com o
DuckDuckGo e registra um aviso no log de erros.

## 3. Rodar o painel

```bash
.venv\Scripts\python.exe -m streamlit run app.py
```

O painel abre em http://localhost:8501 e tem quatro abas:

- **Visão do dia**: as notícias coletadas hoje (ou na última coleta com resultados), agrupadas por
  tema e ordenadas por potencial. Os filtros de vertical e potencial usam chips, como na newsletter.
- **Histórico**: filtros por período (data de coleta ou de publicação), tema, fonte, mecanismo,
  região, vertical, potencial e texto livre. Mostra cards ou tabela e exporta CSV.
- **Coleta e logs**: indicador de buscas Exa usadas no dia, botão **Executar coleta agora**,
  histórico de execuções, detalhe de cada busca e log de erros com o traceback.
- **Configuração**: edita termos (tema, texto, uso no Exa, prioridade, ativo) e parâmetros, e
  importa as fichas pesquisadas a partir do HTML da newsletter.

### Visão do executivo e visão de administrador

- **Executivo, sem login:** vê só a **Visão do dia**, com a barra de filtros, os cards, a ficha, o
  envio ao Bitrix e o Excel, além do Modo TV.
- **Administrador:** entra pelo botão **🔒 Área do administrador**, no topo, e passa a ver também:
  - as abas **Histórico**, **Coleta e logs** (coleta manual, execuções, erros, imagens) e
    **Configuração**;
  - o indicador **Buscas Exa hoje**.

O login vale até recarregar a página ou clicar em **Sair**. Depois de 5 senhas erradas, o login
fica bloqueado por 5 minutos naquela sessão.

Usuário e senha ficam em `ADMIN_USER` e `ADMIN_PASSWORD`, no `.env` ou nos Secrets do Streamlit
Cloud, e nunca no código. Sem essas variáveis, ninguém consegue entrar como administrador.

### Fontes de dados

O botão **🔍 Fontes de dados**, no topo, abre a lista de tudo o que a coleta consulta:
- os mecanismos de busca (Exa, Firecrawl e DuckDuckGo), com limite e uso do dia;
- as fontes diretas por RSS;
- as fichas da newsletter e a inclusão manual;
- os termos de busca por tema;
- os sites que mais geraram notícias;
- as fontes avaliadas e não incluídas, com o motivo (`fontes_nao_incluidas` no `config/termos.yaml`);
- a última coleta.

O botão aparece para todos. Mostra só nomes e endereços públicos.

### Incluir notícia por link

Na aba **Coleta e logs** (administrador), cole o link de uma matéria, por exemplo uma recebida por
WhatsApp, e clique em **Incluir**. O painel lê da própria página o título, o resumo, o texto e a
data de publicação; classifica com as mesmas regras da coleta, usando o texto completo; grava sem
duplicar (pela URL) e baixa até 2 imagens. A notícia aparece com mecanismo "manual" e não é
reclassificada depois. Pela linha de comando:

```bash
.venv\Scripts\python.exe -c "from radar.collector import add_from_url; print(add_from_url('https://...'))"
```

### Notícias sem relação, fora do escopo e repetidas

Ficam fora da Visão do dia, do Modo TV, dos indicadores e das exportações, mas continuam no banco:

- **Sem relação com a Cordeiro:** demanda de guindaste/área = "Não". A classificação automática não
  achou relação com içamento ou carga pesada, ou o analista marcou "Não".
- **Fora do escopo:** viram demanda "Não", com o motivo escrito no quadro de impacto.
  - **Sites de Portugal** (`.pt`). O termo "Porto de Vila do Conde" traz muitas notícias da cidade
    portuguesa.
  - **Notícias sobre outro país** sem estado brasileiro nem menção ao Brasil.
  - Notícias com as palavras de `excluir_se_contiver` no `config/termos.yaml`: futebol, eleições,
    crimes e acidentes, listas genéricas de licitação, "valor de mercado"… A comparação é por
    palavra inteira. Na coleta, essas notícias nem entram.
- **Repetidas:** a mesma matéria publicada por vários sites (`radar/dedupe.py`) aparece **uma vez**.
  - **Quando conta como repetida:** compara o título e também o conteúdo (título + resumo, em que
    palavras raras como "Diamante" e "coco" pesam mais que comuns como "energia"). Assim a mesma
    notícia escrita de outro jeito também se junta.
  - **O que nunca se junta:** notícias com números que não batem ("R$ 20 bi" x "R$ 18 bi") ou de
    estados diferentes ("Licitações em PE" x "em SP"). A janela é de 30 dias.
  - **Qual fica visível:** a ficha pesquisada ou incluída à mão; senão, a **mais recente**.
  - **Quando roda:** o agrupamento é refeito a cada coleta e a cada inclusão por link, e as cópias
    não baixam imagem.
  - **Casos que a regra não pega:** junte à mão, com `python -m radar.dedupe --juntar <id-da-cópia>
    <id-da-principal>`, ou desfaça com `--separar <id>`. A marcação manual vale para os
    reagrupamentos futuros. Para simular sem gravar: `run_all(dry_run=True)`.

No **Histórico**, o administrador pode ligar **"Mostrar notícias sem relação com a Cordeiro"** e
**"Mostrar notícias repetidas"**. Depois de mudar as regras ou a lista de exclusão, reclassifique:
`python -m radar.collector --reclassificar`.

A **Visão do dia** mostra as **12 principais de cada tema** (por potencial), com o botão
**"Mostrar todas"**. Isso deixa a página leve mesmo em dias com centenas de notícias.

### Barra de filtros

As abas Visão do dia e Histórico usam a barra de filtros da newsletter: busca, os atalhos
**Destaques** (**Novas hoje** e **Alta prioridade**, os mesmos critérios dos indicadores do topo), chips de
**Vertical**, **Potencial** (com "Como o potencial é calculado"), **Prazo da demanda**,
**Categoria** e **Região**, listas de **Fase do projeto** e **Empresa executora** e o botão
**Baixar Excel organizado**. O Excel exporta o resultado filtrado nas mesmas 4 abas da newsletter:

- **Oportunidades**, com Responsável e Andamento para preencher (lista suspensa);
- **Roteiros**, com o passo a passo de cada ficha;
- **Contatos**, com os canais oficiais das empresas;
- **Cadastro**, com as etapas de cadastro por empresa.

Os chips de Categoria e Região mostram só o que existe na base.

### Nota da notícia (0 a 10)

Cada card mostra uma nota de 0 a 10 que responde: *vale a pena o executivo jogar esta notícia no
Bitrix?* — a chance de virar relacionamento e demanda (`radar/score.py`). Seis critérios, cada um até
o seu peso (padrão; editáveis em Configuração e reescalados para somar 10):

| Critério | Peso | Níveis |
|---|---|---|
| Demanda de guindaste/área | 2,5 | Sim · Possível · Não |
| Momento da obra | 2,5 | contratação/EPC em curso > aprovado/licenciado > leilão/edital > obra em andamento > anúncio > estudo > só contexto; obra travada ou concluída quase zera |
| Região | 1,5 | CE/PA > Nordeste > nacional > fora da área |
| Empresas para contatar | 1,5 | executora identificada (ficha pesquisada) > empresas mapeadas > empresa citada no texto > nenhuma |
| Porte do investimento | 1,0 | ≥ R$ 1 bi > R$ 100 mi–1 bi > menor > sem valor |
| Prazo | 1,0 | Curto > Médio > a confirmar > Longo |

Notícia com mais de 60 dias perde 0,5 ponto; com mais de 120 dias, 1 ponto. Obra inaugurada/concluída
fica com no máximo 4,5. Faixas: **Quente** ≥ 8 (enviar ao Bitrix), **Morna** ≥ 6 (pesquisar),
**Fria** ≥ 4 (monitorar), **Baixa** < 4. O seletor tem a opção **Maior nota**, o Histórico ordena por
nota e o Excel traz as colunas Nota e Faixa. A nota é calculada na hora (não fica gravada no banco).

### Enviar oportunidade para o Bitrix24

Cada card tem o botão **Enviar para o Bitrix**. Ele abre a lista de usuários; depois de
escolher o responsável e clicar em **Confirmar envio**, o painel cria um lead via `crm.lead.add`:

| Campo do lead | Conteúdo |
|---|---|
| `TITLE` | `[Lead IM]` + título da notícia, ex.: `[IM-2026-0003] Beach Park inaugura…` |
| `COMMENTS` | corpo: resumo, potencial, vertical/categoria, UF, prazo, impacto, entrada da Cordeiro, fase, executor, serviço, próximo passo, fonte e link |
| `ASSIGNED_BY_ID` | usuário escolhido |
| `SOURCE_ID` | origem definida em `config/bitrix.yaml` |
| `SOURCE_DESCRIPTION` | "Radar Cordeiro" + link da notícia |

- **Configuração:** a URL do webhook (com o token) fica em `BITRIX_WEBHOOK_URL`, no `.env` ou nos
  Secrets do Streamlit Cloud, no formato `https://<conta>.bitrix24.com.br/rest/<id>/<token>/`.
- **Usuários e origem:** a lista de usuários e o `SOURCE_ID` ficam em `config/bitrix.yaml`.
- **Registro:** cada envio fica na tabela `crm_leads`. O card passa a mostrar "✓ Enviado ao Bitrix"
  com o responsável. Enviar de novo cria outro lead.
- **Erros:** falhas aparecem na tela e no log de erros.
- **No card:** depois do envio, aparece a faixa **Lead no Bitrix**, com o ID do lead (o link abre o lead
  no Bitrix), o usuário responsável e a data do envio.

### Lead IM (código de rastreio)

Todo card tem um **Lead IM** no formato `IM-AAAA-NNNN`: o ano da coleta e o número da notícia na
base. Ele é único e não muda.

- **Onde aparece:** no card, no título e no corpo do lead do Bitrix, na ficha em texto, no CSV, no
  Excel (a coluna que liga Oportunidades e Roteiros) e no rodapé dos slides da TV.
- **Para que serve:** no Bitrix, buscar por `IM-` mostra todos os leads vindos da Inteligência de
  Mercado; no painel, a busca também aceita o código.

### Ficha do executivo

Cada card traz o bloco **Entrada da Cordeiro** (prioridade, fase e executor) e a **Ficha do
executivo**, com os mesmos 8 tópicos da newsletter: oportunidade, roteiro com tempo por passo,
contatos e cadastro, perguntas, mensagem de abordagem, empresas, pendências e fontes. O tópico
"Copiar ficha completa" mostra o texto inteiro para colar no CRM. No Histórico, o botão
**Baixar fichas do executivo (TXT)** exporta as fichas filtradas. Há duas origens:

- **Ficha pesquisada**: importada da newsletter, com fase, executor, empresas e canais oficiais de
  cadastro verificados pelo analista. A classificação do analista prevalece sobre a automática.
- **Ficha preliminar**: gerada automaticamente com o roteiro padrão para as notícias coletadas.
  Não inventa contatos, executor nem empresas; esses campos ficam como "a confirmar".

Para importar ou atualizar as fichas, use a aba Configuração ou a linha de comando:

```bash
.venv\Scripts\python.exe -m radar.dossier radar-cordeiro-relatorio-NEWSLETTER-integrado.html
```

### Modo TV (rota `/tv`)

Abra http://localhost:8501/tv no navegador da TV, ou use o link "Abrir Modo TV" no painel. É um
carrossel 16:9 em tela cheia, pensado para a TV de 43" em Full HD:

- **Conteúdo:** a capa com indicadores e **todas as notícias da base**, cada uma com até 2 imagens,
  impacto, entrada da Cordeiro e a **nota 0–10** (selo no canto, com "Por que a nota" abaixo do título).
  A ordem é: novas da semana primeiro, depois pela nota (maior → menor), depois a mais recente. A capa
  mostra também a distribuição por nota (Quente, Morna, Fria, Baixa).
- **Capa:** reaparece a cada 30 notícias, e os dados são recarregados nessas passagens (a cada 10
  minutos ou mais). A recarga **continua da notícia seguinte à última exibida**; não volta para o
  início. Assim a TV percorre a base inteira, e a lista é refeita só ao terminar a volta.
- **Leveza:** só o slide atual e o próximo ficam montados, então o carrossel continua leve com
  centenas de notícias. O contador mostra a posição, por exemplo `57 / 386`.

Controles: ← → navegam, espaço pausa e F alterna a tela cheia. Parâmetros pela URL:

| Parâmetro | Padrão | Uso |
|---|---|---|
| `segundos` | 18 | tempo de cada notícia |
| `capa` | 12 | tempo da capa |
| `capa_a_cada` | 30 | repete a capa a cada N notícias (0 = só no início) |
| `max` | 0 | limita o número de notícias (0 = todas) |
| `recarregar` | 10 | minutos mínimos entre recargas dos dados |

Exemplo: `/tv?segundos=10&max=100` mostra as 100 primeiras, a 10 s cada.

Para deixar a TV fixa no carrossel, abra o navegador em modo quiosque, por exemplo:
`chrome --kiosk http://<ip-do-computador>:8501/tv`. Para a TV acessar o painel pela rede, o
Streamlit precisa estar rodando no computador e a porta 8501 liberada no firewall.

### Mapa de Obras (app separado: `mapa_obras.py`)

O Mapa de Obras Cordeiro é um **app próprio**, fora do Radar de notícias, com as obras do **Obras Online**
(eólico, mineração, data center e infraestrutura). Ele usa o mesmo banco (SQLite ou Supabase, tabelas
`obras` e `obras_imports`), o mesmo Bitrix e o mesmo login de administrador.

```bash
.venv\Scripts\python.exe -m streamlit run mapa_obras.py --server.port 8502
```

No Streamlit Community Cloud, ele é um segundo app do mesmo repositório: *Create app* → branch `main`,
**Main file path `mapa_obras.py`**, e os mesmos Secrets do Radar (`SUPABASE_DB_URL`, `BITRIX_WEBHOOK_URL`,
`ADMIN_USER`, `ADMIN_PASSWORD`).

- **Painel (`/`):** o mapa interativo do `mapa_obras_cordeiro-PAINEL.html`, com os mesmos filtros e
  fichas, alimentado pelo banco. Abaixo dele, o envio da obra ao Bitrix e o botão **Baixar Excel das
  obras** (abas Obras, com Responsável e Andamento, e Empresas).
- **Modo TV (`/tv`):** mesmo carrossel do Modo TV de notícias. A capa mostra os indicadores e o mapa
  do Brasil com todas as obras; cada slide mostra o estado da obra no mapa, as datas previstas (com o
  aviso "em N dias"), os dados da obra e as empresas. A ordem é: novas da semana, depois a fase que
  termina antes. Aceita os mesmos parâmetros do `/tv` (`segundos`, `capa`, `capa_a_cada` — padrão 20 —,
  `max` e `recarregar`), recarrega os dados ao passar pela capa e continua de onde parou.
- **Bitrix:** o lead leva o código `IM-OBR-<código da obra>` (a busca por `IM-` no Bitrix encontra notícias
  e obras), a fase, as datas, o valor e as empresas. O envio fica em `crm_leads` (coluna `obra_cod`).
- **Atualização dos dados:** cada importação é um retrato completo. Obras fora do arquivo saem do painel
  e da TV, mas continuam no banco. Há três formas:
  1. **Automática:** defina `OBRAS_PASTA` no `.env` com a pasta onde fica o `mapa_obras_cordeiro-PAINEL.html`.
     A coleta diária (Agendador do Windows ou `scheduler.py`) importa o HTML de obras mais recente da
     pasta que tenha os dados do mapa (outros painéis na pasta são ignorados), só quando ele mudou. Basta salvar a versão nova do arquivo na pasta.
  2. **Pelo painel:** o administrador envia o arquivo no fim da página inicial do Mapa de Obras (ou clica em
     "Importar agora da pasta"). O histórico das importações aparece logo abaixo.
  3. **Pela linha de comando:**

```bash
.venv\Scripts\python.exe -m radar.obras "caminho\mapa_obras_cordeiro-PAINEL.html"
```

A TV de obras fica em `chrome --kiosk http://<ip-do-computador>:8502/tv`. O Obras Online não tem
API aberta, então a fonte continua sendo o HTML exportado do painel de obras. Os nomes das obras aparecem
mascarados, como na fonte.

### Imagens das notícias

Em cada coleta, cada notícia nova recebe até 2 imagens, salvas em `static/imagens/` e registradas
na tabela `news_images`. As fontes são a imagem da busca, a imagem de capa da matéria (`og:image`)
e fotos do corpo do texto. Logos, banners e imagens repetidas entre notícias (anúncios,
imagens-padrão de site) são descartados. Mesmo assim, algum logo ou peça promocional ainda pode
passar. Para preencher as notícias que ainda não têm imagem:

```bash
.venv\Scripts\python.exe -m radar.images
```

## 4. Deixar a coleta diária rodando

O Streamlit não executa tarefas sozinho, então a coleta fica num processo separado. Escolha **uma**
das opções abaixo. Usar as duas faria a coleta rodar duas vezes por dia; mesmo assim, o Exa nunca
passa de 5 buscas no dia.

**Opção A — Agendador de Tarefas do Windows (recomendada neste PC).** Não exige terminal aberto.
Se o computador estiver desligado às 08:00, a coleta roda assim que ele for ligado.

```bash
powershell -ExecutionPolicy Bypass -File scripts\agendar_tarefa_windows.ps1
```

O Agendador usa o relógio do Windows. Confira se o fuso da máquina é UTC-03:00 (Fortaleza ou
Brasília). Para remover a tarefa: `Unregister-ScheduledTask -TaskName "Radar Cordeiro - coleta diaria"`.

**Opção B — APScheduler (`scheduler.py`).** Usa o fuso America/Fortaleza mesmo que o servidor esteja
em outro fuso. O processo precisa ficar rodando, num terminal aberto ou como serviço (NSSM no
Windows, systemd no Linux).

```bash
.venv\Scripts\python.exe scheduler.py
```

Com `--agora`, ele faz uma coleta imediata e depois continua agendado.

**Opção C — cron (Linux).**

```
CRON_TZ=America/Fortaleza
0 8 * * * cd /caminho/painel_noticias && .venv/bin/python -m radar.collector --agendado
```

Coleta avulsa pela linha de comando:

```bash
.venv\Scripts\python.exe -m radar.collector
```

## 5. Como a coleta funciona

1. **Exa**: limite rígido de **5 buscas por dia**, no fuso de Fortaleza. O código fixa o teto em 5;
   o `termos.yaml` pode reduzir esse número, nunca aumentar. Cada chamada é reservada no banco
   (tabela `exa_usage`) *antes* de ser feita, com uma operação atômica. Assim, uma coleta manual e
   uma agendada no mesmo dia somam juntas e não passam de 5. Uma chamada que falhar também conta,
   porque pode ter sido cobrada. Entram no Exa os termos marcados `exa: true`, em ordem de
   prioridade. Se houver mais de 5 marcados, os termos entram em rodízio diário. Os filtros usados
   são `userLocation: "BR"`, `category: "news"` e publicação nos últimos N dias.
2. **Firecrawl** (`/v2/search`, notícias): busca restrita ao Brasil (`country: BR`), com período
   configurável (dia, semana ou mês).
   - **Limite:** cada busca consome créditos (cerca de 2 a cada 10 notícias), então há um **limite
     diário de buscas** (padrão: 10), reservado no banco antes de cada chamada.
   - **Registro:** o uso e os créditos do dia ficam na tabela `api_usage` e aparecem para o
     administrador.
   - **Termos:** entram os marcados `firecrawl: true`; sem nenhum marcado, todos, por prioridade e
     com rodízio diário.
   - **Chave:** `FIRECRAWL_API_KEY`, no `.env` ou nos Secrets.
3. **Fontes diretas por RSS**, sem custo de API: lidas a cada coleta, com as notícias dos últimos 14
   dias. Hoje: **Brasil Mineral**, **InfraNews**, **BVMI** e 4 editorias do **Movimento Econômico**
   (Portos, Energia, Infraestrutura, Indústria & Empresas). Avaliadas e não incluídas: Valor e Exame
   (feed geral, quase só ruído, e já chegam pelas buscas), Nordeste Investing (feed com erro) e
   CanalEnergia (feed vazio). Para acrescentar um site,
   inclua em `fontes_rss` no `config/termos.yaml`, por exemplo
   `{nome: Nome do site, url: "https://site/feed/", tema: Mineração, ativo: true}`. Para ler só os
   feeds, sem gastar cota de Exa e Firecrawl: `python -m radar.collector --rss`.
   - **Sites sem feed útil**: são cobertos por **buscas direcionadas** no tema "Buscas
     direcionadas" do `termos.yaml` (`site:diariodopara.com.br mineração`,
     `site:poder360.com.br infraestrutura obras`…). É o caso do Diário do Pará e do Poder360, cujos
     feeds são de política e cujas editorias de economia não têm feed.
   - **Rodar só alguns termos** no DuckDuckGo, sem Exa, Firecrawl e feeds:
     `run_collection("manual", only_terms=[...])`.
4. **DuckDuckGo** (biblioteca `ddgs`): busca de notícias para todos os termos ativos, com região
   `br-pt`, período configurável (dia, semana ou mês) e uma pausa entre buscas para evitar bloqueio.
5. **Deduplicação**: a URL é normalizada (sem `utm_*`, fragmento ou barra final) e é única no banco.
   Quando uma notícia reaparece, o banco só atualiza `times_seen` e `last_seen_at`.
6. **Classificação automática** (`radar/classify.py`): regras que seguem os critérios de potencial
   da newsletter (relação com içamento, UF dentro da área de atuação, decisão pendente ou obra em
   andamento, porte financeiro). Elas atribuem vertical, categoria, UF, prazo, potencial, demanda e
   o texto "Impacto para a Cordeiro". **É uma triagem por palavras-chave, não uma análise.** Nas 52
   notícias da newsletter de referência, as regras acertaram o potencial exato em 36 e a UF em 49.
   Valide antes de prospectar. Depois de ajustar as regras ou as UFs, reclassifique a base:

```bash
.venv\Scripts\python.exe -m radar.collector --reclassificar
```

## 6. Banco de dados (SQLite)

| Tabela      | Conteúdo |
|-------------|----------|
| `news`      | título, URL (única), fonte, data de publicação, resumo, termo buscado, tema, mecanismo de origem, data da coleta, classificação |
| `searches`  | cada busca feita: mecanismo, termo, nº de resultados, nº de novas, status e erro |
| `runs`      | cada execução: origem (agendado ou manual), início, fim, status e totais |
| `exa_usage` | buscas Exa usadas por dia |
| `errors`    | log de erros com traceback |
| `dossiers`  | Fichas do executivo pesquisadas (JSON), ligadas à notícia pela URL |
| `accounts`  | canais oficiais de fornecedores das empresas (contatos e cadastro) |
| `news_images` | até 2 imagens por notícia: arquivo, origem, tamanho e hash visual |
| `image_blocklist` | hashes de imagens repetidas entre notícias (anúncios), ignoradas nas próximas coletas |
| `crm_leads` | leads enviados ao Bitrix: notícia ou obra, lead criado, responsável, status e resposta |
| `obras` | obras do Mapa de Obras (JSON da ficha), ativas ou fora do último arquivo |
| `obras_imports` | cada importação do Mapa de Obras: origem, arquivo e contagens |

Para consultar o banco fora do painel, abra `data/radar.db` em qualquer cliente SQLite (por exemplo,
o DB Browser for SQLite).

## Observações

- Salvar pela aba Configuração reescreve o `termos.yaml` e apaga os comentários do arquivo.
- O DuckDuckGo News rende mais com termos curtos, de 2 a 4 palavras. O Exa aceita frases mais longas.
- O DuckDuckGo não tem API oficial e pode limitar as requisições. Quando isso acontece, a coleta
  tenta de novo e registra o erro, sem interromper as outras buscas.

## Banco no Supabase (dados persistentes)

Com `SUPABASE_DB_URL` configurada, o painel, a coleta e o agendador gravam no **Postgres do
Supabase** em vez do `data/radar.db`. Os dados passam a sobreviver aos reinícios do Streamlit
Cloud, e um computador rodando o agendamento diário alimenta o mesmo banco que o Cloud mostra.
Com `SUPABASE_URL` e `SUPABASE_SERVICE_KEY`, as imagens vão para o bucket público `imagens` do
Supabase Storage.

1. **Copiar as credenciais para o `.env`** (ou para os Secrets do Cloud):
   - `SUPABASE_DB_URL`: em *Project Settings → Database → Connection string*, escolha **Session
     pooler** (funciona em IPv4, inclusive no Streamlit Cloud) e troque `[YOUR-PASSWORD]` pela
     senha do banco.
   - `SUPABASE_URL`: `https://cbqflpapzmywfxcebjpa.supabase.co`.
   - `SUPABASE_SERVICE_KEY`: chave secreta (*service_role*) em *Project Settings → API*. Ela dá
     acesso total ao projeto e nunca deve ir para o código nem para o GitHub.
2. **Migrar o banco local e as imagens:**

```bash
.venv\Scripts\python.exe -m radar.migrar_supabase
```

A migração cria as tabelas, copia todos os dados, envia as imagens e confere as contagens. Pode
ser rodada de novo sem duplicar nada. Sem `SUPABASE_DB_URL`, tudo continua no SQLite local, como
antes.

## Publicar no Streamlit Community Cloud

- **Chave do Exa:** em *Settings → Secrets*, adicione `EXA_API_KEY = "sua-chave"`. O app procura
  primeiro no `.env` e depois nos Secrets.
- **Dados persistentes:** configure também `SUPABASE_DB_URL`, `SUPABASE_URL` e
  `SUPABASE_SERVICE_KEY` nos Secrets (veja "Banco no Supabase"). Sem elas, o Cloud usa um SQLite
  temporário, que é apagado a cada reinício.
- **Coleta diária:** o Cloud não roda o `scheduler.py`. Deixe o agendamento num computador da
  empresa com o mesmo `.env`; ele grava no Supabase, e o painel do Cloud mostra as notícias do dia.
- **Pooler:** o host direto `db.<projeto>.supabase.co` só tem IPv6 e não funciona no Cloud nem na
  maioria das redes. Use a URL do **Session pooler** (`aws-1-us-west-2.pooler.supabase.com`).
- **Segurança no Supabase:** as tabelas têm RLS ativo e nenhuma política, então as chaves públicas
  (anon/publishable) não leem nem alteram nada pela API. O painel conecta como dono das tabelas.
- **Avisos no console do navegador:** `Tracking Prevention blocked…`, `heap-api … 404`,
  `/api/v2/user/details 404`, `Unrecognized feature` e `allow-scripts and allow-same-origin` vêm da
  própria plataforma do Cloud e do navegador, não deste app, e podem ser ignorados.
