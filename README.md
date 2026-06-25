# 🗡️ Albion Market Track

Ferramenta para encontrar oportunidades de arbitragem no **Black Market** do Albion Online.  
Você captura os preços do mercado enquanto navega no jogo, e o app mostra quais itens comprar nas cidades para vender no Black Market com lucro.

---

## 📋 O que você vai precisar instalar (só uma vez)

Instale os dois programas abaixo. São gratuitos.

### 1. Node.js
> É o motor que roda o servidor interno do app.

- Acesse: **https://nodejs.org**
- Clique no botão verde **"LTS"** (versão recomendada)
- Baixe e instale normalmente (next, next, finish)

### 2. Albion Data Client
> É o programa que lê os dados do mercado enquanto você joga.

- Acesse: **https://github.com/ao-data/albiondata-client/releases**
- Baixe o arquivo mais recente para Windows e instale normalmente

> ✅ **Não precisa instalar Python.** O app já vem empacotado como `.exe` e traz tudo que precisa.

---

## 📥 Instalando o Albion Market Track

### Passo 1 — Baixe o projeto

Clique em **Code → Download ZIP** nesta página e extraia a pasta onde quiser (ex: `C:\Albion Market Track`).

### Passo 2 — Instale as dependências do servidor (só uma vez)

**1.** Abra a pasta que você extraiu  
**2.** Entre na pasta **`albion-scanner`**  
**3.** Clique na barra de endereço do Windows Explorer, apague o que está escrito, digite `cmd` e pressione **Enter**  
**4.** Na janela preta que abrir, digite o comando abaixo e pressione Enter:

```
npm install
```

**5.** Aguarde terminar (pode demorar 1-2 minutos). Quando voltar para o cursor normal, está pronto.

---

## ▶️ Como abrir o app

Dê **dois cliques** no arquivo **`iniciar-scanner.bat`** que está na pasta do projeto.  
Uma janela vai aparecer pedindo permissão de administrador — clique em **Sim**.

> ⚠️ **Precisa ser como Administrador!** O app captura pacotes de rede, o que exige permissão elevada no Windows. Sem isso, não vai funcionar.

O app abre automaticamente.

---

## 🎮 Como usar — passo a passo

### Antes de tudo: Capture a zona da cidade (só na primeira vez por cidade)

O app precisa saber em qual cidade você está. Você faz isso **uma vez por cidade** e nunca mais precisa repetir.

**1.** Abra o app  
**2.** No campo **"Cidade"** (canto superior esquerdo), selecione a cidade onde você quer capturar preços  
**3.** Clique no botão **"⬡ Cap. zona"**  
**4.** O app vai mostrar uma contagem regressiva — abra o Albion Online e **entre na cidade selecionada** (ou saia dela, qualquer troca de mapa serve)  
**5.** Quando o app detectar a zona, o status muda para **"✓ Zona pronta"** em verde

> 💡 **Dica:** Black Market usa a mesma zona que Caerleon. Se você já capturou Caerleon, já serve para o Black Market também.

---

### Capturando preços do mercado

**1.** Selecione a cidade no campo **"Cidade"**  
**2.** Clique em **"▶ Iniciar Captura"**  
**3.** No jogo, **vá ao mercado** da cidade e navegue pelos itens normalmente  
 - Abra categorias, veja preços, busque itens — qualquer coisa que carregue a lista de preços  
 - Quanto mais categorias você abrir, mais dados o app vai ter  
**4.** Quando terminar, clique em **"■ Finalizar"**  
**5.** Aguarde alguns segundos — o app vai processar e preencher a tabela automaticamente

> ⏱️ O temporizador no canto superior direito mostra há quanto tempo você está capturando.

---

### Capturando o Black Market

O Black Market fica em **Caerleon**. Para capturar os preços dele:

**1.** Selecione **"Black Market"** no campo Cidade  
**2.** Clique em **"▶ Iniciar Captura"**  
**3.** No jogo, entre no **Black Market** em Caerleon e navegue pelos itens  
**4.** Clique em **"■ Finalizar"** quando terminar

---

## 📊 Entendendo as abas

### Aba "Mercado"

Mostra todos os itens capturados com:

