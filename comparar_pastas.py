#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparar_pastas.py — responde se fotos/ e miniaturas/ são a mesma imagem
(só com tamanhos diferentes) ou se são conteúdos diferentes.

Uso:
  python comparar_pastas.py                 # compara fotos/ com miniaturas/
  python comparar_pastas.py --n 30          # compara 30 pares em vez de 15
  python comparar_pastas.py --a fotos --b miniaturas
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

from comum import achar_imagem, arrumar_saida, falar, ler_imagem


def tamanho_legivel(n_bytes):
    kb = n_bytes / 1024.0
    return "%.0f KB" % kb if kb < 1024 else "%.1f MB" % (kb / 1024.0)


def formas(pasta):
    """Conta arquivos de imagem e as dimensões."""
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    arquivos = [a for a in Path(pasta).iterdir()
                if a.is_file() and a.suffix.lower() in exts] if Path(pasta).is_dir() else []
    return arquivos


def correlacao(img1, img2):
    """Correlação dos histogramas de cor: 1.0 = idênticos, 0 = nada a ver."""
    cs = []
    for i in range(3):
        h1 = cv2.calcHist([img1], [i], None, [32], [0, 256]).flatten()
        h2 = cv2.calcHist([img2], [i], None, [32], [0, 256]).flatten()
        h1 = h1 / (h1.sum() + 1e-6)
        h2 = h2 / (h2.sum() + 1e-6)
        c = float(np.sum(np.sqrt(h1 * h2)))
        cs.append(c)  # Bhattacharyya: 1.0 = igual
    return sum(cs) / 3.0


def comparar(im_a, im_b):
    """Redimensiona a maior para o tamanho da menor e mede a diferença."""
    ha, wa = im_a.shape[:2]
    hb, wb = im_b.shape[:2]
    if ha * wa >= hb * wb:
        alvo, base, outro = (wb, hb), im_b, im_a
    else:
        alvo, base, outro = (wa, ha), im_a, im_b
    red = cv2.resize(outro, alvo, interpolation=cv2.INTER_AREA)
    dif = float(np.mean(np.abs(red.astype(np.float32) - base.astype(np.float32))))
    prop_a, prop_b = wa / ha, wb / hb
    mesmo_formato = abs(prop_a - prop_b) < 0.02
    return dif, correlacao(red, base), mesmo_formato


