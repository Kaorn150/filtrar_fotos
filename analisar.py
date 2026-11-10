#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analisar.py — mede o TOM DO CABELO (ct), o TOM DE PELE (t) e a presença de
ROSTO (r) em cada miniatura listada no galeria.html.

Gera dois arquivos:
  * analise.json        -> todas as medições (usado depois pelo filtrar.py)
  * galeria_medida.html -> o próprio galeria.html com ct / t / r preenchidos

Escala de ct (0..100, igual à que o HTML já espera — luz L* do CIELAB):
  preto ~10-25 · castanho escuro ~25-35 · castanho ~45-60 · loiro ~70-90

Como funciona (resumo):
  1. acha o rosto (cascata do OpenCV, frontal + perfil);
  2. acha a "cabeça" pela maior mancha de pele, conferindo com o rosto;
  3. pega a faixa logo acima/dos lados da cabeça e tira os pixels de pele;
  4. agrupa as cores dessa faixa em até 4 grupos e escolhe o que tem cara de
     cabelo: dentro das colunas da cabeça, perto do topo, com textura e longe
     da borda (fundo liso de estúdio é liso e costuma encostar na borda);
  5. ct = mediana da luz daquele grupo.

Uso:
  python analisar.py                        # roda tudo
  python analisar.py --limite 60 --debug 20 # teste rápido + desenhos de conferência
  python analisar.py --retomar              # continua de onde parou
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from comum import RE_PERFIS, achar_imagem, arrumar_saida, carregar_perfis, dump, falar, ler_imagem

# ------------------------------------------------------------------ detector
NOMES_CASCATAS = (
    "haarcascade_frontalface_alt2.xml",
    "haarcascade_frontalface_default.xml",
    "haarcascade_profileface.xml",
)

TAM_MIN_DETEC = 260  # abaixo disso a imagem é ampliada antes de detectar (miniatura de 150px)


class DetectorRosto:
    """Detecção de rosto com os cascata que já vêm instalados com o OpenCV."""

    def __init__(self):
        base = getattr(cv2, "data", None) and cv2.data.haarcascades
        if not base:
            raise SystemExit(
                "Este OpenCV não traz os arquivos de cascata.\n"
                "Reinstale com:  pip install opencv-python-headless==4.10.0.84"
            )
        self.cascatas = []
        for nome in NOMES_CASCATAS:
            c = cv2.CascadeClassifier(base + nome)
            if not c.empty():
                self.cascatas.append((nome, c))
        if not self.cascatas:
            raise SystemExit("Nenhum cascata de rosto encontrado em " + base)

    def detectar(self, cinza):
        """Devolve (x, y, w, h) do rosto mais provável, ou None."""
        alto, larg = cinza.shape
        escala = 1.0
        if min(alto, larg) < TAM_MIN_DETEC:
            escala = TAM_MIN_DETEC / max(1, min(alto, larg))
            # imagem muito estreita/alta não pode virar um monstro
            if max(alto, larg) * escala > 1200:
                escala = 1200.0 / max(alto, larg)
            cinza = cv2.resize(cinza, None, fx=escala, fy=escala,
                               interpolation=cv2.INTER_LINEAR)
            alto, larg = cinza.shape

        achados = []
        for tentativa in (0, 1):  # 0 = rápido (frontal), 1 = caprichado (inclui perfil)
            if tentativa == 0:
                minimo = max(20, int(min(alto, larg) * 0.15))
                parametros = dict(scaleFactor=1.10, minNeighbors=5,
                                  minSize=(minimo, minimo), flags=cv2.CASCADE_SCALE_IMAGE)
                usar = [c for c in self.cascatas if "profile" not in c[0]]
            else:
                minimo = max(16, int(min(alto, larg) * 0.09))
                parametros = dict(scaleFactor=1.15, minNeighbors=3,
                                  minSize=(minimo, minimo), flags=cv2.CASCADE_SCALE_IMAGE)
                usar = self.cascatas
            for nome, cascata in usar:
                passagens = [False, True] if "profile" in nome else [False]
                for espelhar in passagens:
                    img = cv2.flip(cinza, 1) if espelhar else cinza
                    for (x, y, w, h) in cascata.detectMultiScale(img, **parametros):
                        if espelhar:
                            x = larg - x - w
                        if w * h < minimo * minimo:
                            continue
                        if w > 0.95 * larg and h > 0.95 * alto:
                            continue
                        achados.append((w * h, x, y, w, h))
                if achados and tentativa == 0:
                    break  # frontal já achou: nem gasta tempo com o de perfil
            if achados:
                break
        if not achados:
            return None
        # maior rosto; desempate pelo mais central na horizontal
        achados.sort(key=lambda t: (t[0], -abs(t[1] + t[3] / 2 - larg / 2)))
        _, x, y, w, h = achados[-1]
        if escala != 1.0:
            inv = 1.0 / escala
            x, y, w, h = int(x * inv), int(y * inv), int(w * inv), int(h * inv)
        return int(x), int(y), int(w), int(h)


