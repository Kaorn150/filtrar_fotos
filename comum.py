#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Funções compartilhadas entre analisar.py e filtrar.py."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# expressão que acha o array de perfis dentro do HTML
RE_PERFIS = re.compile(r"(const PERFIS = )(\[.*?\])(;\s*\r?\n)", re.S)


def falar(*args):
    """print que não quebra no console do Windows (cp1252)."""
    try:
        print(*args)
    except UnicodeEncodeError:
        print(*[str(a).encode("ascii", "replace").decode() for a in args])


def arrumar_saida():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def carregar_perfis(caminho_html):
    """Lê o HTML e devolve (texto, lista de perfis)."""
    caminho = Path(caminho_html)
    with open(caminho, "r", encoding="utf-8", newline="") as f:
        texto = f.read()
    m = RE_PERFIS.search(texto)
    if not m:
        raise SystemExit(
            "Não achei o array 'const PERFIS = [...];' dentro de %s" % caminho
        )
    perfis = json.loads(m.group(2))
    return texto, perfis, m


def escrever_html(texto_original, perfis, destino):
    """Gera um novo HTML com a lista de perfis informada."""
    with open(destino, "w", encoding="utf-8", newline="") as f:
        f.write(RE_PERFIS.sub(lambda m: m.group(1) + dump(perfis) + m.group(3), texto_original, count=1))


def dump(perfis):
    """JSON no mesmo formato do arquivo original (acentos/emoji legíveis)."""
    return json.dumps(perfis, ensure_ascii=False, separators=(", ", ": "))


def ler_imagem(caminho):
    """Abre a imagem tolerando caminhos com acento/emoji (problema clássico no Windows)."""
    import cv2
    import numpy as np

    dados = np.fromfile(str(caminho), dtype=np.uint8)
    if dados.size == 0:
        return None
    return cv2.imdecode(dados, cv2.IMREAD_COLOR)


def achar_imagem(pasta, usuario, img_rel=None):
    """Localiza o arquivo do perfil dentro de uma pasta (miniaturas/ ou fotos/).

    Tenta, nesta ordem:
      1. o caminho que veio no HTML (img);
      2. <usuario>.<ext>;
      3. qualquer arquivo que comece com <usuario>. ou <usuario>_
    """
    if img_rel:
        p = Path(img_rel)
        if not p.is_absolute():
            cand = Path(pasta) / p
            if cand.is_file():
                return cand
            # às vezes o HTML aponta para miniaturas/ e estamos olhando fotos/
            cand = Path(pasta) / p.name
            if cand.is_file():
                return cand
    base = Path(pasta)
    if not base.is_dir():
        return None
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        cand = base / (usuario + ext)
        if cand.is_file():
            return cand
    try:
        arquivos = [a for a in base.iterdir() if a.is_file()]
    except OSError:
        return None
    for arq in arquivos:
        if arq.name.startswith(usuario + ".") or arq.name.startswith(usuario + "_"):
            return arq
    # último recurso: o @ aparece em qualquer lugar do nome do arquivo
    for arq in sorted(arquivos):
        if usuario and usuario in arq.name:
            return arq
    return None
