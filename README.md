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
  ui.py                    CSS e blocos HTML da identidade visual da newsletter
pages/tv.py                rota /tv — carrossel em tela cheia para a TV
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

- uma capa com indicadores;
- até 24 oportunidades (Alto ou Muito Alto, ou novas na semana), com até 2 imagens, impacto e
  entrada da Cordeiro.

Os dados são recarregados ao voltar para a capa, a cada 10 minutos. Controles: ← → navegam,
espaço pausa e F alterna a tela cheia. O tempo é configurável pela URL:
`/tv?segundos=18&capa=12&max=24&recarregar=10`.

Para deixar a TV fixa no carrossel, abra o navegador em modo quiosque, por exemplo:
`chrome --kiosk http://<ip-do-computador>:8501/tv`. Para a TV acessar o painel pela rede, o
Streamlit precisa estar rodando no computador e a porta 8501 liberada no firewall.

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
2. **DuckDuckGo** (biblioteca `ddgs`): busca de notícias para todos os termos ativos, com região
   `br-pt`, período configurável (dia, semana ou mês) e uma pausa entre buscas para evitar bloqueio.
3. **Deduplicação**: a URL é normalizada (sem `utm_*`, fragmento ou barra final) e é única no banco.
   Quando uma notícia reaparece, o banco só atualiza `times_seen` e `last_seen_at`.
4. **Classificação automática** (`radar/classify.py`): regras que seguem os critérios de potencial
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

Para consultar o banco fora do painel, abra `data/radar.db` em qualquer cliente SQLite (por exemplo,
o DB Browser for SQLite).

## Observações

- Salvar pela aba Configuração reescreve o `termos.yaml` e apaga os comentários do arquivo.
- O DuckDuckGo News rende mais com termos curtos, de 2 a 4 palavras. O Exa aceita frases mais longas.
- O DuckDuckGo não tem API oficial e pode limitar as requisições. Quando isso acontece, a coleta
  tenta de novo e registra o erro, sem interromper as outras buscas.
