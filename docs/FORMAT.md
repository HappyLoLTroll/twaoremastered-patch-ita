# Formati: `.ttarch2` e `.landb` (The Wolf Among Us Remastered)

Appunti di reverse engineering usati dall'installer. Nessun byte di gioco è
incluso in questo repository: qui c'è solo la descrizione dei formati.

---

## 1. Archivi `.ttarch2`

Riconoscimento dai primi 4 byte:

| magic | significato |
|---|---|
| `NCTT` | archivio non compresso |
| `ZCTT` | compresso, blocchi **deflate** (zlib, finestra grezza) da 64 KB |
| `eCTT` / `zCTT` | varianti compresse (Oodle/zlib) — non usate dall'installer |

### 1.1 NCTT

```
offset 0   char[4]  "NCTT"
offset 4   u64      dimensione del flusso logico (file_size - 12)
offset 12  ...      flusso logico (vedi 1.3)
```

### 1.2 ZCTT

```
offset 0   char[4]  "ZCTT"
offset 4   u32      dimensione blocco (0x10000)
offset 8   i32      numero blocchi (n)
offset 12  u64[n+1] offset assoluti nel file: inizio/fine di ogni blocco
offset ..  byte[]   n blocchi deflate concatenati
```

Il flusso logico è la concatenazione dei blocchi decompressi.

### 1.3 Flusso logico (indice)

```
tag            char[4]   "4ATT" (oppure "3ATT": in questo caso segue u32 versione)
u32 nameSize             di norma 0x10000
u32 count                numero di file
record[count]            28 byte ciascuno:
    u64 crc64
    u64 offset           relativo a dataStart
    i32 size
    i32 unknown
    u16 nameBlock
    u16 nameOffset
nomi                     nameSize byte, paginati da 64 KB
dati                     file concatenati
```

Nomi: `nome = baseNomi + nameOffset + nameBlock * 0x10000`, stringa ASCII
terminata da `0x00`.

```
baseNomi  = inizio_record + 28 * count
dataStart = baseNomi + nameSize
```

Scrivendo un archivio da zero si può usare `NCTT` (il motore accetta il
formato non compresso); per riscrivere un archivio esistente conviene invece
mantenere `ZCTT` con gli stessi parametri, così il file resta strutturalmente
identico all'originale (usato per `ui_episode`/`ui_credits`).

---

## 2. File `.landb` (versione 6)

Magic `6VSM` (in ASCII si legge `MSV6`).

### 2.1 Intestazione

```
char[4] magic      "6VSM" (o "5VSM")
u32     fileSize   dimensione della sezione voci
u32     lastSize   dimensione del blocco finale (tabella condivisa)
u32     unknown    di norma 0
u32     countBlocks
countBlocks × ( char[8] hashClasse + u32 valore )
```

Classi note:

| hash | significato |
|---|---|
| `B0-9F-D8-63-34-02-4F-00` | le voci hanno il campo `crc64Langres` |
| `53-DC-A5-33-DB-D6-DC-7E` | le voci hanno i campi unicode extra |

### 2.2 Sezione voci

```
u32 b1, u32 s1, u32 b2, u32 s2
u32 blockLen        = fileSize - 32 - commonLen
u32 count
count × voce:
    u32  wavID
    u64  crc64Langres        <-- chiave stabile fra le lingue
    u32  anmID
    i32  zero
    i32  blockAnm
    char[8] anmName          (hash)
    i32  blockWav
    char[8] wavName          (hash)
    i32  blockUnk
    i32  unkSize + byte[unkSize]
    i32  zero2
    i32  blockLangres
    i32  blockActor
    i32  actorSize + byte[actorSize]
    i32  blockSpeech
    i32  speechSize + byte[speechSize]   <-- TESTO mostrato
    i32  blockSize, i32 someValue
    [se unicode] i32 blockUni + byte[blockUni-4]
    i32  flags
u32 commonLen + byte[commonLen-4]
u32 ×4  dati finali
byte[lastSize]  blocco finale
```

`fileSize = 24 + somma(voci) + commonLen + 16`.

### 2.3 Merge per chiave

La stessa battuta ha lo stesso `crc64Langres` in tutte le lingue. L'installer:

1. legge il file **inglese** (struttura del remaster);
2. per ogni voce cerca il `crc64Langres` nel file italiano;
3. sostituisce solo `speech` quando la traduzione esiste e non è un segnaposto
   (`Hello`);
4. riscrive aggiornando `blockLangres`, `blockSpeech` e le lunghezze con il
   delta della stringa, più `fileSize`/`blockLen`.

Le voci non modificate sono ricostruite dai byte originali, quindi il file
prodotto è byte-identico all'input quando non c'è nulla da tradurre
(round-trip usato come test).

---

## 3. Perché i file sciolti funzionano

Ogni set di risorse (`Archives\_resdesc_50_*.lua`) dichiara:

```lua
set.localDir = _currentDirectory
set.localDirIncludeBase = true
```

Il motore quindi carica anche i file che stanno direttamente in `Archives\`;
un `<nome>_english.landb` sciolto ha precedenza sulla voce dentro l'archivio.
Da qui la modalità "solo testi": 80 file, nessun archivio toccato.

Limite: il nome è unico. `ui_episode_english.landb` e `ui_credits_english.landb`
esistono in 5 versioni (una per episodio): un file sciolto coprirebbe tutti gli
episodi con la versione sbagliata, causando `Hello` al posto della scheda
narrativa e l'impossibilità di avviare il capitolo. Per questo quei due file
vanno inseriti **dentro** l'archivio del rispettivo episodio.
