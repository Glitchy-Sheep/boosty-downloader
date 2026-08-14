# Filesystem path and name limits

**Every path has two independent limits:**
- one **name** is limited by the filesystem
- the **whole path** - by the OS API. 

**Systems count in different units:**
- Linux in UTF-8 bytes
- macOS and Windows in UTF-16 units:
  - Latin letter = 1 unit = 1 byte
  - Cyrillic = 1 unit = 2 bytes
  - emoji = 2 units = 4 bytes.

## Limits per system

| System                             | One name         | In real letters: Latin / Cyrillic / emoji | Whole path                                 |
| ---------------------------------- | ---------------- | ----------------------------------------- | ------------------------------------------ |
| Linux (ext4, btrfs, xfs, f2fs)     | 255 UTF-8 bytes  | 255 / 127 / 63                            | 4096 bytes                                 |
| Android / Termux                   | 255 UTF-8 bytes  | 255 / 127 / 63                            | 4096 bytes                                 |
| macOS (APFS, HFS+)                 | 255 UTF-16 units | 255 / 255 / 127                           | 1024 bytes                                 |
| Windows (NTFS)                     | 255 UTF-16 units | 255 / 255 / 127                           | 260 units; ~32 767 with `LongPathsEnabled` |
| USB stick / SD card (exFAT, FAT32) | 255 UTF-16 units | 255 / 255 / 127                           | limit of the OS it is plugged into         |

## Examples

```
━━━ Linux (ext4/btrfs/xfs/f2fs) ━━ name <= 255 bytes ━━ path <= 4096 bytes ━━━

# name: 127 Cyrillic letters = 254 bytes -> fits
✅ /home/alice/boosty/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя

# name: 128 Cyrillic letters = 256 bytes -> Errno 36 File name too long
❌ /home/alice/boosty/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя

# name: 64 emoji = 256 bytes -> Errno 36
❌ /home/alice/boosty/🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

━━━ macOS (APFS/HFS+) ━━ name <= 255 UTF-16 units ━━ path <= 1024 bytes ━━━

# name: 255 Cyrillic letters = 255 units, 510 bytes -> fits here, dies on Linux
✅ /Users/alice/boosty/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя

# name: a + 127 emoji = 255 units, 509 bytes -> fits
✅ /Users/alice/boosty/a🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

# name: aa + 127 emoji = 256 units, 510 bytes -> Errno 63: the counter is units, not bytes
❌ /Users/alice/boosty/aa🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

# every name is 200 bytes and legal, the whole path is 1225 bytes > 1024 -> Errno 63
❌ /Users/alice/boosty/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя/яяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяяя

━━━ Windows (NTFS) ━━ name <= 255 units ━━ path <= 260 units by default ━━━

# path: 55 units total -> fits
✅ C:\Boosty\2026-08-14 - Стрим (a2dd6942)\files\отчёт.pdf

# name: 128 emoji = 256 units > 255 -> WinError 206, even with long paths enabled
❌ C:\Boosty\🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

# both names are legal (120 and 115 units), the whole path is 281 units > 260 -> WinError 206
❌ C:\Users\alice\Downloads\boosty\author\Огромный стрим о жизни канала, ответы на вопросы подписчиков, планы на будущее и розыгрыш призов среди всех зрителей эфи\files\Огромный стрим о жизни канала, ответы на вопросы подписчиков, планы на будущее и розыгрыш призов среди всех зри.pdf

# the same path after LongPathsEnabled = 1 (HKLM\SYSTEM\CurrentControlSet\Control\FileSystem): the limit becomes ~32 767 units
✅ C:\Users\alice\Downloads\boosty\author\Огромный стрим о жизни канала, ответы на вопросы подписчиков, планы на будущее и розыгрыш призов среди всех зрителей эфи\files\Огромный стрим о жизни канала, ответы на вопросы подписчиков, планы на будущее и розыгрыш призов среди всех зри.pdf
```

What boosty-downloader relies on: 
- every generated name is capped at `MAX_NAME_BYTES = 240` bytes (`path_sanitizer.py`)
- characters <= UTF-16 units <= UTF-8 bytes for any text, so 240 bytes fits every system above with headroom
- The full-path limit stays on the user: on default Windows keep the destination short (`C:\Boosty`) or enable `LongPathsEnabled`.
