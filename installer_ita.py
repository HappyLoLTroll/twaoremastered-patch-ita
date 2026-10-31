#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
The Wolf Among Us Remastered - Installer italiano
installer by HappyLoLTroll

Due modalita':
  A) solo testi e sottotitoli  -> estrae i testi italiani dagli archivi del
     gioco e li scrive come file sciolti in Archives\.
  B) testi + testo dei capitoli -> come A, e in piu' inserisce
     ui_episode/ui_credits (dalla patch italiana vecchia) dentro gli archivi
     degli episodi.

Backup di tutto cio' che viene modificato in <gioco>\old_patch_ita\
"""

import hashlib
import json
import os
import shutil
import struct
import sys
import threading
import time
import traceback
import zlib

APP_NAME = "The Wolf Among Us Remastered - Italiano"
APP_AUTHOR = "installer by HappyLoLTroll"
VERSION = "1.2"
PATCH_URL = "https://1drv.ms/u/s!ApMUGr0cuN39gcU1t4iqnsfx5KTodQ?e=y9QOEr"
BKP_DIR_NAME = "old_patch_ita"

ITAL = "_italian.landb"
ENGL = "_english.landb"
DUPLICATI = ("ui_episode_english.landb", "ui_credits_english.landb")
ARCH_HINTS = ("_ar_data.ttarch2", "Project_ar_all.ttarch2")
EPISODI = ["Fables_pc_Fables10%d_ar_data.ttarch2" % i for i in range(1, 6)]
EPISODI_PATCH = ["Fables_pc_Fables10%d_data.ttarch2" % i for i in range(1, 6)]
CHUNK = 0x10000
INDEX_TAGS = (b"2ATT", b"3ATT", b"4ATT", b"5ATT")
MAGIC = (b"NCTT", b"ZCTT", b"eCTT", b"ECTT", b"zCTT")
PLACEHOLDERS = ("hello", "hello.", "hello!", "test")
HASH_UNICODE = bytes.fromhex("53DCA533DBD6DC7E")


def md5(b):
    return hashlib.md5(b).hexdigest()


# --------------------------------------------------------------- archivio
class Archive:
    def __init__(self, path):
        self.path = path
        self.stream = bytearray()
        self.loaded = 0
        self.f = open(path, "rb")
        magic = self.f.read(4)
        if magic not in MAGIC:
            raise ValueError("non e' un archivio ttarch2 (%r)" % magic)
        self.magic = magic
        self.compressed = magic != b"NCTT"
        self.nblocks = 0
        self.starts = []
        if self.compressed:
            if magic in (b"eCTT", b"ECTT", b"zCTT"):
                self.f.read(4)
            self.chunk, self.nblocks = struct.unpack("<Ii", self.f.read(8))
            self.starts = [struct.unpack("<Q", self.f.read(8))[0]
                           for _ in range(self.nblocks + 1)]
            self.base = 0
        else:
            self.base = 12
            self.f.seek(0)
            self.stream = bytearray(self.f.read())

    def _decomp(self, raw):
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:
            return zlib.decompress(raw)

    def ensure(self, size):
        if not self.compressed:
            return
        while len(self.stream) < size and self.loaded < self.nblocks:
            i = self.loaded
            self.f.seek(self.starts[i])
            self.stream += self._decomp(self.f.read(self.starts[i + 1] - self.starts[i]))
            self.loaded += 1

    def ensure_all(self):
        self.ensure(1 << 62)

    def read(self, off, size):
        self.ensure(off + size)
        return bytes(self.stream[off:off + size])

    def parse(self):
        self.ensure(64)
        tag = bytes(self.stream[self.base:self.base + 4])
        if tag not in INDEX_TAGS:
            raise ValueError("indice non riconosciuto %r" % tag)
        extra = 4 if tag == b"3ATT" else 0
        hdr = self.base + 4 + extra
        name_size, count = struct.unpack("<II", self.read(hdr, 8))
        if not (0 < count < 200000):
            raise ValueError("conteggio file non valido: %d" % count)
        rec = hdr + 8
        raw = self.read(rec, 28 * count)
        self.records = []
        for i in range(count):
            crc, off, size, unk, blk, noff = struct.unpack("<QQiiHH", raw[28 * i:28 * i + 28])
            self.records.append((crc, off, size, unk, blk, noff))
        names_base = rec + 28 * count
        last = max(b * CHUNK + n for (_c, _o, _s, _u, b, n) in self.records)
        self.ensure(names_base + last + 512)
        self.files = []
        for i, (_c, off, size, _u, blk, noff) in enumerate(self.records):
            pos = names_base + blk * CHUNK + noff
            end = self.stream.find(b"\0", pos, pos + 512)
            if end < 0:
                raise ValueError("nome file illeggibile nell'archivio")
            self.files.append((bytes(self.stream[pos:end]).decode("ascii", "replace"), off, size))
        self.name_size = name_size
        self.tag = tag
        self.data_start = names_base + name_size
        return self.files

    def read_file(self, name):
        for n, off, size in self.files:
            if n == name:
                return self.read(self.data_start + off, size)
        raise KeyError(name)

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


