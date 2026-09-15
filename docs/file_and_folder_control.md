# Nova Phase 5.8-G — File & Folder Control

## 1. Overview & Architecture

Phase 5.8-G introduces safe, reliable, and bounded file and folder control for Nova on Windows. It enforces strict separation of concerns, single capability ownership, and defense-in-depth security policies.

### Single Capability Ownership

To eliminate ambiguity and prevent duplicate registrations, capabilities are partitioned strictly as follows:

| Intent | Skill | Actions / Parameters | Responsibility |
|---|---|---|---|
| `find_file` | `FileSearchSkill` | `pattern`, `extension`, `search_root`, `max_results` | Bounded file search across standard user roots |
| `open_folder` | `ExplorerSkill` | `path` | Opening folder in Windows File Explorer |
| `file_operation` | `FileOpsSkill` | `action`: `list_directory`, `get_file_info`, `open_file`, `create_folder`, `create_file`, `rename_file`, `copy_file`, `move_file`, `delete_file` | Safe filesystem operations |

Aliases:
- `"file"` -> `"file_operation"`
- `"file_control"` -> `"file_operation"`

---

## 2. PathGuard Security Pipeline

Every filesystem request passes through `PathGuard` before execution:

```
raw user path
      ↓
lexical & syntax validation
      ↓
Windows canonicalization & resolution
      ↓
operation-specific policy check (READ / WRITE / DELETE / LIST / EXECUTE_OPEN)
      ↓
protected boundary validation (System32, Program Files, drive roots)
      ↓
reparse point, symlink, & junction validation
      ↓
ancestor chain validation (all existing parent directories)
      ↓
pre-action race-resistant verification
      ↓
filesystem operation (Python standard library only)
```

### Syntax & Lexical Invariants
1. **Drive Letter vs ADS**:
   - Valid drive-letter prefix (`^[A-Za-z]:[\\/]`) is allowed.
   - Any colon other than index 1 (or multiple colons) is rejected as an Alternate Data Stream (ADS) attempt (e.g. `file.txt:stream`).
2. **Control Characters & Null Bytes**:
   - Null bytes (`\0`) and ASCII control characters (0x01–0x1F) are strictly rejected.
3. **UNC & Device Namespaces**:
   - UNC paths (`\\server\share`, `//server/share`) are rejected.
   - Device namespaces (`\\.\`, `\\?\`, `\??\`) are rejected.
4. **DOS Reserved Device Names**:
   - Standalone and extension-suffixed DOS devices (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`) are rejected.
5. **Reparse Points & Symlinks**:
   - Reparse points (`FILE_ATTRIBUTE_REPARSE_POINT (0x400)`) and symlinks are detected via `os.lstat` and Win32 `GetFileAttributesW`.
   - Mutations (`WRITE`, `DELETE`) on symlinks and junctions are strictly forbidden.
6. **Ancestor Chain Validation**:
   - Every existing parent directory in the path hierarchy is validated to prevent directory traversal escapes through junctions or protected system roots.

---

## 3. Action-Specific Parameter Matrix

Parameters are validated before filesystem execution. Unexpected or disallowed parameters immediately reject the request:

| Action | `path` | `source` | `destination` | `content` | Disallowed Parameters |
|---|---|---|---|---|---|
| `list_directory` | Optional (default cwd) | Rejected | Rejected | Rejected | `source`, `destination`, `content` |
| `get_file_info` | Required | Rejected | Rejected | Rejected | `source`, `destination`, `content` |
| `open_file` | Required | Rejected | Rejected | Rejected | `source`, `destination`, `content` |
| `create_folder` | Required | Rejected | Rejected | Rejected | `source`, `destination`, `content` |
| `create_file` | Required | Rejected | Rejected | Optional | `source`, `destination` |
| `rename_file` | Rejected | Required | Required | Rejected | `path`, `content` |
| `copy_file` | Rejected | Required | Required | Rejected | `path`, `content` |
| `move_file` | Rejected | Required | Required | Rejected | `path`, `content` |
| `delete_file` | Required | Rejected | Rejected | Rejected | `source`, `destination`, `content` |

---

## 4. Overwrite & Conflict Policy

In V1, **overwrite is ALWAYS false**:
- `create_file`: Fails safely if destination file already exists.
- `copy_file`: Fails safely if destination file already exists.
- `move_file`: Fails safely if destination file already exists.
- `rename_file`: Fails safely if destination file already exists.
- `create_folder`: Fails safely if directory already exists.

The LLM tool schema does not expose `overwrite=true`. Silent replacement is strictly prohibited.

---

## 5. open_file Security

Files launched via Windows association use `os.startfile` (`shell=False`) and enforce a strict allowlist of documents, media, and project files.

### Safe Extension Allowlist
- Documents: `.txt`, `.csv`, `.tsv`, `.json`, `.xml`, `.yaml`, `.yml`, `.md`, `.log`, `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`
- Code: `.py`, `.c`, `.cpp`, `.h`, `.java`, `.html`, `.css`
- Media: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.svg`, `.webp`, `.mp3`, `.wav`, `.m4a`, `.mp4`, `.mkv`, `.avi`

### Explicit Forbidden Blacklist
- Executables & Scripts: `.exe`, `.com`, `.msi`, `.scr`, `.pif`, `.cpl`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.vbe`, `.js`, `.jse`, `.wsf`, `.wsh`, `.hta`, `.lnk`, `.url`, `.msc`, `.reg`

Any unlisted extension is blocked.

---

## 6. delete_file & High-Risk Confirmation

File deletion is classified as `RiskLevel.HIGH` by `StepRiskPolicy`:
- Requires valid token confirmation through `ConfirmationManager`.
- Operates strictly on regular files (`os.path.isfile` and not symlink/junction).
- Strictly rejects directories (`os.path.isdir`).
- Never recursively deletes.
- Uses narrowest direct Python call: `os.unlink`.
- Absolutely forbids `shutil.rmtree`, `shell=True`, `cmd.exe`, `PowerShell`, `del`, `rmdir`, `taskkill`.

### TOCTOU Defense-in-Depth
Immediately before deletion or modification, `PathGuard.pre_action_verify_file()` re-validates:
- Target existence and regular file attributes.
- Target is not a reparse point or directory.
- Immediate parent directory existence and non-reparse status.
- Protected boundary validation.

*Note on TOCTOU*: In a non-transactional OS filesystem, atomic unlink of arbitrary paths without kernel file handles inherently carries residual sub-microsecond race conditions if another malicious process swaps paths concurrently. Nova minimizes this window via immediate pre-action checks and strict ancestor chain integrity.

---

## 7. Bounded File Search (`FileSearchSkill`)

`FileSearchSkill` preserves sole ownership of `find_file`:
- Bounded traversal: default `max_depth = 4`, default `max_results = 20`.
- Hard result cap: `50` results maximum.
- Bounded root directories: standard user folders (Desktop, Documents, Downloads, etc.) or validated explicit `search_root`.
- `followlinks=False` in `os.walk`.
- Automatic skipping of hidden directories (`.git`), build directories (`node_modules`, `site-packages`, `__pycache__`), system directories (`$recycle.bin`, `System Volume Information`, `AppData`), and junctions/reparse points.