def principal():
    arrumar_saida()
    aqui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Compara as pastas fotos/ e miniaturas/.")
    ap.add_argument("--pasta", default=str(aqui), help="pasta do projeto")
    ap.add_argument("--html", default="galeria.html", help="HTML com a lista de perfis")
    ap.add_argument("--a", default="fotos", help="primeira pasta (padrão: fotos)")
    ap.add_argument("--b", default="miniaturas", help="segunda pasta (padrão: miniaturas)")
    ap.add_argument("--n", type=int, default=15, help="quantos pares comparar")
    args = ap.parse_args()

    pasta = Path(args.pasta)
    pa, pb = pasta / args.a, pasta / args.b
    if not pa.is_dir() and not pb.is_dir():
        raise SystemExit("Não achei nem %s/ nem %s/ em %s" % (args.a, args.b, pasta))

    arq_a, arq_b = formas(pa), formas(pb)
    falar("\n============ %s/ x %s/ ============" % (args.a, args.b))
    falar("Arquivos: %s/ = %d   ·   %s/ = %d" % (args.a, len(arq_a), args.b, len(arq_b)))
    if arq_a and arq_b:
        r = len(arq_a) / max(1, len(arq_b))
        if r > 1.6:
            falar("  -> %s/ tem %.1fx mais arquivos. Pode ser mais de uma foto por pessoa."
                  % (args.a, r))
        elif r < 0.6:
            falar("  -> %s/ tem %.1fx mais arquivos. Pode ser mais de uma foto por pessoa."
                  % (args.b, 1 / r))

    # usuários do HTML
    usuarios = []
    html = pasta / args.html
    if html.is_file():
        with open(html, "r", encoding="utf-8", newline="") as f:
            texto = f.read()
        m = re.search(r"const PERFIS = (\[.*?\]);", texto, re.S)
        if m:
            usuarios = [p["u"] for p in json.loads(m.group(1))]
    if not usuarios:
        usuarios = sorted({a.name.split(".")[0] for a in (arq_b or arq_a)})

    def dims(pasta_x, u, img_rel):
        arq = achar_imagem(pasta_x, u, img_rel)
        if not arq:
            return None, None
        im = ler_imagem(arq)
        if im is None:
            return arq, None
        return arq, (im.shape[1], im.shape[0])

    img_rel = {p.get("u"): p.get("img") for p in json.loads(m.group(1))} if usuarios and html.is_file() else {}
    amostra = usuarios[: max(1, args.n) * 12]
    pares, so_a, so_b = [], 0, 0
    for u in amostra:
        if len(pares) >= args.n:
            break
        xa = achar_imagem(pa, u, img_rel.get(u))
        xb = achar_imagem(pb, u, img_rel.get(u))
        if xa and xb:
            pares.append((u, xa, xb))
        elif xa and not xb:
            so_a += 1
        elif xb and not xa:
            so_b += 1

    if not pares:
        falar("\nNão achei arquivos com o mesmo @ nas duas pastas.")
        falar("Os nomes devem ser diferentes. Exemplo de arquivos encontrados:")
        for a in (arq_a[:3] + arq_b[:3]):
            falar("   %s/%s" % (a.parent.name, a.name))
        return

    falar("\n%-24s %-14s %-14s %-9s %-7s %s" % ("@", args.a, args.b, "tamanho KB", "diferença", "mesma?"))
    diffs, corrs, mesmo_fmt = [], [], True
    for u, xa, xb in pares:
        ia, ib = ler_imagem(xa), ler_imagem(xb)
        if ia is None or ib is None:
            continue
        dif, corr, fmt = comparar(ia, ib)
        diffs.append(dif)
        corrs.append(corr)
        mesmo_fmt = mesmo_fmt and fmt
        ta = xa.stat().st_size
        tb = xb.stat().st_size
        veredito = "SIM" if (dif < 18 and corr > 0.93) else ("talvez" if dif < 35 else "NÃO")
        falar("%-24s %-14s %-14s %-9s %-7.1f %s" % (
            "@" + u[:23],
            "%dx%d" % (ia.shape[1], ia.shape[0]),
            "%dx%d" % (ib.shape[1], ib.shape[0]),
            "%s/%s" % (tamanho_legivel(ta).replace(" ", ""), tamanho_legivel(tb).replace(" ", "")),
            dif, veredito))

    if not diffs:
        return
    media_dif = sum(diffs) / len(diffs)
    media_corr = sum(corrs) / len(corrs)
    falar("\n------------------------------------------------")
    falar("Diferença média de pixels: %.1f (0 = idênticas, 100+ = outra foto)" % media_dif)
    falar("Correlação de cor média:   %.2f (1.00 = idênticas)" % media_corr)
    falar("Mesmo formato (quadrada/retângulo): %s" % ("sim" if mesmo_fmt else "não"))
    if so_a:
        falar("Só existem em %s/: %d da amostra" % (args.a, so_a))
    if so_b:
        falar("Só existem em %s/: %d da amostra" % (args.b, so_b))

    falar("")
    if media_dif < 18 and media_corr > 0.93:
        falar("CONCLUSÃO: é a MESMA foto nas duas pastas — só muda o tamanho.")
        falar("  · pode medir por miniaturas/ (mais rápido) e exibir por fotos/")
        falar("  · rode depois:  python filtrar.py --usar fotos")
    elif media_dif > 35:
        falar("CONCLUSÃO: o conteúdo é DIFERENTE (não é só redimensionamento).")
        falar("  · mantenha o analisar.py medindo miniaturas/ (é o que o HTML usa)")
        falar("  · e NÃO use --usar fotos, senão a galeria final mostra outra imagem")
    else:
        falar("CONCLUSÃO: parecidas, mas com diferença acima do normal de um redimensionamento.")
        falar("  · pode ser crop ou compressão forte. Olhe um par com calma antes de decidir.")


if __name__ == "__main__":
    principal()
