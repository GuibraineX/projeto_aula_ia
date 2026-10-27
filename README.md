# 🏭 Triagem de Manutenção com IA e MCP

Assistente de triagem para uma fábrica fictícia. A pessoa descreve um problema em texto
livre ("a EST-02 parou com erro E-12") e o agente:

1. consulta o equipamento e os **manuais** (busca semântica, RAG);
2. orienta **somente** com o que o manual diz, citando a fonte;
3. abre um **chamado** com protocolo;
4. pede a **reserva de peças**, que só vale depois da **aprovação de uma pessoa**;
5. **recusa** o que está fora do escopo, como reiniciar uma máquina remotamente.

As ferramentas ficam num **servidor MCP** separado. O agente descobre essas ferramentas,
decide quais o modelo pode usar e aplica limites de tempo, de tentativas e de rodadas.

> Projeto didático, construído ao longo das Aulas 1 a 9 da disciplina de IA.
> A fábrica, os equipamentos, os manuais e as peças são **fictícios**.

---

## Sumário

- [Arquitetura](#arquitetura)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Instalação](#instalação)
- [Como usar](#como-usar)
- [Como funciona](#como-funciona)
- [Ferramentas do servidor MCP](#ferramentas-do-servidor-mcp)
- [Configuração](#configuração)
- [Testes e avaliação](#testes-e-avaliação)
- [Problemas comuns](#problemas-comuns)
- [Limitações conhecidas](#limitações-conhecidas)
- [Relação com as aulas](#relação-com-as-aulas)

---

## Arquitetura

```text
  Pessoa
    │
    ▼
 app.py (interface web)  ou  conversar.py (terminal)
    │
    ▼
 agente.py ─────────────────────────────►  Ollama Cloud (gpt-oss:20b)
  laço · permissões · limites  ◄─────────  pede ferramentas / responde
    │
    │  MCP (stdio por padrão, ou HTTP)
    ▼
 servidor_mcp.py ──► data/fabrica.sqlite   (chamados, reservas, estoque)
  10 ferramentas  ──► busca.py ──► data/manuals/*.md
                                   └──► Gemini (embeddings)
```

O projeto tem três camadas, e cada uma tem uma responsabilidade:

| Camada | Arquivos | Responsabilidade |
|---|---|---|
| Interface | `app.py`, `conversar.py` | Conversar com a pessoa e mostrar o painel |
| Agente | `agente.py` | Decidir **o que pode** acontecer: permissões, limites, novas tentativas |
| Servidor MCP | `servidor_mcp.py`, `busca.py` | **Executar** as ferramentas e guardar os dados |

O servidor **publica e executa** as ferramentas; a aplicação **descobre, autoriza e coordena**.

---

## Estrutura do projeto

```text
projeto_aula_ia/
├── app.py                 interface web (Gradio)
├── conversar.py           chat pelo terminal
├── agente.py              laço do agente, prompt, permissões e limites
├── servidor_mcp.py        servidor MCP com as 10 ferramentas
├── busca.py               busca nos manuais (RAG)
├── requirements.txt       dependências
├── .env.exemplo           modelo do arquivo de chaves
├── .env                   suas chaves (não vai para o Git)
├── .gitignore
├── data/
│   ├── equipamentos.json  4 equipamentos
│   ├── pecas.json         estoque inicial de 5 peças
│   ├── manuals/           manuais em Markdown, um por equipamento + GERAL
│   └── fabrica.sqlite     criado ao rodar (chamados, reservas, estoque, vetores)
├── test/
│   ├── teste_servidor.py  testa o servidor e as permissões, sem o modelo
│   ├── avaliar.py         avalia o agente com o modelo real
│   └── teste_chave.py     confere se a chave do Ollama funciona
└── registros/             criado ao rodar: um JSON por atendimento + logs
```

---

## Instalação

**Requisitos:** Python 3.10 ou mais novo, VS Code com a extensão Python e uma chave do
**Ollama Cloud**. Não é preciso instalar o Ollama nem baixar modelos.

### 1. Ambiente virtual

No terminal do VS Code (`` Ctrl+` ``), na pasta do projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear a ativação:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.venv\Scripts\Activate.ps1
```

Depois, em `Ctrl+Shift+P → Python: Select Interpreter`, escolha o `.venv`.

### 2. Dependências

```powershell
pip install -r requirements.txt
```

| Biblioteca | Para quê |
|---|---|
| `gradio` | Interface web |
| `ollama` | Cliente do modelo de linguagem (Ollama Cloud) |
| `mcp` | Servidor e cliente MCP (versão fixa: 1.30.0, a mesma da Aula 9) |
| `python-dotenv` | Lê as chaves do arquivo `.env` |
| `google-genai` | Embeddings do Gemini para a busca nos manuais |

### 3. Chaves

Copie o `.env.exemplo`, renomeie a cópia para `.env` e preencha:

```text
OLLAMA_API_KEY=sua-chave-do-ollama
MODELO=gpt-oss:20b
GEMINI_API_KEY=sua-chave-do-gemini
```

- Chave do Ollama: <https://ollama.com/settings/keys>
- Chave do Gemini: <https://aistudio.google.com/apikey> (opcional: sem ela, a busca
  compara palavras em vez de significados)

Formato: uma variável por linha, sem espaço em volta do `=` e sem aspas. O `.env` está no
`.gitignore`: **nunca** envie esse arquivo para o Git.

### 4. Conferir

```powershell
python test/teste_chave.py        # a chave do Ollama responde?
python test/teste_servidor.py     # o servidor e as permissões funcionam?
```

O segundo deve mostrar **10 ferramentas descobertas**, separadas em três grupos, e terminar
com a reserva `APROVADA`.

---

## Como usar

### Interface web

```powershell
python app.py
```

O navegador abre em <http://127.0.0.1:7860>. Para desligar, aperte `Ctrl+C` no terminal.

| Área | O que faz |
|---|---|
| Chat | Descreva o problema e envie com `Enter` ou **Enviar** |
| Blocos 🔧 | Cada ferramenta usada. Clique para ver o resultado completo |
| Chamados de teste | Exemplos prontos que preenchem a caixa com um clique |
| Chamados | Os chamados do banco, os mais recentes primeiro |
| Reservas de peças | As reservas. As pendentes aparecem na lista de seleção |
| ✅ Aprovar / ❌ Recusar | A decisão humana sobre a reserva selecionada |
| 🔌 Ferramentas do servidor MCP | As ferramentas descobertas e os três grupos de permissão |

Ícones dos blocos: **🔧** a ferramenta rodou, **⛔** foi barrada pela permissão,
**⚠️** devolveu um erro (o modelo pode corrigir e tentar de novo).

### Terminal

```powershell
python conversar.py
```

| Comando | O que faz |
|---|---|
| (qualquer texto) | Envia para o agente |
| `/aprovar RES-001` | Aprova uma reserva (você é a pessoa responsável) |
| `/recusar RES-001` | Recusa uma reserva |
| `/nova` | Começa uma conversa nova (os chamados continuam no banco) |
| `/sair` | Encerra |

### Exemplo de atendimento

```text
Você: A EST-02 parou com erro E-12
   [ok ] consultar_equipamento(codigo='EST-02')
   [ok ] buscar_manual(equipamento='EST-02', pergunta='E-12')
   [ok ] abrir_chamado(equipamento='EST-02', ..., prioridade='alta', codigo_erro='E-12')
   [ok ] consultar_estoque(peca='SNS-FC-01')
   [ok ] solicitar_reserva_peca(protocolo='LAB-101', peca='SNS-FC-01', quantidade=1)

Assistente: Chamado LAB-101 aberto. [EST-02 · E-12 · Sensor de fim de curso]: limpar a
face do sensor e conferir o alinhamento; se o LED não acender, trocar o SNS-FC-01.
Reserva RES-001 aguarda aprovação.
```

O texto exato varia a cada execução. O que importa são os **fatos**: o protocolo da
resposta é o que a ferramenta devolveu, a orientação cita a fonte e a reserva aparece
como pendente.

---

## Como funciona

### O laço do agente (`agente.py`)

Para cada mensagem:

1. Conecta ao servidor MCP e descobre as ferramentas (`tools/list`).
2. Envia ao modelo o histórico e **só** as ferramentas permitidas.
3. Se o modelo pedir ferramentas, executa cada uma (com permissão, tempo limite e
   novas tentativas) e devolve um resultado para **cada** pedido.
4. Repete até o modelo responder sem pedir ferramentas, ou até atingir um limite.
5. Grava o atendimento em `registros/AAAA-MM-DD.jsonl`.

Todo atendimento termina com um **status**: `final` (respondeu), `vazio` (o modelo não
devolveu texto) ou `limite` (parou por um dos limites, e diz por quê).

### Permissões em três níveis

| Grupo | Ferramentas | Quem usa |
|---|---|---|
| Para o modelo | `consultar_equipamento`, `buscar_manual`, `consultar_estoque`, `abrir_chamado`, `solicitar_reserva_peca` | O modelo, durante o atendimento |
| Só a aplicação | `listar_chamados`, `listar_reservas`, `aprovar_reserva`, `recusar_reserva` | Os botões e o painel. O modelo nem sabe que existem |
| Bloqueadas | `reiniciar_equipamento` e qualquer ferramenta nova | Ninguém |

É uma **lista de permitidas**: uma ferramenta nova publicada pelo servidor começa
**bloqueada**, até alguém liberá-la em `agente.py`. Há duas barreiras:

1. o modelo só recebe as ferramentas do seu grupo;
2. se ele pedir outra mesmo assim, `chamar_ferramenta` recusa antes de chegar ao servidor.

### Os limites

| Limite | Valor | Onde |
|---|---|---|
| Tempo por ferramenta | 15 s (3 s para `consultar_equipamento`, 60 s para `buscar_manual`) | `TIMEOUT_PADRAO`, `TIMEOUTS` |
| Tentativas por ferramenta | 3, só para consultas e `abrir_chamado` | `TENTATIVAS`, `PODE_REPETIR` |
| Chamadas ao modelo por pedido | 8 | `MAX_RODADAS` |
| Ferramentas por rodada / por pedido | 4 / 8 | `MAX_POR_RODADA`, `MAX_FERRAMENTAS` |
| Tempo de resposta do modelo | 180 s | `AsyncClient(timeout=180)` |

Só é repetido o que é **seguro repetir**: as consultas só leem dados, e o `abrir_chamado`
tem controle de duplicatas. A espera entre tentativas cresce (0,5 s e depois 1 s).
Só a **demora** é repetida: um erro de validação falharia igual de novo.

### A busca nos manuais (`busca.py`)

1. **Trechos:** cada seção `##` de um manual vira um trecho, com a fonte
   `EQUIPAMENTO · título`. Assim o significado de um erro fica junto da verificação.
2. **Filtro:** só entram os trechos do equipamento pedido e os do `GERAL`.
3. **Busca semântica:** embeddings do Gemini (`gemini-embedding-001`, 768 dimensões,
   `RETRIEVAL_DOCUMENT` para os trechos e `RETRIEVAL_QUERY` para a pergunta).
4. **Cache:** os vetores dos trechos são guardados no SQLite, com a chave
   `sha256(modelo|texto)`. Um trecho editado é recalculado sozinho.
5. **Plano B:** se o Gemini falhar ou não houver chave, a busca compara palavras
   (sem acento, sem palavras vazias, com um radical simples).
6. **Bônus de código:** um trecho cujo título tem o código de erro citado (`E-12`, `E12`,
   `e-7`) ganha +1 e vai para o topo.
7. **Resposta:** os 3 trechos mais relevantes, o método usado e o campo
   `tem_manual_do_equipamento`.

O campo `metodo` sempre diz qual busca foi usada e, no plano B, **por quê**.

### Controle de duplicatas e aprovação humana

- `abrir_chamado` devolve o **mesmo** protocolo se já existir um chamado aberto para o
  mesmo equipamento e o mesmo código de erro (ou o mesmo sintoma, se não houver código).
  Nesse caso, também informa as reservas que o chamado já tem.
- `solicitar_reserva_peca` cria a reserva como `AGUARDANDO_APROVACAO` e não baixa o
  estoque. Pedidos iguais pendentes devolvem a reserva existente.
- `aprovar_reserva` confere o estoque **de novo** e, numa única transação, baixa o estoque
  e muda o status. Uma reserva só sai do estado pendente uma vez.

### Validação

O servidor não confia no modelo:

- `prioridade` só aceita `baixa`, `media` ou `alta`. Variações inofensivas, como `Alta` ou
  `Média`, são normalizadas antes da validação; um valor errado, como `urgente`, é recusado.
- `quantidade` só aceita um inteiro de verdade, de 1 a 10 (`True` e `"2"` são recusados).
- Códigos de equipamento são normalizados: `est 02`, `EST02` e `est-02` viram `EST-02`.

Um pedido mal feito vira um **erro com o motivo**; um pedido certo com resposta negativa
(por exemplo, peça sem estoque) vira um resultado com `criada: false` e o motivo.

---

## Ferramentas do servidor MCP

| Ferramenta | Tipo | Grupo | O que faz |
|---|---|---|---|
| `consultar_equipamento(codigo)` | Consulta | Modelo | Nome, linha, setor, criticidade e equipe |
| `buscar_manual(equipamento, pergunta)` | Consulta | Modelo | Os trechos mais relevantes dos manuais, com a fonte |
| `consultar_estoque(peca)` | Consulta | Modelo | Quantidade disponível de uma peça |
| `abrir_chamado(equipamento, sintoma, prioridade, codigo_erro)` | Ação | Modelo | Abre um chamado `LAB-...` ou devolve o existente |
| `solicitar_reserva_peca(protocolo, peca, quantidade)` | Ação | Modelo | Cria uma reserva `RES-...` pendente de aprovação |
| `listar_chamados()` | Consulta | Aplicação | Os 20 chamados mais recentes |
| `listar_reservas()` | Consulta | Aplicação | As 20 reservas mais recentes |
| `aprovar_reserva(reserva)` | Ação | Aplicação | Aprova e baixa o estoque |
| `recusar_reserva(reserva)` | Ação | Aplicação | Recusa a reserva |
| `reiniciar_equipamento(codigo)` | Simulação | Bloqueada | Não faz nada. Existe para demonstrar o bloqueio |

### Usar o servidor por HTTP

Por padrão, o agente inicia o servidor sozinho, via stdio, a cada atendimento. Para rodar o
servidor como um processo separado:

```powershell
# Terminal 1
python servidor_mcp.py --http

# Terminal 2
$env:MCP_URL="http://127.0.0.1:8000/mcp"
python app.py
```

---

## Configuração

As variáveis ficam no `.env`. Uma variável definida no terminal tem prioridade sobre o
`.env` (por exemplo, `$env:MODELO="outro-modelo"`).

| Variável | Para que serve | Padrão |
|---|---|---|
| `OLLAMA_API_KEY` | Usa o Ollama Cloud. Sem ela, tenta o Ollama local | (vazia) |
| `MODELO` | Modelo do chat (precisa aceitar ferramentas) | `gpt-oss:20b` (Cloud) ou `qwen2.5:7b` (local) |
| `GEMINI_API_KEY` | Embeddings da busca nos manuais | (vazia: busca por palavras) |
| `MODELO_EMBEDDING` | Modelo de embeddings do Gemini | `gemini-embedding-001` |
| `MCP_URL` | Conecta a um servidor MCP já rodando por HTTP | (vazia: stdio) |
| `FABRICA_BANCO` | Caminho do banco SQLite | `data/fabrica.sqlite` |
| `SIMULAR_LENTIDAO` | `1` faz o `consultar_equipamento` demorar 5 s em metade das chamadas | (vazia) |

### Dados

- `data/equipamentos.json`: EST-02 (esteira), PRN-01 (prensa), CMP-01 (compressor) e
  INJ-04 (injetora, **sem manual**, de propósito).
- `data/pecas.json`: estoque **inicial**. O `FLT-CMP-01` começa com 0 unidades, de propósito.
- `data/manuals/`: um arquivo por equipamento, com o nome igual ao código, e o `GERAL.md`
  com as normas de segurança. Cada seção `##` vira um trecho da busca.

### Recomeçar do zero

Pare o app (`Ctrl+C`) e apague o banco. Ele é recriado com o estoque inicial:

```powershell
Remove-Item data\fabrica.sqlite
```

---

## Testes e avaliação

### Teste do servidor (sem o modelo)

```powershell
python test/teste_servidor.py
```

Usa um banco separado (`data/teste.sqlite`) e chama as ferramentas com as permissões do
modelo. Erros **esperados**: prioridade inválida, ferramenta bloqueada e ferramenta só da
aplicação. Por fim, aprova a reserva com as permissões da aplicação.

### Avaliação do agente (com o modelo real)

```powershell
python test/avaliar.py        # cada caso 1 vez
python test/avaliar.py 3      # cada caso 3 vezes (mais confiável)
```

Roda 7 casos, cada um com o banco zerado, e confere **fatos**: ferramentas usadas,
argumentos e se a resposta bate com o que as ferramentas devolveram.

| Caso | O que é conferido |
|---|---|
| CH-101: chamado completo | Prioridade alta, protocolo correto, fonte citada, verificação do manual, reserva pendente |
| CH-102: falta o equipamento | Não usa ferramentas e pergunta qual é o equipamento |
| CH-103: fora do escopo | Não tenta reiniciar e orienta procurar o técnico |
| CMP-01: peça sem estoque | Explica a falta de estoque, sem dizer que aguarda aprovação |
| PRN-01: fumaça | Prioridade alta, afastar pessoas, Segurança do Trabalho, normas gerais citadas |
| INJ-04: sem manual | Diz que não há manual |
| EST-02 de novo | Reconhece o chamado existente e não pede de novo a peça já aprovada |

O placar mostra `n/vezes` para cada verificação e a última resposta que falhou. O
resultado é salvo em `registros/avaliacao/resultado-AAAAMMDD-HHMMSS.json`.

**Como usar:** rode **antes** e **depois** de mudar o prompt, o modelo ou uma ferramenta, e
compare. Uma verificação que passava e passou a falhar é uma regressão. Para comparar
modelos:

```powershell
$env:MODELO="outro-modelo"
python test/avaliar.py 3
Remove-Item Env:MODELO
```

As verificações de **texto** procuram palavras-chave e podem errar. Quando uma falhar,
leia a resposta mostrada no placar antes de concluir.

### Onde ficam os registros

| Arquivo | Conteúdo |
|---|---|
| `registros/AAAA-MM-DD.jsonl` | Um atendimento por linha: pedido, modelo, resposta, status, passos e tempo |
| `registros/servidor_mcp.log` | Logs e erros do servidor MCP |
| `registros/avaliacao/` | Banco, registros e placares da avaliação |

---

## Problemas comuns

| Sintoma | Causa provável e o que fazer |
|---|---|
| `Erro 401 do Ollama` | `OLLAMA_API_KEY` errada no `.env` |
| `Erro 404 do Ollama` | Nome errado em `MODELO` |
| `Erro 429` | Limite de uso do plano: espere e tente de novo |
| `Não consegui conectar ao Ollama` | Sem internet, ou o `.env` não está na pasta do projeto |
| O cabeçalho diz `Ollama local` | A `OLLAMA_API_KEY` não foi lida. Confira se o arquivo se chama `.env` (e não `.env.txt`) |
| `Connection closed` / `Falha no servidor MCP` | O servidor quebrou ao iniciar. A causa está em `registros/servidor_mcp.log` |
| `unable to open database file` | Um caminho aponta para uma pasta que não existe. Confira os nomes `data` e `manuals` no código |
| `metodo: lexical (sem embeddings: ...)` | A busca caiu no plano B. O motivo está entre parênteses |
| `trechos: []` em todo equipamento | A pasta dos manuais está com outro nome no `busca.py` |
| `No module named 'agente'` | Um script numa subpasta precisa acrescentar a pasta do projeto ao `sys.path` (como em `test/teste_servidor.py`) |
| `status: limite` | O modelo usou todas as rodadas pedindo ferramentas. Confira o `MAX_RODADAS` |
| Mudei o código e nada mudou | O Python lê os arquivos ao iniciar. Pare (`Ctrl+C`) e rode de novo |
| O Windows não apaga o `fabrica.sqlite` | O app está rodando e usando o arquivo. Pare o app antes |

**Dica para depurar:** leia o traceback de baixo para cima. A última linha diz **o que**
aconteceu; a linha `File "...", line N` logo acima diz **onde**. Para isolar uma camada,
chame a função direto, sem o resto do sistema, por exemplo:

```powershell
python -c "import busca; print(busca.buscar('EST-02', 'E-12')['metodo'])"
```

---

## Limitações conhecidas

- **O prompt é um pedido, não uma garantia.** O modelo às vezes pula passos ou erra o
  texto. Por isso, o que é essencial (permissões, validação, duplicatas e aprovação) está
  no **código**.
- **Duplicatas sem código de erro** só são detectadas quando o sintoma é escrito igual.
- **Não há ferramenta para consultar um chamado existente.** Uma ferramenta
  `consultar_chamado` é o próximo passo natural.
- **Um servidor por atendimento:** no modo stdio, cada mensagem inicia o servidor
  (cerca de 1 s a mais). Para uso contínuo, o modo HTTP evita isso.
- **Uso local e de uma pessoa por vez:** sem login nem controle de quem aprova.
- **Dados fictícios:** os manuais e os procedimentos não valem para equipamentos reais.

---

## Relação com as aulas

| Aula | Onde aparece no projeto |
|---|---|
| 1. Fundamentos de agentes | Escopo, aprovação humana, recusa de ações, "responder não é executar" |
| 2. LLMs e ambiente | Ollama Cloud, temperatura baixa, erros explicados com dicas, registros |
| 3. Python e APIs | `.venv`, `requirements.txt`, configuração no `.env` |
| 4. Técnicas de prompt | Prompt com tarefa, contexto, procedimento e limites; casos de teste |
| 5. RAG | Trechos por seção, embeddings, cache, filtro, busca por palavras, citação da fonte |
| 6. Agente como laço | `atender`: chamar, inspecionar, executar, repetir, parar com status |
| 7. Composição de ferramentas | Ferramentas encadeadas, memória de trabalho (histórico) |
| 8. Robustez e delegação | Tempo limite, novas tentativas, duplicatas, os quatro limites, avaliação |
| 9. MCP e multiagentes | Servidor MCP, `tools/list`, `tools/call`, conversão de esquema, permissões |
