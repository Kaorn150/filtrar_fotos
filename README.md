# Filtrar fotos — só mulheres de cabelo preto

Dois scripts Python que leem o `galeria.html`, medem o tom do cabelo de cada foto
e geram uma galeria nova só com quem passou no filtro.

```
analisar.py   ->  mede as 4000 fotos      -> analise.json + galeria_medida.html
filtrar.py    ->  aplica o corte          -> galeria_final.html + selecionadas/
```

O `galeria.html` original já tem filtro de "cabelo preto", slider de tom e triagem
manual — mas os campos `ct` (tom do cabelo), `t` (pele) e `r` (tem rosto) estavam
vazios. O `analisar.py` é quem preenche isso.

---

## 1. Instalar (só na primeira vez)

Tenha o [Python 3.10+](https://www.python.org/downloads/) instalado (marque
"Add Python to PATH"). Dê dois cliques em **`instalar.bat`** na pasta do projeto.
Ele cria o ambiente virtual, instala OpenCV + NumPy e já faz um teste com 30 fotos.

Pela linha de comando, se preferir:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Não precisa baixar nenhum modelo: o detector de rosto já vem dentro do OpenCV.

## 2. Medir as fotos

Dê dois cliques em **`analisar.bat`** (ou `python analisar.py`).
Leva de 1 a 5 minutos para 4000 miniaturas. Ao final ele mostra a distribuição:

```
=== DISTRIBUIÇÃO DO TOM DE CABELO (3950 de 4022) ===
  preto                      1210  ####################
  castanho muito escuro       640  ##########
  castanho escuro             510  ########
  castanho                    780  ############
  castanho claro              410  #######
  loiro / claro               400  #######
```

Escala: `0 = preto` · `~25 castanho muito escuro` · `~50 castanho` · `~85 loiro`.

Gerou dois arquivos: `analise.json` (os números) e `galeria_medida.html`
(a galeria inteira com as medições, para você conferir e triar).

Dicas:

```bat
python analisar.py --limite 60 --debug 20   :: teste rápido + desenhos de conferência
python analisar.py --retomar                :: continua de onde parou
python analisar.py --imagens fotos          :: medir a pasta fotos/ em vez de miniaturas/
```

A pasta `debug/` mostra o que o script mediu: retângulo amarelo = rosto,
magenta = cabeça, verde = faixa do cabelo.

## Qual pasta de imagem o HTML usa?

O `galeria.html` aponta para **`miniaturas/`** (todos os 4020 perfis com foto usam
`miniaturas/usuario.jpg`). A pasta `fotos/` não é usada em lugar nenhum do HTML.

Diferença na prática:

| onde aparece | tamanho na tela | miniatura dá conta? |
|---|---|---|
| grade de cartões | ~140 px ou mais | sim |
| varredura | ~78 px | sim, sobra |
| **tela de triagem** | foto grande | **depende — abaixo de ~320 px fica borrada** |

O `analisar.py` agora imprime o tamanho das imagens e avisa se forem pequenas:

```
Tamanho das imagens: 150x150 em média (menor lado 150, maior lado 150)
  Aviso: tem imagem pequena (150  px). Na tela de triagem ela vai ficar borrada.
         Use --usar fotos no filtrar.py para o HTML apontar para a pasta fotos/.
```

Para a galeria final usar as fotos grandes em vez das miniaturas:

```bat
python filtrar.py --usar fotos
```

Ele procura o arquivo de cada aprovado dentro de `fotos/` (aceita nome diferente,
contanto que o @ apareça no nome) e reescreve o caminho; quem não achar mantém o
caminho de `miniaturas/`. A cópia para `selecionadas/` continua saindo da pasta
`fotos/` por padrão, caindo para `miniaturas/` se faltar arquivo.

Dá também para medir direto as fotos grandes, se quiser mais detalhe na medição
(mais demorado): `python analisar.py --imagens fotos`.

## 3. Conferir o corte (importante)

Abra o `galeria_medida.html`, ordene por **"mais escuro"** e vá rolando.
Veja em que valor de `ct` o cabelo preto acaba e o castanho começa — o número
aparece na etiqueta `cabelo NN` de cada cartão. Use esse valor no passo 4.
O slider "tom ≤" do topo faz esse teste ao vivo.

## 4. Gerar a galeria final

Dê dois cliques em **`filtrar.bat`** (ou `python filtrar.py`). Padrão:
`ct <= 30`, exige rosto detectado, e descarta quem o palpite por nome diz que é homem.

```bat
python filtrar.py --corte 22          :: mais rigoroso (só preto mesmo)
python filtrar.py --corte 45          :: aceita castanho escuro
python filtrar.py --genero F          :: só o palpite feminino (1348 perfis)
python filtrar.py --genero todos      :: ignora gênero
python filtrar.py --sem-rosto         :: aceita fotos sem rosto detectado
python filtrar.py --ver               :: só mostra o resumo, não grava nada
```

Saída:

| arquivo | o que é |
|---|---|
| `galeria_final.html` | a galeria só com as aprovadas, ordenada da mais escura para a mais clara |
| `selecionadas.txt` | lista dos @ aprovados |
| `selecionadas/` | cópia das fotos (tenta a pasta `fotos/` primeiro, senão `miniaturas/`) |

Dentro do `galeria_final.html` você ainda pode usar os chips de gênero (F?),
marcar ★ / ✕ e filtrar "só candidatas" — a triagem manual continua funcionando.

---

## Como a medição funciona

1. Acha o rosto (cascata frontal + perfil do OpenCV).
2. Acha a **cabeça** pela maior mancha de pele, conferindo com a caixa do rosto.
3. Recorta a faixa logo acima e dos lados da cabeça e remove os pixels de pele.
4. Agrupa as cores dessa faixa em até 4 grupos (k-means no espaço CIELAB) e
   escolhe o grupo com cara de cabelo: dentro das colunas da cabeça, perto do
   topo, com textura (fundo de parede é liso) e longe da borda da imagem.
5. `ct` = mediana da luz L* daquele grupo (0 a 100).

O `esc30` (mediana dos 30% mais escuros da faixa) fica salvo junto e serve de
plano B: `--corte-escuro 20` cobra que a faixa seja escura de verdade, o que
derruba bastante os falsos positivos de fundo escuro.

## Limites conhecidos

* **Fundo escuro** pode ser lido como cabelo preto. Use `--corte-escuro 20`
  ou `--min-frac 15` para reduzir.
* **Gênero** não é detectado na imagem: o script usa o palpite por nome que já
  vem no HTML (`g`). Quem está como `?` entra por padrão — descarte na triagem
  ou rode com `--genero F` para ser rigoroso.
* Cabelo com luz forte, tintura colorida, boné, touca ou foto de corpo inteiro
  erram mais. Por isso a triagem manual no HTML continua sendo o passo final.