| Coluna | O que significa |
|--------|----------------|
| **Item** | Nome do item (com tier e encantamento) |
| **Cidade** | Onde foi capturado |
| **Qual.** | Qualidade (Normal, Good, Outstanding...) |
| **Venda mín.** | Menor preço de venda disponível |
| **Qtd venda** | Quantos estão à venda |
| **Média 24h** | Preço médio vendido nas últimas 24h |
| **Capturado** | Há quanto tempo foi capturado |

Clique no cabeçalho de qualquer coluna para ordenar.

---

### Aba "Arbitragem BM"

Esta é a aba principal! Ela cruza os preços das cidades com os do Black Market e mostra onde tem lucro.

| Coluna | O que significa |
|--------|----------------|
| **Item** | Nome do item |
| **Qual.** | Qualidade |
| **Cidade** | Cidade mais barata para comprar |
| **Preço cidade** | Quanto custa comprar na cidade |
| **BM ordem venda** | Preço que os jogadores estão pedindo no Black Market |
| **Lucro** | Quanto você ganha por item (já descontando a taxa) |
| **% Lucro** | Percentual de lucro |
| **Em venda BM** | Quantos estão sendo vendidos no BM agora |
| **Vend. 24h** | Quantos foram vendidos nas últimas 24 horas |
| **Média BM** | Preço médio que o BM pagou nas últimas 24h |

> 🟢 **Verde** = lucro positivo | 🔴 **Vermelho** = prejuízo

---

## 🔧 Filtros da Arbitragem

### Taxa %
Ajuste a taxa de mercado cobrada pelo Black Market. O padrão é **10%**.

### Barra de filtros

| Filtro | Como usar |
|--------|-----------|
| **Nome** | Digite parte do nome do item para filtrar |
| **Tier** | Marque/desmarque os tiers que quer ver (T1 a T8) |
| **Enc.** | Filtra por encantamento (.0 = sem encantamento, .1/.2/.3 = encantados) |
| **Lucro % ≥** | Digite um número mínimo de lucro (ex: `90` mostra só itens com mais de 90% de lucro) |

---

## ✏️ Editando preços manualmente

Se você viu um preço diferente no jogo e quer recalcular o lucro com o valor real:

**1.** Na aba Arbitragem BM, dê **duplo-clique** na célula **"Preço cidade"** ou **"BM ordem venda"**  
**2.** Digite o novo valor (pode usar ponto como separador de milhar, ex: `38.500`)  
**3.** Pressione **Enter** para confirmar — o lucro e % são recalculados automaticamente  
**4.** O item fica destacado em **laranja** para indicar que foi editado manualmente  
**5.** Para remover a edição e voltar ao valor original, dê duplo-clique e pressione **Delete**

---

## 🗑️ Limpando os dados

- **"Limpar dados"** — apaga tudo e começa do zero  
- **"Limpar cidade"** — apaga só os dados da cidade selecionada no filtro

---

## ❓ Problemas comuns

### O app abre mas a tabela fica vazia
Você precisa capturar os dados primeiro. Siga os passos da seção "Capturando preços do mercado".

### Aparece "Dados sem localização"
Você não capturou a zona da cidade ainda. Clique em "⬡ Cap. zona" e troque de mapa no jogo.

### O app fecha sozinho ou dá erro de permissão
Certifique-se de abrir via `iniciar-scanner.bat` e clicar em **Sim** na janela de admin.

### A aba Arbitragem BM está vazia
Você precisa capturar dados tanto de uma **cidade** quanto do **Black Market**. Faça as duas capturas e depois veja a aba Arbitragem.

### Node.js não encontrado / servidor não inicia
Certifique-se de que o **Node.js está instalado** e que a pasta **`albion-scanner`** está na mesma pasta que o `iniciar-scanner.bat`.

### Os nomes dos itens aparecem em código (ex: `T4 ARMOR CLOTH SET1`)
Normal na primeira vez. O app busca os nomes em português automaticamente em segundo plano. Aguarde alguns segundos e a tabela vai atualizar sozinha.

---

## 📁 Estrutura de arquivos

```
Albion-Market-Track/
├── dist/
│   └── Albion Market.exe   ← Executável do app
├── iniciar-scanner.bat     ← Clique duas vezes aqui para abrir
├── captura_gui.py          ← Código-fonte
└── albion-scanner/
    ├── server.js
    ├── package.json
    └── node_modules/       ← Criado pelo "npm install"
```

---

## 📝 Licença

Projeto pessoal para uso no Albion Online. Não afiliado à Sandbox Interactive.
