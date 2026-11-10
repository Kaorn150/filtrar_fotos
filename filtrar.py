#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
filtrar.py — usa o analise.json (gerado pelo analisar.py) e produz:

  * galeria_final.html  -> o mesmo visual do galeria.html, mas só com quem passou
  * selecionadas/       -> cópia das fotos aprovadas (opcional, padrão: ligado)
  * selecionadas.txt    -> lista dos @ aprovados

Exemplos:
  python filtrar.py                          # cabelo preto (ct <= 30) + rosto + palpite feminino/indefinido
  python filtrar.py --corte 22               # mais rigoroso
  python filtrar.py --genero F               # só quem o palpite por nome diz que é mulher
  python filtrar.py --sem-rosto              # aceita também fotos sem rosto detectado
  python filtrar.py --ver                    # só mostra o resumo, não grava nada
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from comum import RE_PERFIS, achar_imagem, arrumar_saida, carregar_perfis, dump, falar

FAIXAS = [(0, 25, "preto"), (25, 35, "castanho muito escuro"), (35, 50, "castanho escuro"),
          (50, 65, "castanho"), (65, 80, "castanho claro"), (80, 101, "loiro / claro")]


def principal():
    arrumar_saida()
    aqui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Filtra as fotos por tom de cabelo e gênero.")
    ap.add_argument("--pasta", default=str(aqui), help="pasta do projeto")
    ap.add_argument("--html", default=None,
                    help="HTML base (padrão: galeria_medida.html, senão galeria.html)")
    ap.add_argument("--analise", default="analise.json", help="JSON gerado pelo analisar.py")
    ap.add_argument("--saida", default="galeria_final.html", help="HTML filtrado")
    ap.add_argument("--corte", type=int, default=30, help="ct máximo (0-100). 30 = preto/castanho escuro")
    ap.add_argument("--corte-escuro", type=int, default=None,
                    help="exige também que os 30%% mais escuros da faixa sejam <= este valor")
    ap.add_argument("--genero", choices=["F", "F?", "todos"], default="F?",
                    help="F = só palpite feminino · F? = feminino + indefinido (padrão) · todos")
    ap.add_argument("--sem-rosto", action="store_true", help="não exige rosto detectado")
    ap.add_argument("--min-frac", type=int, default=0,
                    help="exige que o tom medido ocupe pelo menos N%% da faixa (0 = não exige)")
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="exige confiança mínima na medição (0 = não exige)")
    ap.add_argument("--ordem", choices=["tom", "nome", "original"], default="tom")
    ap.add_argument("--origem", choices=["auto", "fotos", "miniaturas"], default="auto",
                    help="de onde copiar as fotos (auto = tenta fotos/ e cai para miniaturas/)")
    ap.add_argument("--sem-copiar", action="store_true", help="não copia as fotos")
    ap.add_argument("--pasta-fotos", default="selecionadas", help="destino das cópias")
    ap.add_argument("--usar", choices=["miniaturas", "fotos"], default=None,
                    help="faz o HTML final apontar para esta pasta (padrão: mantém o original)")
    ap.add_argument("--titulo", default=None, help="título do HTML final")
    ap.add_argument("--ver", action="store_true", help="só mostra o resumo, não grava nada")
    args = ap.parse_args()

    pasta = Path(args.pasta)
    html_path = None
    if args.html:
        html_path = pasta / args.html
    else:
        for nome in ("galeria_medida.html", "galeria.html"):
            if (pasta / nome).is_file():
                html_path = pasta / nome
                break
    if not html_path or not html_path.is_file():
        raise SystemExit("Não achei o HTML base na pasta %s (use --html)." % pasta)

    json_path = pasta / args.analise
    if not json_path.is_file():
        raise SystemExit("Não achei %s. Rode primeiro:  python analisar.py" % json_path)

    dados = json.loads(json_path.read_text(encoding="utf-8"))
    itens = dados.get("itens", [])
    if not itens:
        raise SystemExit("O %s não tem itens. Rode o analisar.py de novo." % json_path.name)

    texto, perfis, _ = carregar_perfis(html_path)
    por_u = {p["u"]: p for p in perfis}
    analise_por_u = {i["u"]: i for i in itens}

    def passar(i):
        if i.get("ct") is None:
            return False, "sem medição"
        if i["ct"] > args.corte:
            return False, "tom claro"
        if args.corte_escuro is not None and (i.get("esc30") or 999) > args.corte_escuro:
            return False, "faixa clara"
        if not args.sem_rosto and not i.get("r"):
            return False, "sem rosto"
        g = i.get("g") or "?"
        if args.genero == "F" and g != "F":
            return False, "palpite " + ("masculino" if g == "M" else "indefinido")
        if args.genero == "F?" and g == "M":
            return False, "palpite masculino"
        if args.min_frac and (i.get("frac") or 0) < args.min_frac:
            return False, "pouco cabelo"
        if args.min_score and (i.get("score") or 0) < args.min_score:
            return False, "medição fraca"
        return True, ""

    escolhidos, motivos = [], {}
    for i in itens:
        ok, motivo = passar(i)
        if ok:
            escolhidos.append(i)
        elif motivo:
            motivos[motivo] = motivos.get(motivo, 0) + 1

    if args.ordem == "tom":
        escolhidos.sort(key=lambda i: (i["ct"], i.get("esc30") or 0, i["u"]))
    elif args.ordem == "nome":
        escolhidos.sort(key=lambda i: (i.get("n") or i["u"]).lower())
    else:
        ordem_original = [p["u"] for p in perfis]
        escolhidos.sort(key=lambda i: ordem_original.index(i["u"]) if i["u"] in ordem_original else 1e9)

    # ------------------------------------------------------------- resumo
    falar("\n================ RESUMO ================")
    falar("Perfis no HTML .......... %d" % len(perfis))
    falar("Analisados .............. %d" % len(itens))
    falar("Com tom medido .......... %d" % sum(1 for i in itens if i.get("ct") is not None))
    falar("")
    falar("Corte usado: ct <= %d%s · gênero: %s · rosto: %s"
          % (args.corte,
             (" e 30%% mais escuro <= %d" % args.corte_escuro) if args.corte_escuro is not None else "",
             args.genero, "obrigatório" if not args.sem_rosto else "não exigido"))
    falar("APROVADOS ............... %d" % len(escolhidos))
    por_g = {}
    for i in escolhidos:
        por_g[i.get("g") or "?"] = por_g.get(i.get("g") or "?", 0) + 1
    falar("  por palpite de nome: " + ", ".join("%s=%d" % (k, v) for k, v in sorted(por_g.items())))
    if motivos:
        falar("\nDescartados:")
        for m, q in sorted(motivos.items(), key=lambda t: -t[1]):
            falar("  %-18s %d" % (m, q))
    if escolhidos:
        falar("\nTom das aprovadas:")
        for a, b, nome in FAIXAS:
            q = sum(1 for i in escolhidos if a <= i["ct"] < b)
            if q:
                falar("  %-22s %4d  %s" % (nome, q, "#" * min(50, q)))

    if args.ver:
        falar("\n( modo --ver: nada foi gravado )")
        return

    # ------------------------------------------------------- HTML final
    novos = []
    for i in escolhidos:
        p = por_u.get(i["u"])
        if not p:
            continue
        p = dict(p)
        p["ct"] = i.get("ct")
        p["t"] = i.get("t")
        p["r"] = bool(i.get("r"))
        novos.append(p)
    if args.usar:
        alvo = pasta / args.usar
        if alvo.is_dir():
            trocados = 0
            for p in novos:
                arq = achar_imagem(alvo, p["u"], p.get("img"))
                if arq:
                    p["img"] = "%s/%s" % (args.usar, arq.name)
                    trocados += 1
            falar("Caminho das fotos trocado para %s/: %d de %d" % (args.usar, trocados, len(novos)))
            if trocados < len(novos):
                falar("  %d ficaram com o caminho original (arquivo não achado em %s/)"
                      % (len(novos) - trocados, args.usar))
        else:
            falar("Aviso: a pasta %s/ não existe, mantive os caminhos originais." % args.usar)

    destino = pasta / args.saida
    with open(destino, "w", encoding="utf-8", newline="") as f:
        f.write(RE_PERFIS.sub(lambda m: m.group(1) + dump(novos) + m.group(3), texto, count=1))
    falar("\nHTML final: %s (%d perfis)" % (destino, len(novos)))

    # -------------------------------------------------------- lista txt
    txt = pasta / "selecionadas.txt"
    txt.write_text("\n".join("@" + p["u"] for p in novos), encoding="utf-8")
    falar("Lista:      %s" % txt)

    # ---------------------------------------------------------- cópias
    if args.sem_copiar:
        return
    pasta_img = Path(dados.get("pasta_imagens") or (pasta / "miniaturas"))
    if not pasta_img.is_dir():
        pasta_img = pasta / "miniaturas"
    candidatas = []
    if args.origem in ("auto", "fotos"):
        fotos = pasta / "fotos"
        if fotos.is_dir():
            candidatas.append(fotos)
    if args.origem in ("auto", "miniaturas"):
        if pasta_img.is_dir():
            candidatas.append(pasta_img)
    if not candidatas:
        candidatas.append(pasta_img)

    dest = pasta / args.pasta_fotos
    dest.mkdir(exist_ok=True)
    copiados, faltando = 0, []
    for p in novos:
        alvo = None
        for pasta_orig in candidatas:
            alvo = achar_imagem(pasta_orig, p["u"], p.get("img"))
            if alvo:
                break
        if not alvo:
            faltando.append(p["u"])
            continue
        sufixo = alvo.suffix or ".jpg"
        shutil.copy2(alvo, dest / (p["u"] + sufixo))
        copiados += 1
    falar("Fotos copiadas para %s/: %d" % (args.pasta_fotos, copiados))
    if faltando:
        falar("  sem arquivo encontrado (%d): %s%s"
              % (len(faltando), ", ".join(faltando[:8]), "..." if len(faltando) > 8 else ""))
    falar("\nPronto! Abra %s no navegador." % args.saida)


if __name__ == "__main__":
    principal()