# ------------------------------------------------------------------ utilidades
def para_lab(bgr):
    """BGR uint8 -> CIELAB float32 com L em 0..100 (escala usada pelo HTML)."""
    return cv2.cvtColor(bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)


def mascara_pele(bgr):
    """Pele = quem passa nas duas regras (YCbCr e HSV) ao mesmo tempo."""
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    Y, Cr, Cb = cv2.split(ycc)
    H, S, V = cv2.split(hsv)
    regra_ycc = (Cr >= 133) & (Cr <= 175) & (Cb >= 77) & (Cb <= 130) & (Y > 45)
    regra_hsv = (((H <= 25) | (H >= 168)) & (S >= 25) & (S <= 175) & (V > 45))
    m = (regra_ycc & regra_hsv).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))


def mapa_textura(cinza, k=5):
    """Desvio padrão local — cabelo tem textura, parede de fundo não."""
    f = cinza.astype(np.float32)
    m1 = cv2.blur(f, (k, k))
    m2 = cv2.blur(f * f, (k, k))
    return np.sqrt(np.maximum(m2 - m1 * m1, 0.0))


def achar_cabeca(bgr, face):
    """Caixa da cabeça: maior mancha de pele, conferida com a caixa do rosto."""
    alto, larg = bgr.shape[:2]
    pele = mascara_pele(bgr)
    n, rotulos, stats, _ = cv2.connectedComponentsWithStats(pele, 8)
    if n > 1:
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area = int(stats[i, cv2.CC_STAT_AREA])
        x, y, w, h = (int(stats[i, j]) for j in (0, 1, 2, 3))
        cx, cy = x + w / 2, y + h / 2
        # a mancha tem que ser parecida com uma pessoa: nem minúscula, nem o fundo todo
        ok_tam = max(300, int(0.010 * alto * larg)) <= area <= int(0.55 * alto * larg)
        ok_pos = True
        if face:
            fx, fy, fw, fh = face
            ok_pos = (x - 0.30 * w < fx + fw / 2 < x + 1.30 * w and
                      y - 0.20 * h < fy + fh / 2 < y + 1.60 * h)
        if ok_tam and ok_pos and w > 0.06 * larg and h > 0.06 * alto:
            return (x, y, w, h)
    if face:
        x, y, w, h = face
        return (int(x + 0.05 * w), int(y + 0.10 * h), int(0.90 * w), int(0.80 * h))
    return None


_local = threading.local()


def detector_local():
    """Um detector por thread — o CascadeClassifier não é seguro entre threads."""
    det = getattr(_local, "det", None)
    if det is None:
        det = DetectorRosto()
        _local.det = det
    return det