def write_archive_stream(stream, path, compressed, base_tag, extra):
    if compressed:
        n = max(1, (len(stream) + CHUNK - 1) // CHUNK)
        blocchi = []
        for i in range(n):
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            blocchi.append(c.compress(stream[i * CHUNK:(i + 1) * CHUNK]) + c.flush())
        testa = 12 + 8 * (n + 1)
        starts = [testa]
        for b in blocchi:
            starts.append(starts[-1] + len(b))
        out = bytearray(b"ZCTT") + struct.pack("<Ii", CHUNK, n)
        for s in starts:
            out += struct.pack("<Q", s)
        for b in blocchi:
            out += b
    else:
        out = bytearray(b"NCTT") + struct.pack("<Q", len(stream)) + stream
    with open(path, "wb") as fh:
        fh.write(out)
    return len(out)


def rebuild_archive(arc, replacements, out_path):
    """Riscrive l'archivio con i file sostituiti, stesso formato."""
    arc.ensure_all()
    stream = bytes(arc.stream)
    tag = stream[arc.base:arc.base + 4]
    extra_tag = b""
    if tag == b"3ATT":
        extra_tag = stream[arc.base + 4:arc.base + 8]
    hdr = arc.base + 4 + len(extra_tag)
    name_size, count = struct.unpack("<II", stream[hdr:hdr + 8])
    rec = hdr + 8
    names_start = rec + 28 * count
    nomi = stream[names_start:names_start + name_size]
    header = bytearray(tag) + extra_tag + struct.pack("<II", name_size, count)
    dati = bytearray()
    for i, (nome, _off, _size) in enumerate(arc.files):
        crc, _o, _s, unk, blk, noff = struct.unpack("<QQiiHH", stream[rec + 28 * i:rec + 28 * i + 28])
        payload = replacements.get(nome)
        if payload is None:
            payload = stream[arc.data_start + _o:arc.data_start + _o + _s]
        header += struct.pack("<QQiiHH", crc, len(dati), len(payload), unk, blk, noff)
        dati += payload
    return write_archive_stream(bytes(header) + nomi + bytes(dati), out_path,
                                arc.magic == b"ZCTT", tag, extra_tag)


# ------------------------------------------------------------------ landb
class Entry:
    __slots__ = ("wav", "crc", "anm", "zero1", "block_anm", "anm_name",
                 "block_wav", "wav_name", "block_unk", "unk", "zero2",
                 "block_langres", "block_actor", "actor", "block_speech",
                 "speech", "block_size", "some_value", "block_uni", "data_uni",
                 "flags", "raw_actor", "raw_speech")


def _dec(b):
    if not b:
        return ""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def _enc(s):
    return s.encode("utf-8") if s else b""


class Landb:
    def __init__(self):
        self.magic = b"6VSM"
        self.last_size = self.third = 0
        self.blocks = []
        self.b1 = self.s1 = self.b2 = self.s2 = 0
        self.entries = []
        self.common_len = 0
        self.common = b""
        self.last4 = (0, 0, 0, 0)
        self.tail = b""
        self.unicode = False

    @classmethod
    def read(cls, data):
        lb = cls()
        lb.magic = data[:4]
        if lb.magic not in (b"5VSM", b"6VSM"):
            raise ValueError("landb non supportato (%r)" % lb.magic)
        lb.last_size, lb.third = struct.unpack("<II", data[8:16])
        nblk = struct.unpack("<I", data[16:20])[0]
        pos = 20
        for _ in range(nblk):
            h = data[pos:pos + 8]
            lb.blocks.append((h, struct.unpack("<I", data[pos + 8:pos + 12])[0]))
            if h == HASH_UNICODE:
                lb.unicode = True
            pos += 12
        lb.b1, lb.s1, lb.b2, lb.s2 = struct.unpack("<IIII", data[pos:pos + 16])
        pos += 20                                    # + block_len (ricalcolato)
        count = struct.unpack("<I", data[pos:pos + 4])[0]
        pos += 4
        for _ in range(count):
            e = Entry()
            e.wav, e.crc, e.anm, e.zero1 = struct.unpack("<IQIi", data[pos:pos + 20])
            pos += 20
            e.block_anm = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            e.anm_name = data[pos:pos + 8]
            pos += 8
            e.block_wav = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            e.wav_name = data[pos:pos + 8]
            pos += 8
            e.block_unk = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            n = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            e.unk = data[pos:pos + n]
            pos += n
            e.zero2 = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            e.block_langres = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            e.block_actor = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            n = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            e.raw_actor = data[pos:pos + n]
            e.actor = _dec(e.raw_actor)
            pos += n
            e.block_speech = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            n = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            e.raw_speech = data[pos:pos + n]
            e.speech = _dec(e.raw_speech)
            pos += n
            e.block_size, e.some_value = struct.unpack("<Ii", data[pos:pos + 8])
            pos += 8
            e.block_uni = 0
            e.data_uni = b""
            if lb.unicode:
                e.block_uni = struct.unpack("<i", data[pos:pos + 4])[0]
                pos += 4
                e.data_uni = data[pos:pos + e.block_uni - 4]
                pos += e.block_uni - 4
            e.flags = struct.unpack("<i", data[pos:pos + 4])[0]
            pos += 4
            lb.entries.append(e)
        lb.common_len = struct.unpack("<I", data[pos:pos + 4])[0]
        pos += 4
        lb.common = data[pos:pos + lb.common_len - 4]
        pos += lb.common_len - 4
        lb.last4 = struct.unpack("<IIII", data[pos:pos + 16])
        pos += 16
        lb.tail = data[pos:pos + lb.last_size]
        if pos + len(lb.tail) != len(data):
            raise ValueError("landb incoerente")
        return lb

    def _entry_bytes(self, e):
        actor = e.raw_actor if _dec(e.raw_actor) == e.actor else _enc(e.actor)
        speech = e.raw_speech if _dec(e.raw_speech) == e.speech else _enc(e.speech)
        da = len(actor) - len(e.raw_actor)
        ds = len(speech) - len(e.raw_speech)
        out = bytearray()
        out += struct.pack("<IQIi", e.wav, e.crc, e.anm, e.zero1)
        out += struct.pack("<i", e.block_anm) + e.anm_name
        out += struct.pack("<i", e.block_wav) + e.wav_name
        out += struct.pack("<i", e.block_unk)
        out += struct.pack("<i", len(e.unk)) + e.unk
        out += struct.pack("<i", e.zero2)
        out += struct.pack("<i", e.block_langres + da + ds)
        out += struct.pack("<i", e.block_actor + da)
        out += struct.pack("<i", len(actor)) + actor
        out += struct.pack("<i", e.block_speech + ds)
        out += struct.pack("<i", len(speech)) + speech
        out += struct.pack("<Ii", e.block_size, e.some_value)
        if self.unicode:
            out += struct.pack("<i", e.block_uni) + e.data_uni
        out += struct.pack("<i", e.flags)
        return bytes(out)

    def write(self):
        body = b"".join(self._entry_bytes(e) for e in self.entries)
        size = 24 + len(body) + self.common_len + 16
        out = bytearray()
        out += self.magic
        out += struct.pack("<III", size, self.last_size, self.third)
        out += struct.pack("<I", len(self.blocks))
        for h, v in self.blocks:
            out += h + struct.pack("<I", v)
        out += struct.pack("<IIII", self.b1, self.s1, self.b2, self.s2)
        out += struct.pack("<II", size - 32 - self.common_len, len(self.entries))
        out += body
        out += struct.pack("<I", self.common_len) + self.common
        out += struct.pack("<IIII", *self.last4)
        out += self.tail
        return bytes(out)


def merge_texts(base_bytes, fonti):
    """fonti: lista (nome, bytes landb). La prima che riempie una voce vince."""
    lb = Landb.read(base_bytes)
    presi = set()
    stat = []
    for nome, dati in fonti:
        mappa = {e.crc: e.speech for e in Landb.read(dati).entries}
        n = 0
        for e in lb.entries:
            if e.crc in presi:
                continue
            testo = mappa.get(e.crc)
            if testo is None:
                continue
            t = testo.strip()
            if not t or t.lower() in PLACEHOLDERS:
                continue
            if testo != e.speech:
                e.speech = testo
                n += 1
            presi.add(e.crc)
        stat.append((nome, n))
    return lb.write(), stat, sum(1 for e in lb.entries if e.crc not in presi)



def merge_maps(base_bytes, fonti):
    """fonti: [(nome, {crc: testo})] in ordine di priorita'."""
    lb = Landb.read(base_bytes)
    presi = set()
    stat = []
    for nome, mappa in fonti:
        n = 0
        for e in lb.entries:
            if e.crc in presi:
                continue
            t = (mappa.get(e.crc) or "").strip()
            if not t or t.lower() in PLACEHOLDERS:
                continue
            if t != e.speech:
                e.speech = t
                n += 1
            presi.add(e.crc)
        stat.append((nome, n))
    return lb.write(), stat, sum(1 for e in lb.entries if e.crc not in presi)


def testi_dalla_patch(pack):
    """nome landb -> {crc: testo italiano} leggendo la patch vecchia."""
    out = {}
    for nome in sorted(os.listdir(pack)):
        if not nome.lower().endswith(".ttarch2"):
            continue
        try:
            a = Archive(os.path.join(pack, nome))
            files = {f[0] for f in a.parse()}
        except Exception:
            continue
        try:
            for f in files:
                if not f.endswith("_english.landb"):
                    continue
                try:
                    m = {e.crc: e.speech for e in Landb.read(a.read_file(f)).entries}
                except Exception:
                    continue
                if f not in out or len(m) > len(out[f]):
                    out[f] = m
        finally:
            a.close()
    return out


def da_patch_extra(nome):
    return (nome.startswith("previouslyon_") or nome.startswith("nexttimeon_")
            or nome in ("ui_text_english.landb", "ui_menu_english.landb"))


# ------------------------------------------------------------------- piano
def valid_game(path):
    if not path or not os.path.isdir(path):
        return False, "cartella non valida"
    A = os.path.join(path, "Archives")
    if not os.path.isdir(A):
        return False, "manca la cartella Archives"
    n = len([f for f in os.listdir(A) if f.lower().endswith(".ttarch2")])
    if n < 5:
        return False, "Archives non contiene gli archivi del gioco"
    return True, "%d archivi trovati" % n


def trova_patch(path):
    """Ritorna la cartella che contiene Fables_pc_Fables10N_data.ttarch2."""
    if not path or not os.path.isdir(path):
        return None
    for cand in (path, os.path.join(path, "Pack")):
        if os.path.isdir(cand):
            if any(os.path.exists(os.path.join(cand, n)) for n in EPISODI_PATCH):
                return cand
    return None


def coppie_archivi(game):
    A = os.path.join(game, "Archives")
    coppie = {}
    occ = {}
    for nome in sorted(os.listdir(A)):
        low = nome.lower()
        if not low.endswith(".ttarch2"):
            continue
        if not any(h.lower() in low for h in ARCH_HINTS) or "voice" in low:
            continue
        arc = Archive(os.path.join(A, nome))
        try:
            files = {f[0]: f for f in arc.parse()}
            for n in files:
                if not n.endswith(ITAL):
                    continue
                target = n[:-len(ITAL)] + ENGL
                if target not in files:
                    continue
                coppie[target] = (arc.read_file(target), arc.read_file(n))
                occ.setdefault(target, []).append(nome)
        finally:
            arc.close()
    duplicati = {k: v for k, v in occ.items() if len(v) > 1}
    return coppie, duplicati


def backup_file(src, bkp_root, rel):
    """Copia src in <bkp_root>/<rel>; ritorna (fatto, motivo)."""
    dest = os.path.join(bkp_root, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        shutil.copy2(src, dest)
        return True, "backup"
    if md5(open(src, "rb").read()) == md5(open(dest, "rb").read()):
        return False, "gia' in backup (identico)"
    # backup diverso: il gioco e' cambiato, conservo il vecchio
    vecchi = os.path.join(bkp_root, "_precedenti")
    os.makedirs(vecchi, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = os.path.basename(rel)
    shutil.move(dest, os.path.join(vecchi, base + "." + ts + ".bak"))
    shutil.copy2(src, dest)
    return True, "backup aggiornato"


def install(game, mode, patch_dir, log, progress=None):
    """mode: 'testi' oppure 'capitoli'."""
    ok, msg = valid_game(game)
    if not ok:
        raise RuntimeError(msg)
    A = os.path.join(game, "Archives")
    bkp = os.path.join(game, BKP_DIR_NAME)
    os.makedirs(bkp, exist_ok=True)
    manifest_path = os.path.join(bkp, "manifest.json")
    manifest = {"versione": VERSION, "modalita": mode, "data": time.strftime("%Y-%m-%d %H:%M:%S"),
                "file_sciolti": [], "archivi": []}
    if os.path.exists(manifest_path):
        try:
            vecchio = json.load(open(manifest_path, encoding="utf-8"))
            manifest["file_sciolti"] = vecchio.get("file_sciolti", [])
            manifest["archivi"] = vecchio.get("archivi", [])
        except Exception:
            pass

    log("Gioco: %s" % game)
    log("Backup: %s" % bkp)
    log("")
    coppie, duplicati = coppie_archivi(game)
    if not coppie:
        raise RuntimeError("nessun testo italiano trovato negli archivi del gioco")
    log("Testi italiani disponibili nel gioco: %d file" % len(coppie))

    skip = set(duplicati)
    da_scrivere = {k: v for k, v in coppie.items() if k not in skip}
    if duplicati:
        log("Esclusi dai file sciolti (servono i capitoli): %s" % ", ".join(sorted(skip)))
    log("")

    # ---- fase 1: file sciolti (sempre)
    log("[1/2] Installazione menu, dialoghi e sottotitoli...")
    scritti = 0
    for i, (target, (base, trans)) in enumerate(sorted(da_scrivere.items()), 1):
        merged, stat, restano = merge_texts(base, [("remaster", trans)])
        dest = os.path.join(A, target)
        if os.path.exists(dest):
            b, why = backup_file(dest, bkp, os.path.join("Archives", target))
            if b:
                log("      backup %s (%s)" % (target, why))
        old = open(dest, "rb").read() if os.path.exists(dest) else None
        if old is None or md5(old) != md5(merged):
            with open(dest, "wb") as fh:
                fh.write(merged)
            scritti += 1
        if target not in manifest["file_sciolti"]:
            manifest["file_sciolti"].append(target)
        if progress:
            progress(i, len(da_scrivere))
    log("      %d file aggiornati su %d" % (scritti, len(da_scrivere)))
    log("")

    # ---- fase 2: capitoli (opzionale)
    if mode == "capitoli":
        if not patch_dir:
            raise RuntimeError("patch vecchia non indicata")
        pack = trova_patch(patch_dir)
        if not pack:
            raise RuntimeError("nella cartella indicata non trovo la patch vecchia "
                               "(servono i file Fables_pc_Fables10N_data.ttarch2)")
        log("[2/2] Installazione testo dei capitoli (patch vecchia)...")
        arch_bkp = os.path.join(bkp, "Archives")
        for ep, ar in enumerate(EPISODI, 1):
            cur = os.path.join(A, ar)
            if not os.path.exists(cur):
                log("      %s assente, salto" % ar)
                continue
            bak_rel = os.path.join("Archives", ar)
            bak_abs = os.path.join(bkp, bak_rel)
            os.makedirs(arch_bkp, exist_ok=True)
            if not os.path.exists(bak_abs):
                shutil.copy2(cur, bak_abs)
                log("      backup %s" % ar)
            origine = bak_abs          # base pulita, anche se gia' patchato
            patch_ep = os.path.join(pack, EPISODI_PATCH[ep - 1])
            if not os.path.exists(patch_ep):
                log("      patch episodio %d non trovata, salto" % ep)
                continue
            a = Archive(origine)
            p = Archive(patch_ep)
            try:
                a.parse()
                p.parse()
                repl = {}
                dettagli = []
                for nome in DUPLICATI:
                    if nome not in [f[0] for f in a.files]:
                        continue
                    base = a.read_file(nome)
                    fonti = []
                    try:
                        if nome in [f[0] for f in p.files]:
                            fonti.append(("patch vecchia", p.read_file(nome)))
                    except Exception:
                        pass
                    it = nome[:-len(ENGL)] + ITAL
                    if it in [f[0] for f in a.files]:
                        fonti.append(("remaster", a.read_file(it)))
                    if not fonti:
                        continue
                    merged, stat, restano = merge_texts(base, fonti)
                    repl[nome] = merged
                    dettagli.append("%s (%s)" % (nome, ", ".join("%s %d" % s for s in stat)))
                if not repl:
                    continue
                dimensione = rebuild_archive(a, repl, cur)
            finally:
                a.close()
                p.close()
            log("      episodio %d: %s | %.1f MB" %
                (ep, "; ".join(dettagli), dimensione / 1048576.0))
            if ar not in manifest["archivi"]:
                manifest["archivi"].append(ar)

        # ---- fase 2b: riassunti (previouslyon/nexttimeon) e UI dalla patch
        log("[2b] Riassunti e interfaccia dalla patch vecchia...")
        pmaps = testi_dalla_patch(pack)
        scritti2 = 0
        for target, (base, trans) in sorted(coppie.items()):
            if not da_patch_extra(target):
                continue
            rem = {e.crc: e.speech for e in Landb.read(trans).entries}
            merged, stat, restano = merge_maps(base, [("patch vecchia", pmaps.get(target, {})),
                                                      ("remaster", rem)])
            dest = os.path.join(A, target)
            if os.path.exists(dest):
                b, why = backup_file(dest, bkp, os.path.join("Archives", target))
                if b:
                    log("      backup %s (%s)" % (target, why))
            old = open(dest, "rb").read() if os.path.exists(dest) else None
            if old is None or md5(old) != md5(merged):
                with open(dest, "wb") as fh:
                    fh.write(merged)
                scritti2 += 1
            if target not in manifest["file_sciolti"]:
                manifest["file_sciolti"].append(target)
            log("      %-34s ITA %3d | EN %2d | %s" %
                (target, len(Landb.read(merged).entries) - restano, restano,
                 ", ".join("%s %d" % x for x in stat)))
        log("      %d file aggiornati" % scritti2)
        log("")

    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    log("")
    log("Fatto. Installazione completata (%s)." %
        ("testi + capitoli" if mode == "capitoli" else "solo testi e sottotitoli"))
    return manifest


def uninstall(game, log, progress=None):
    A = os.path.join(game, "Archives")
    bkp = os.path.join(game, BKP_DIR_NAME)
    manifest_path = os.path.join(bkp, "manifest.json")
    if not os.path.exists(manifest_path):
        raise RuntimeError("nessun backup trovato in %s" % bkp)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    log("Ripristino da: %s" % bkp)
    ripristinati = 0
    for ar in manifest.get("archivi", []):
        bak = os.path.join(bkp, "Archives", ar)
        cur = os.path.join(A, ar)
        if os.path.exists(bak):
            shutil.copy2(bak, cur)
            ripristinati += 1
            log("   ripristinato %s" % ar)
    rimossi = 0
    for nome in manifest.get("file_sciolti", []):
        p = os.path.join(A, nome)
        if os.path.exists(p):
            os.remove(p)
            rimossi += 1
    log("   %d archivi ripristinati, %d file sciolti rimossi" % (ripristinati, rimossi))
    log("")
    log("Gioco riportato in inglese.")
    return ripristinati, rimossi


def run_gui():
    import ctypes
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox, ttk
    import webbrowser

    # DPI awareness: senza questo Windows ingrandisce l'immagine (sfocatura a 150%)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    root = tk.Tk(className="IWAU-ITA-Installer")
    root.withdraw()
    root.title("%s - %s" % (APP_NAME, APP_AUTHOR))
    root.configure(bg="#f3f4f6")

    try:
        dpi = max(96.0, root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        dpi = 96.0
    S = dpi / 96.0

    def px(v):
        return max(1, int(round(v * S)))

    stile = ttk.Style()
    try:
        stile.theme_use("vista")
    except Exception:
        pass
    base = tkfont.nametofont("TkDefaultFont").actual("size") or 9
    base = abs(int(base))
    stile.configure("Titolo.TLabel", font=("Segoe UI", base + 8, "bold"))
    stile.configure("Sotto.TLabel", font=("Segoe UI", base - 1))
    stile.configure("Nota.TLabel", font=("Segoe UI", base - 2))
    stile.configure("Ok.TLabel", font=("Segoe UI", base - 1), foreground="#0a7a3d")
    stile.configure("Ko.TLabel", font=("Segoe UI", base - 1), foreground="#b00020")
    stile.configure("TLabelframe.Label", font=("Segoe UI", base))
    stile.configure("Azione.TButton", font=("Segoe UI", base), padding=(px(12), px(6)))
    stile.configure("TButton", font=("Segoe UI", base), padding=(px(8), px(4)))
    stile.configure("TRadiobutton", font=("Segoe UI", base), padding=(0, px(2)))

    # griglia principale: le righe si adattano, il log si espande
    root.columnconfigure(0, weight=1)
    for r, w in ((0, 0), (1, 0), (2, 0), (3, 0), (4, 1), (5, 0)):
        root.rowconfigure(r, weight=w)
    m = px(14)

    caps = ttk.Frame(root, padding=(m, m, m, px(4)))
    caps.grid(row=0, column=0, sticky="ew")
    caps.columnconfigure(0, weight=1)
    ttk.Label(caps, text="THE WOLF AMONG US REMASTERED - ITALIANO",
              style="Titolo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(caps, text="%s   |   versione %s" % (APP_AUTHOR, VERSION),
              style="Sotto.TLabel").grid(row=1, column=0, sticky="w", pady=(px(2), 0))

    modalita = tk.StringVar(value="testi")
    gioco = tk.StringVar()
    patch = tk.StringVar()

    frm1 = ttk.LabelFrame(root, text=" 1. Cosa vuoi installare ", padding=px(12))
    frm1.grid(row=1, column=0, sticky="ew", padx=m, pady=(0, px(6)))
    frm1.columnconfigure(0, weight=1)
    ttk.Radiobutton(frm1, text="Solo testi e sottotitoli (menu, dialoghi, sottotitoli)",
                    value="testi", variable=modalita).grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(frm1, text="Testi + testo dei capitoli (schede narrative, crediti)",
                    value="capitoli", variable=modalita).grid(row=1, column=0, sticky="w", pady=(px(4), 0))

    frm_patch_info = ttk.Frame(frm1)
    frm_patch_info.columnconfigure(0, weight=1)
    ttk.Label(frm_patch_info,
              text="Per il testo dei capitoli serve la patch italiana della versione vecchia.\n"
                   "Scaricala da: " + PATCH_URL,
              style="Nota.TLabel", foreground="#333",
              wraplength=px(700), justify="left").grid(row=0, column=0, sticky="w", pady=(px(8), px(4)))
    riga = ttk.Frame(frm_patch_info)
    riga.grid(row=1, column=0, sticky="w")

    def apri_link():
        webbrowser.open(PATCH_URL)

    def copia_link():
        root.clipboard_clear()
        root.clipboard_append(PATCH_URL)
        messagebox.showinfo("Link copiato", "Link della patch copiato negli appunti.")

    ttk.Button(riga, text="Apri pagina download", command=apri_link).pack(side="left")
    ttk.Button(riga, text="Copia link", command=copia_link).pack(side="left", padx=px(6))

    frm2 = ttk.LabelFrame(root, text=" 2. Cartella del gioco ", padding=px(12))
    frm2.grid(row=2, column=0, sticky="ew", padx=m, pady=px(6))
    frm2.columnconfigure(0, weight=1)
    r2 = ttk.Frame(frm2)
    r2.grid(row=0, column=0, sticky="ew")
    r2.columnconfigure(0, weight=1)
    ttk.Entry(r2, textvariable=gioco, font=("Segoe UI", base)).grid(row=0, column=0, sticky="ew", ipady=px(3))
    lbl_gioco = ttk.Label(frm2, text="", style="Nota.TLabel")
    lbl_gioco.grid(row=1, column=0, sticky="w", pady=(px(4), 0))

    frm3 = ttk.LabelFrame(root, text=" 3. Cartella della patch vecchia (solo per i capitoli) ",
                          padding=px(12))
    frm3.grid(row=3, column=0, sticky="ew", padx=m, pady=px(6))
    frm3.columnconfigure(0, weight=1)
    r3 = ttk.Frame(frm3)
    r3.grid(row=0, column=0, sticky="ew")
    r3.columnconfigure(0, weight=1)
    ent_patch = ttk.Entry(r3, textvariable=patch, font=("Segoe UI", base), state="disabled")
    ent_patch.grid(row=0, column=0, sticky="ew", ipady=px(3))
    btn_patch = ttk.Button(r3, text="Sfoglia...", state="disabled")
    btn_patch.grid(row=0, column=1, padx=(px(8), 0))
    lbl_patch = ttk.Label(frm3, text="Solo se installi anche il testo dei capitoli.",
                          style="Nota.TLabel")
    lbl_patch.grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(4), 0))

    def scegli_gioco():
        p = filedialog.askdirectory(title="Seleziona la cartella del gioco (quella con l'exe)")
        if p:
            gioco.set(os.path.normpath(p))
            ok, msg = valid_game(p)
            lbl_gioco.configure(text=("OK: " + msg) if ok else ("ERRORE: " + msg),
                                style="Ok.TLabel" if ok else "Ko.TLabel")

    def scegli_patch():
        p = filedialog.askdirectory(title="Seleziona la cartella della patch vecchia")
        if p:
            patch.set(os.path.normpath(p))
            trovata = trova_patch(p)
            lbl_patch.configure(text=("OK: patch trovata" if trovata else "ERRORE: patch non trovata qui"),
                                style="Ok.TLabel" if trovata else "Ko.TLabel")

    ttk.Button(r2, text="Sfoglia...", command=scegli_gioco).grid(row=0, column=1, padx=(px(8), 0))
    btn_patch.configure(command=scegli_patch)

    def aggiorna_modalita(*_):
        attivo = modalita.get() == "capitoli"
        ent_patch.configure(state="normal" if attivo else "disabled")
        btn_patch.configure(state="normal" if attivo else "disabled")
        if attivo:
            frm_patch_info.grid(row=2, column=0, sticky="ew", pady=(px(8), 0))
        else:
            frm_patch_info.grid_remove()

    modalita.trace_add("write", aggiorna_modalita)
    aggiorna_modalita()

    frm4 = ttk.Frame(root, padding=(m, px(4), m, px(4)))
    frm4.grid(row=4, column=0, sticky="nsew")
    frm4.columnconfigure(0, weight=1)
    frm4.rowconfigure(0, weight=1)
    log_box = tk.Text(frm4, height=10, wrap="word", font=("Consolas", base),
                      background="#0f1418", foreground="#dbe4ea",
                      insertbackground="#fff", relief="flat",
                      padx=px(10), pady=px(8), borderwidth=1,
                      highlightthickness=1, highlightbackground="#2a3238")
    log_box.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(frm4, orient="vertical", command=log_box.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    log_box.configure(yscrollcommand=scroll.set)
    log_box.configure(state="disabled")
    barra = ttk.Progressbar(frm4, mode="determinate", maximum=100)
    barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(6), 0))

    azioni = ttk.Frame(root, padding=(m, px(6), m, m))
    azioni.grid(row=5, column=0, sticky="ew")
    azioni.columnconfigure(3, weight=1)

    def log(msg):
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        root.update_idletasks()

    def progress(i, n):
        barra["value"] = 100.0 * i / max(1, n)
        root.update_idletasks()

    def esegui(modo):
        g = gioco.get().strip()
        ok, msg = valid_game(g)
        if not ok:
            messagebox.showerror("Cartella del gioco", msg)
            return
        pdir = patch.get().strip()
        if modo == "installa" and modalita.get() == "capitoli" and not trova_patch(pdir):
            messagebox.showerror("Patch vecchia",
                                 "Indica la cartella della patch vecchia "
                                 "(contiene Pack\\Fables_pc_Fables10N_data.ttarch2).\n"
                                 "Scaricala da: " + PATCH_URL)
            return
        if modo == "installa":
            testo = "testi + capitoli" if modalita.get() == "capitoli" else "solo testi e sottotitoli"
            if not messagebox.askyesno("Conferma",
                                       "Installare in:\n%s\n\nModalita': %s\n\n"
                                       "I file modificati vengono salvati in '%s'."
                                       % (g, testo, BKP_DIR_NAME)):
                return
        else:
            if not messagebox.askyesno("Ripristino", "Riportare il gioco in inglese?"):
                return

        for b in (btn_installa, btn_ripristina):
            b.configure(state="disabled")
        barra["value"] = 0
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")

        def lavoro():
            try:
                if modo == "installa":
                    install(g, "capitoli" if modalita.get() == "capitoli" else "testi",
                            pdir, log, progress)
                    msg2 = "Installazione completata.\nAvvia il gioco: sara' in italiano."
                else:
                    uninstall(g, log, progress)
                    msg2 = "Ripristino completato: gioco in inglese."
                root.after(0, lambda: messagebox.showinfo("Fatto", msg2))
            except Exception as exc:
                testo = "%s" % exc
                dettaglio = traceback.format_exc()
                root.after(0, lambda: messagebox.showerror("Errore", testo))
                log("ERRORE: " + testo)
                log(dettaglio)
            finally:
                def riabilita():
                    for b in (btn_installa, btn_ripristina):
                        b.configure(state="normal")
                    barra.configure(value=0)
                root.after(0, riabilita)

        threading.Thread(target=lavoro, daemon=True).start()

    btn_installa = ttk.Button(azioni, text="Installa", style="Azione.TButton",
                              command=lambda: esegui("installa"))
    btn_installa.grid(row=0, column=0, sticky="w")
    btn_ripristina = ttk.Button(azioni, text="Ripristina (inglese)",
                                command=lambda: esegui("ripristina"))
    btn_ripristina.grid(row=0, column=1, sticky="w", padx=px(8))

    def come_funziona():
        messagebox.showinfo(
            "Come funziona",
            "Il remaster contiene gia' i testi italiani ufficiali dentro gli archivi .ttarch2.\n\n"
            "1) SOLO TESTI: legge gli archivi *_ar_data.ttarch2 e Project_ar_all, estrae i testi\n"
            "   italiani e li scrive in Archives\\ come file sciolti <nome>_english.landb.\n"
            "   Il motore carica i file sciolti prima degli archivi, quindi menu, dialoghi e\n"
            "   sottotitoli diventano italiani. Gli archivi non vengono modificati.\n\n"
            "2) CAPITOLI: le schede narrative (ui_episode, ui_credits) esistono in 5 versioni,\n"
            "   una per episodio, con lo stesso nome: un file sciolto coprirebbe tutti gli\n"
            "   episodi. Per questo vengono presi dalla patch italiana vecchia e inseriti\n"
            "   dentro l'archivio del proprio episodio, riscritto nello stesso formato\n"
            "   (ZCTT, blocchi deflate 64 KB).\n\n"
            "Il merge e' per chiave (crc64): dove la traduzione manca resta l'inglese.\n\n"
            "BACKUP: prima di ogni modifica i file vengono copiati in old_patch_ita\\\n"
            "(archivi originali inclusi). 'Ripristina' rimette tutto a posto.\n\n"
            + APP_AUTHOR)

    ttk.Button(azioni, text="Come funziona", command=come_funziona).grid(row=0, column=2, sticky="w",
                                                                        padx=px(8))
    ttk.Button(azioni, text="Esci", command=root.destroy).grid(row=0, column=4, sticky="e")

    log("Benvenuto. %s." % APP_AUTHOR)
    log("1) scegli cosa installare   2) indica la cartella del gioco   "
        "3) (solo capitoli) indica la patch vecchia")
    log("")
    log("La cartella del gioco e' quella che contiene TheWolfAmongUsRemastered.exe "
        "e la cartella Archives.")

    # dimensione iniziale: comoda ma mai oltre lo schermo
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = min(px(900), int(sw * 0.94))
    h = min(px(760), int(sh * 0.90))
    root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
    root.minsize(px(720), px(620))
    root.deiconify()
    root.mainloop()


# -------------------------------------------------------------------- CLI
def main(argv):
    args = argv[1:]
    if "--cli" in args:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        mode = "capitoli" if "--capitoli" in args else "testi"
        game = None
        patch = None
        for i, a in enumerate(args):
            if a == "--game" and i + 1 < len(args):
                game = args[i + 1]
            if a == "--patch" and i + 1 < len(args):
                patch = args[i + 1]
        log = print
        if "--undo" in args:
            uninstall(game, log)
            return 0
        if mode == "capitoli":
            install(game, mode, patch, log)
        else:
            install(game, mode, None, log)
        return 0
    run_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
