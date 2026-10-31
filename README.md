# The Wolf Among Us Remastered — Patch ITA

[![build](https://github.com/HappyLoLTroll/twaoremastered-patch-ita/actions/workflows/build.yml/badge.svg)](https://github.com/HappyLoLTroll/twaoremastered-patch-ita/actions/workflows/build.yml)

Installer italiano per la traduzione italiana di **The Wolf Among Us Remastered** (PC).

> La remastered contiene già i testi italiani ufficiali: questo progetto non
> traduce nulla, li rende semplicemente quelli usati dal gioco. Vedi
> [Come sono stati ottenuti i testi italiani](#come-sono-stati-ottenuti-i-testi-italiani).

---

## Download

Ultima versione nella pagina **Releases**:
<https://github.com/HappyLoLTroll/twaoremastered-patch-ita/releases/latest>

Un solo file: `IWAU-ITA-Installer.exe` (nessuna installazione, nessun Python
richiesto). L'eseguibile della release viene compilato automaticamente da
GitHub Actions a ogni commit.

## Cosa fa

Due modalità, scelte nell'installer:

| modalità | cosa ottieni | richiede |
|---|---|---|
| **Solo testi e sottotitoli** | menu, impostazioni, obiettivi, fablespedia, dialoghi e sottotitoli in italiano | solo il gioco |
| **Testi + testo dei capitoli** | come sopra, più schede narrative (l'inizio di ogni episodio), **riassunti "Previously on / Next time on"** e **etichette di menu/UI** | la patch italiana della **versione vecchia** |

La patch vecchia serve solo per quei due file e si scarica qui:
<https://1drv.ms/u/s!ApMUGr0cuN39gcU1t4iqnsfx5KTodQ?e=y9QOEr>

## Come si usa

1. scegli la modalità;
2. indica la cartella del gioco (quella con `TheWolfAmongUsRemastered.exe` e
   `Archives`);
3. se hai scelto i capitoli, indica la cartella della patch vecchia
   (`The Wolf Among Us - ITA`, va bene anche la sua sottocartella `Pack`);
4. **Installa**. Per tornare all'inglese: **Ripristina (inglese)**.

Chiudi il gioco prima di installare. Alcuni antivirus segnalano gli eseguibili
creati con PyInstaller: è un falso positivo.

## Backup

Prima di modificare qualsiasi cosa, i file vengono copiati in:

```
<cartella del gioco>\old_patch_ita\
    manifest.json                      elenco di ciò che è stato toccato
    Archives\<nome>_english.landb      copie dei file sciolti preesistenti
    Archives\<archivio>.ttarch2.orig   archivi originali
    _precedenti\                       backup precedenti, se il gioco è cambiato
```

`Ripristina` usa il manifest e il controllo md5: rimette gli archivi originali
e cancella **solo** i file aggiunti dall'installer.

---

## Come sono stati ottenuti i testi italiani

Nessuna traduzione amatoriale: La remastered **contiene già** la localizzazione
italiana ufficiale (testi con copyright aggiornati al 2026), semplicemente non
viene usata se il gioco è impostato su inglese — e il selettore lingua
originale non basta per le schede narrative, perché i file sono condivisi fra
episodi.

Il lavoro è stato: capire il formato degli archivi, estrarre i testi, e
ricostruire i file nel formato atteso dal motore.

### 1. Archivi `.ttarch2`

Due contenitori, riconoscibili dai primi 4 byte:

**`NCTT`** — non compresso:

```
NCTT | u64 dimensione_stream | indice | nomi | dati
```

**`ZCTT`** — compresso:

```
ZCTT | u32 dimensione_blocco (0x10000) | i32 numero_blocchi
     | (numero_blocchi+1) × u64 offset assoluti
     | blocchi deflate (zlib, finestra grezza, 64 KB l'uno)
```

Dentro il flusso (decompresso, per ZCTT) c'è l'indice:

```
tag "4ATT" (o "3ATT" con 4 byte di versione in più)
u32 nameSize (di norma 0x10000)   u32 numero_file
numero_file × 28 byte: u64 crc64 | u64 offset | i32 size | i32 unknow
                       | u16 nameBlock | u16 nameOffset
nomi (paginati: nome = base + nameOffset + nameBlock*0x10000)
dati (l'offset è relativo a dataStart = base + 28*numero_file + nameSize)
```

Gli archivi dei set di localizzazione (`*_french_ar_all`, `_german`, `_spanish`)
sono `NCTT`, quindi il formato "semplice" è accettato dal motore: utile per
scrivere, mentre la riscrittura degli archivi di gioco usa `ZCTT` per restare
identica all'originale.

### 2. File di testo `.landb`

Il formato è `6VSM` (leggi `MSV6`): intestazione con tre `u32` (dimensione del
blocco, dimensione del blocco finale, campo nullo), tabella dei blocchi
(classi hashete: `B0-9F-D8-63-34-02-4F-00` = presenza del `crc64Langres`,
`53-DC-A5-33-DB-D6-DC-7E` = campi unicode), poi le voci:

```
wavID | crc64Langres | anmID | zero | blockAnm | anmName(8)
blockWav | wavName(8) | blockUnk | unkName | zero2
blockLangres | blockActor | actorName | blockSpeech | actorSpeech
blockSize | someValue | [unicode] | flags
```

`actorSpeech` è il testo. `crc64Langres` è la chiave stabile fra lingue: la
stessa battuta ha lo stesso `crc64` in `_english.landb` e in `_italian.landb`.

### 3. Merge per chiave, non sostituzione del file

Sostituire il file intero non funziona: i file italiani della remastered sono più
vecchi e alcune voci (le schede narrative aggiunte nella remastered) mancano,
quindi il motore mostra il valore di default cablato nella scena — `Hello`.

La soluzione usata dall'installer:

1. si parte dal file **inglese della remastered** (struttura e flag corretti);
2. si sostituisce `actorSpeech` solo per le voci il cui `crc64Langres` esiste
   anche in italiano;
3. le voci mancanti o con segnaposto (`Hello`) restano in inglese;
4. il file viene riscritto ricalcolando solo le dimensioni delle stringhe
   modificate: i file non toccati sono **byte per byte identici**
   (round-trip verificato).

### 4. Consegna del testo al motore

**File sciolti.** Ogni set di risorse ha `localDir = Archives` e
`localDirIncludeBase = true`: il motore carica anche i file presenti in
`Archives\`. Scrivendo lì `<nome>_english.landb` il testo italiano ha
precedenza e **nessun archivio viene modificato**. È la modalità "solo testi".

**Dentro l'archivio.** `ui_episode` e `ui_credits` esistono in 5 versioni, una
per episodio, con lo stesso nome: un file sciolto coprirebbe tutti gli episodi
con la versione sbagliata (era la causa del `Hello` e del capitolo che non
partiva). Per questo, in modalità capitoli, l'installer:

1. prende quei testi dalla patch della **versione vecchia** — dove i nomi delle
   lingue sono invertiti (il testo italiano sta in `*_english.landb`,
   l'inglese originale in `*_italian.landb`);
2. li inserisce nell'archivio del rispettivo episodio sostituendo le voci
   omonime;
3. riscrive l'archivio in `ZCTT` come l'originale, ricalcolando offset e
   dimensioni nell'indice e lasciando intatti nomi, `crc64` e campi ignorati;
4. verifica che tutti gli altri file dell'archivio restino byte-identici.


### 5. Accenti nei menu (bug del remaster)

Nelle schermate con testo **maiuscolo** (Impostazioni, Conferme) il remaster
disegna i caratteri in modalità ANSI: una `À` UTF-8 (`C3 80`) viene mostrata
come `Ã¿`. Il difetto c'è anche nei file italiani **ufficiali**, quindi non
dipende dalla patch: `QUALITÀ GRAFICA` → `QUALITÃ¿ GRAFICA`.

Riscrivere il file con dimensioni diverse non è un'opzione: il motore scarta il
`.landb` e il menu resta **vuoto** (verificato: cp1252, ASCII, `some_value`
diverso). L'unica modifica accettata è a **parità di byte**:

```
"À"  C3 80  ->  "A'"  41 27      (2 byte -> 2 byte)
"…"  E2 80 A6 -> "..." 2E 2E 2E  (3 byte -> 3 byte)
```

Sostituendo solo le sequenze accentate dentro `ui_menu_italian.landb`
(37 punti, 74 byte su 129.674) dimensione, offset, `some_value` e struttura
restano identici all'originale: il menu si carica e le scritte diventano
leggibili (`QUALITA' GRAFICA`, `SI'`, `APPLICA`).

L'installer fa esattamente questo, e solo per `ui_menu`: dialoghi, sottotitoli
e schede narrative restano in UTF-8 con gli accenti veri, perché in quelle
schermate il rendering è corretto.

Dettagli completi: [`docs/FORMAT.md`](docs/FORMAT.md).

---

## Compilare

```
pip install pyinstaller
Ricompila.bat
```

oppure:

```
python -m PyInstaller --onefile --windowed --name "IWAU-ITA-Installer" ^
  --version-file "%CD%\version_info.txt" --distpath . --workpath build ^
  --specpath build installer_ita.py
```

## CLI (debug)

```
IWAU-ITA-Installer.exe --cli --game "F:\...\The Wolf Among Us Remastered"
IWAU-ITA-Installer.exe --cli --capitoli --game "<gioco>" --patch "E:\...\The Wolf Among Us - ITA"
IWAU-ITA-Installer.exe --cli --undo --game "<gioco>"
```

## Note

- Doppiaggio: l'edizione contiene solo l'audio inglese; cambiano testi, menu e
  sottotitoli.
- I nomi dei personaggi seguono la patch vecchia nei capitoli (*Neve*,
  *Pancopinco*, *Pincopanco*) e la traduzione della remastered nei dialoghi
  (*Bianca*, *Pinco*, *Panco*).
- Il progetto non distribuisce materiale del gioco: l'installer legge i file
  dalla copia dell'utente.