# ------------------------------------------------------------------- medição
def medir(bgr, detector):
    """Devolve o dicionário de medições de uma imagem."""
    saida = {"r": False, "ct": None, "t": None, "esc30": None,
             "frac": None, "score": None, "erro": None}
    if bgr is None or bgr.size == 0:
        saida["erro"] = "imagem vazia"
        return saida
    alto, larg = bgr.shape[:2]
    if min(alto, larg) < 24:
        saida["erro"] = "imagem pequena demais"
        return saida

    cinza = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    face = detector.detectar(cv2.equalizeHist(cinza))
    saida["r"] = bool(face)

    lab = para_lab(bgr)
    # tom de pele (campo 't'): miolo do rosto
    if face:
        x, y, w, h = face
        y0, y1 = int(y + 0.35 * h), min(alto, int(y + 0.95 * h))
        x0, x1 = int(x + 0.20 * w), min(larg, int(x + 0.80 * w))
        if y1 > y0 and x1 > x0:
            saida["t"] = int(round(float(np.median(lab[y0:y1, x0:x1][:, :, 0]))))

    cabeca = achar_cabeca(bgr, face)
    if not cabeca:
        saida["erro"] = "não deu para achar a cabeça"
        return saida
    x, y, w, h = cabeca

    # faixa do cabelo: em cima da cabeça e um pouco para os lados
    b0, b1 = max(0, int(y - 0.60 * h)), min(alto, int(y + 0.12 * h))
    c0, c1 = max(0, int(x - 0.20 * w)), min(larg, int(x + 1.20 * w))
    if b1 - b0 < 4 or c1 - c0 < 8:
        saida["erro"] = "faixa de cabelo pequena"
        return saida
    banda = np.zeros((alto, larg), np.uint8)
    banda[b0:b1, c0:c1] = 255
    banda = cv2.bitwise_and(banda, cv2.bitwise_not(mascara_pele(bgr)))
    ys, xs = np.nonzero(banda)
    if len(ys) < 80:
        saida["erro"] = "poucos pixels de cabelo"
        return saida

    Ls = lab[:, :, 0][ys, xs]
    As = lab[:, :, 1][ys, xs]
    Bs = lab[:, :, 2][ys, xs]
    tex = mapa_textura(cinza)
    tex_n = tex / max(1e-6, float(np.percentile(tex, 95)))
    Ts = tex_n[ys, xs]

    dentro = ((xs >= x - 0.05 * w) & (xs <= x + 1.05 * w)).astype(np.float32)
    perto = ((ys >= y - 0.40 * h) & (ys <= y + 0.12 * h)).astype(np.float32)
    borda = ((xs < 3) | (xs > larg - 4) | (ys < 3) | (ys > alto - 4)).astype(np.float32)

    # 30% mais escuro da faixa — bom "plano B" quando o fundo engana o grupo
    ordem = np.argsort(Ls)
    n30 = max(1, int(0.30 * len(Ls)))
    saida["esc30"] = int(round(float(np.median(Ls[ordem[:n30]]))))

    Z = np.stack([Ls, As, Bs], 1).astype(np.float32)
    if len(Z) > 21000:  # amostra para não ficar lento
        rng = np.random.default_rng(7)
        idx = rng.choice(len(Z), 21000, replace=False)
        Zc, dentro, perto, borda, Ts = Z[idx], dentro[idx], perto[idx], borda[idx], Ts[idx]
    else:
        Zc = Z
    k = min(4, max(2, len(Zc) // 40))
    cv2.setRNGSeed(7)
    _, rotulos, centros = cv2.kmeans(
        Zc, k, None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 14, 0.5),
        5, cv2.KMEANS_PP_CENTERS)
    rotulos = rotulos.flatten()
    contagens = np.bincount(rotulos, minlength=k)

    melhor, melhor_s = None, -1.0
    for i in range(k):
        if contagens[i] < 0.06 * len(Zc):
            continue
        m = rotulos == i
        s = ((0.40 + 0.60 * float(dentro[m].mean())) *
             (0.30 + 0.70 * float(perto[m].mean())) *
             (0.25 + 0.75 * min(1.0, float(np.median(Ts[m])) / 0.5)) *
             (1.00 - 0.80 * float(borda[m].mean())))
        if s > melhor_s:
            melhor_s, melhor = s, i
    if melhor is None:
        melhor = int(np.argmax(contagens))

    dom = Zc[rotulos == melhor]
    saida["ct"] = int(round(float(np.median(dom[:, 0]))))
    saida["frac"] = int(round(100 * len(dom) / len(Zc)))
    saida["score"] = round(melhor_s, 3)
    return saida


def desenhar_debug(bgr, detector, medição, destino):
    """Salva a imagem com a caixa do rosto, da cabeça e a faixa medida."""
    img = bgr.copy()
    cinza = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    face = detector.detectar(cv2.equalizeHist(cinza))
    cabeca = achar_cabeca(bgr, face)
    if face:
        x, y, w, h = face
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 255), 2)
    if cabeca:
        x, y, w, h = cabeca
        cv2.rectangle(img, (x, y), (x + w, y + h), (255, 0, 255), 2)
        b0, b1 = max(0, int(y - 0.60 * h)), min(img.shape[0], int(y + 0.12 * h))
        c0, c1 = max(0, int(x - 0.20 * w)), min(img.shape[1], int(x + 1.20 * w))
        cv2.rectangle(img, (c0, b0), (c1, b1), (0, 255, 0), 2)
    texto = "ct=%s esc30=%s r=%s" % (medição.get("ct"), medição.get("esc30"), medição.get("r"))
    cv2.putText(img, texto, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, texto, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    try:
        cv2.imencode(".jpg", img)[1].tofile(str(destino))
    except Exception:
        pass


# --------------------------------------------------------------------- fluxo
def principal():
    arrumar_saida()
    aqui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Mede tom de cabelo / pele / rosto das miniaturas.")
    ap.add_argument("--pasta", default=str(aqui), help="pasta do projeto (padrão: a deste script)")
    ap.add_argument("--html", default="galeria.html", help="HTML de entrada")
    ap.add_argument("--imagens", default=None, help="pasta das imagens (padrão: <pasta>/miniaturas)")
    ap.add_argument("--saida", default="analise.json", help="JSON de saída")
    ap.add_argument("--galeria", default="galeria_medida.html", help="HTML de saída preenchido")
    ap.add_argument("--limite", type=int, default=0, help="analisa só os N primeiros (teste)")
    ap.add_argument("--threads", type=int, default=0, help="padrão: número de núcleos (máx 8)")
    ap.add_argument("--retomar", action="store_true", help="reaproveita o JSON anterior")
    ap.add_argument("--debug", type=int, default=0, help="salva N desenhos de conferência")
    args = ap.parse_args()

    pasta = Path(args.pasta)
    html_path = pasta / args.html
    pasta_img = Path(args.imagens) if args.imagens else pasta / "miniaturas"
    if not html_path.is_file():
        raise SystemExit("Não achei o HTML: %s" % html_path)
    if not pasta_img.is_dir():
        raise SystemExit("Não achei a pasta de imagens: %s\n"
                         "Use --imagens para apontar a pasta certa." % pasta_img)

    texto, perfis, _ = carregar_perfis(html_path)
    falar("HTML lido: %d perfis (%s)" % (len(perfis), html_path.name))
    falar("Imagens em: %s" % pasta_img)

    anteriores = {}
    saida_json = pasta / args.saida
    if args.retomar and saida_json.is_file():
        try:
            dados = json.loads(saida_json.read_text(encoding="utf-8"))
            for it in dados.get("itens", []):
                if it.get("ct") is not None or it.get("erro"):
                    anteriores[it["u"]] = it
            falar("Retomando: %d perfis já analisados antes." % len(anteriores))
        except Exception as e:
            falar("Não deu para retomar (%s). Vou medir tudo de novo." % e)

    if args.limite:
        perfis = perfis[: args.limite]
        falar("MODO TESTE: apenas os %d primeiros." % len(perfis))

    DetectorRosto()  # falha aqui (e não no meio) se faltar o cascata
    threads = args.threads or min(8, (os.cpu_count() or 4))
    lock = threading.Lock()
    estado = {"n": 0, "sem_arquivo": 0, "sem_rosto": 0, "erro": 0}
    debug_dir = pasta / "debug"
    if args.debug:
        debug_dir.mkdir(exist_ok=True)

    def processar(p):
        with lock:
            estado["n"] += 1
            n = estado["n"]
        if p["u"] in anteriores and not args.debug:
            return anteriores[p["u"]]
        arquivo = achar_imagem(pasta_img, p["u"], p.get("img"))
        item = {"u": p["u"], "img": p.get("img"), "g": p.get("g"), "n": p.get("n")}
        if not arquivo:
            with lock:
                estado["sem_arquivo"] += 1
            item.update({"r": False, "ct": None, "t": None, "esc30": None,
                         "frac": None, "score": None, "erro": "arquivo não encontrado"})
            return item
        bgr = ler_imagem(arquivo)
        try:
            med = medir(bgr, detector_local())
        except Exception as e:  # uma imagem ruim nunca derruba a rodada
            med = {"r": False, "ct": None, "t": None, "esc30": None,
                   "frac": None, "score": None, "erro": "falhou: %s" % type(e).__name__}
        item.update(med)
        item["arquivo"] = arquivo.name
        if args.debug and bgr is not None and n <= args.debug:
            try:
                desenhar_debug(bgr, detector_local(), med, debug_dir / ("%04d_%s.jpg" % (n, p["u"])))
            except Exception:
                pass
        with lock:
            if med.get("erro"):
                estado["erro"] += 1
            elif not med.get("r"):
                estado["sem_rosto"] += 1
        if n % 250 == 0:
            falar("  ... %d/%d" % (n, len(perfis)))
        return item

    falar("\nMedindo (%d thread(s))... pode levar alguns minutos." % threads)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        itens = list(pool.map(processar, perfis))
    falar("Medição pronta em %.1f s" % (time.time() - t0))
    falar("Sem arquivo: %d · sem rosto: %d · sem medição: %d"
          % (estado["sem_arquivo"], estado["sem_rosto"], estado["erro"]))

    medidos = [i for i in itens if i.get("ct") is not None]
    falar("\n=== DISTRIBUIÇÃO DO TOM DE CABELO (%d de %d) ===" % (len(medidos), len(itens)))
    faixas = [(0, 25, "preto"), (25, 35, "castanho muito escuro"), (35, 50, "castanho escuro"),
              (50, 65, "castanho"), (65, 80, "castanho claro"), (80, 101, "loiro / claro")]
    for a, b, nome in faixas:
        q = sum(1 for i in medidos if a <= i["ct"] < b)
        falar("  %-24s %5d  %s" % (nome, q, "#" * int(56 * q / max(1, len(medidos)))))

    dados = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "pasta": str(pasta),
        "pasta_imagens": str(pasta_img),
        "html_origem": str(html_path),
        "total": len(itens),
        "medidos": len(medidos),
        "itens": itens,
    }
    saida_json.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    falar("\nJSON salvo: %s" % saida_json)

    por_u = {i["u"]: i for i in itens}
    for p in perfis:
        i = por_u.get(p["u"], {})
        p["ct"] = i.get("ct")
        p["t"] = i.get("t")
        p["r"] = bool(i.get("r"))
    destino = pasta / args.galeria
    with open(destino, "w", encoding="utf-8", newline="") as f:
        f.write(RE_PERFIS.sub(lambda m: m.group(1) + dump(perfis) + m.group(3), texto, count=1))
    falar("HTML preenchido: %s" % destino)
    falar("\nAgora rode:   python filtrar.py")


if __name__ == "__main__":
    principal()
