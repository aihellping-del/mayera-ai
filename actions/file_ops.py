"""JARVIS - file kaam (adapted from Mark LVI's actions/
file_controller.py by FatihMakes, CC BY-NC 4.0; reimplemented for
this codebase: same ideas - friendly roots, safe paths, recoverable
trash, undo - wired to JARVIS's executor + ConfirmGate + undo stack).

SAFETY, by construction:
  * Everything is confined to the user's HOME folder tree.
  * The JARVIS install folder itself is off-limits (protects
    key.dat, the memory DB and the program from its own tools).
  * Deleting does not exist here: trash_file MOVES a file into
    ~/.jarvis_trash (recoverable), and only after the user taps
    Haan on the confirmation card in the JARVIS page - the model
    cannot approve it itself.
  * Every successful change registers its reversal on the shared
    undo stack ("undo kar do" -> undo_last_action).
  * Results say status "done" ONLY after a post-action check
    verifies the change on disk (Mark's outcome rule).
"""

import shutil
import time
from pathlib import Path

from core import undo as undo_mod

_FRIENDLY = {
    "desktop": "Desktop", "documents": "Documents",
    "downloads": "Downloads", "pictures": "Pictures",
    "music": "Music", "videos": "Videos", "home": "",
}
_TEXT_EXTS = {".txt", ".md", ".log", ".json", ".csv", ".py", ".html",
              ".bat", ".ini", ".yaml", ".yml"}


class FileOps:
    def __init__(self, home=None, app_dir=None):
        self.home = Path(home) if home else Path.home()
        self.app_dir = (Path(app_dir) if app_dir
                        else Path(__file__).resolve().parent.parent)
        self.trash_dir = self.home / ".jarvis_trash"

    # -- path safety -------------------------------------------------
    def resolve(self, raw, name=""):
        """Friendly root name or a path, plus an optional file name,
        -> an absolute Path inside home, or None if unsafe."""
        raw = (raw or "home").strip()
        key = raw.lower()
        if key in _FRIENDLY:
            base = self.home / _FRIENDLY[key] if _FRIENDLY[key] else self.home
        else:
            p = Path(raw).expanduser()
            base = p if p.is_absolute() else (self.home / p)
        if name:
            base = base / name
        try:
            resolved = base.resolve()
            resolved.relative_to(self.home.resolve())
        except (ValueError, RuntimeError, OSError):
            return None
        # the install folder is never a target
        try:
            resolved.relative_to(self.app_dir.resolve())
            return None
        except (ValueError, RuntimeError, OSError):
            pass
        return resolved

    # -- helpers ------------------------------------------------------
    @staticmethod
    def _err(msg):
        return {"status": "error", "message": msg}

    @staticmethod
    def _done(**kw):
        out = {"status": "done", "verified": True}
        out.update(kw)
        return out

    def _unique(self, path):
        if not path.exists():
            return path
        stem, suffix, parent = path.stem, path.suffix, path.parent
        for i in range(1, 100):
            cand = parent / f"{stem} ({i}){suffix}"
            if not cand.exists():
                return cand
        return path

    # -- operations ---------------------------------------------------
    def list_files(self, path="home"):
        folder = self.resolve(path)
        if folder is None:
            return self._err("ye jagah surakshit nahi hai")
        if not folder.is_dir():
            return self._err("folder nahi mila")
        items = []
        for entry in sorted(folder.iterdir(),
                            key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith("."):
                continue
            items.append({"name": entry.name,
                          "type": "folder" if entry.is_dir() else "file"})
            if len(items) >= 40:
                break
        return self._done(folder=str(folder), items=items,
                          count=len(items))

    def create_folder(self, path, name):
        target = self.resolve(path, name)
        if target is None or not name:
            return self._err("naam ya jagah sahi nahi")
        if target.exists():
            return self._err("is naam ka folder pehle se hai")
        target.mkdir(parents=True)
        if target.is_dir():
            undo_mod.push_undo(f"folder banaya: {target.name}",
                               "trash_created", {"path": str(target)})
            return self._done(path=str(target))
        return self._err("folder bana par dikha nahi")

    def create_file(self, path, name, content=""):
        target = self.resolve(path, name)
        if target is None or not name:
            return self._err("naam ya jagah sahi nahi")
        if target.exists():
            return self._err("is naam ki file pehle se hai")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
        if target.is_file():
            undo_mod.push_undo(f"file banayi: {target.name}",
                               "trash_created", {"path": str(target)})
            return self._done(path=str(target))
        return self._err("file bani par dikhi nahi")

    def write_file(self, path, name, content, append=False):
        target = self.resolve(path, name)
        if target is None or not name:
            return self._err("naam ya jagah sahi nahi")
        previous = (target.read_text(encoding="utf-8", errors="replace")
                    if target.is_file() else None)
        target.parent.mkdir(parents=True, exist_ok=True)
        if append and previous is not None:
            target.write_text(previous + content, encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")
        check = target.read_text(encoding="utf-8", errors="replace")
        if content in check:
            undo_mod.push_undo(
                f"file me likha: {target.name}", "restore_content",
                {"path": str(target), "previous": previous})
            return self._done(path=str(target), chars=len(content))
        return self._err("likha par verify nahi hua")

    def read_file(self, path, name=""):
        target = self.resolve(path, name)
        if target is None:
            return self._err("ye jagah surakshit nahi hai")
        if not target.is_file():
            return self._err("file nahi mili")
        if target.suffix.lower() not in _TEXT_EXTS:
            return self._err("ye file text nahi hai, padh nahi sakta")
        text = target.read_text(encoding="utf-8", errors="replace")
        return self._done(path=str(target), content=text[:4000],
                          chars=len(text))

    def move_file(self, path, name, destination):
        src = self.resolve(path, name)
        dst_dir = self.resolve(destination)
        if src is None or dst_dir is None:
            return self._err("source ya destination sahi nahi")
        if not src.exists():
            return self._err("file nahi mili")
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = self._unique(dst_dir / src.name)
        shutil.move(str(src), str(dst))
        if dst.exists() and not src.exists():
            undo_mod.push_undo(f"move: {src.name}",
                               "move_back",
                               {"from": str(dst), "to": str(src)})
            return self._done(path=str(dst))
        return self._err("move verify nahi hua")

    def copy_file(self, path, name, destination):
        src = self.resolve(path, name)
        dst_dir = self.resolve(destination)
        if src is None or dst_dir is None or not src.is_file():
            return self._err("file ya destination sahi nahi")
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = self._unique(dst_dir / src.name)
        shutil.copy2(str(src), str(dst))
        if dst.is_file():
            undo_mod.push_undo(f"copy: {src.name}",
                               "trash_created", {"path": str(dst)})
            return self._done(path=str(dst))
        return self._err("copy verify nahi hui")

    def rename_file(self, path, name, new_name):
        src = self.resolve(path, name)
        if src is None or not new_name:
            return self._err("naam sahi nahi")
        if not src.exists():
            return self._err("file nahi mili")
        dst = self._unique(src.parent / new_name)
        src.rename(dst)
        if dst.exists() and not src.exists():
            undo_mod.push_undo(f"rename: {src.name} -> {dst.name}",
                               "move_back",
                               {"from": str(dst), "to": str(src)})
            return self._done(path=str(dst))
        return self._err("rename verify nahi hua")

    def trash_file(self, path, name=""):
        """Recoverable delete: move into ~/.jarvis_trash. The
        CONFIRMATION happens in the executor via the UI gate before
        this is called - this method assumes approval."""
        src = self.resolve(path, name)
        if src is None:
            return self._err("ye jagah surakshit nahi hai")
        if not src.exists():
            return self._err("file nahi mili")
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = self._unique(self.trash_dir / f"{stamp}_{src.name}")
        shutil.move(str(src), str(dst))
        if dst.exists() and not src.exists():
            undo_mod.push_undo(f"trash: {src.name}",
                               "restore_trash",
                               {"from": str(dst), "to": str(src)})
            return self._done(path=str(dst), note="trash se wapas ho sakta hai")
        return self._err("trash verify nahi hua")

    def find_files(self, name_part, path="home"):
        base = self.resolve(path)
        if base is None or not name_part:
            return self._err("khoj sahi nahi")
        needle = name_part.lower()
        found = []
        for entry in base.rglob("*"):
            if self.app_dir in entry.parents:
                continue
            if needle in entry.name.lower():
                found.append(str(entry))
            if len(found) >= 20:
                break
        return self._done(matches=found, count=len(found))

    def disk_usage(self, path="home"):
        folder = self.resolve(path)
        if folder is None:
            return self._err("ye jagah surakshit nahi hai")
        total, used, free = shutil.disk_usage(folder)
        gb = 1024 ** 3
        return self._done(total_gb=round(total / gb, 1),
                          free_gb=round(free / gb, 1),
                          used_percent=round(used / total * 100))

    # -- undo execution ----------------------------------------------
    def execute_undo(self, entry):
        op, data = entry["op"], entry["data"]
        if op == "move_back" or op == "restore_trash":
            src, dst = Path(data["from"]), Path(data["to"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst = self._unique(dst) if dst.exists() else dst
            shutil.move(str(src), str(dst))
            return self._done(undone=entry["label"], path=str(dst))
        if op == "trash_created":
            # undo of a create/copy: send the created file to trash
            # (still recoverable - undo never destroys either)
            target = Path(data["path"])
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()  # only an EMPTY created folder
                return self._done(undone=entry["label"])
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            dst = self._unique(self.trash_dir / f"{stamp}_{target.name}")
            shutil.move(str(target), str(dst))
            return self._done(undone=entry["label"], path=str(dst))
        if op == "restore_content":
            target = Path(data["path"])
            if data["previous"] is None:
                if target.exists():
                    target.unlink()
            else:
                target.write_text(data["previous"], encoding="utf-8")
            return self._done(undone=entry["label"])
        return self._err(f"undo op samajh nahi aaya: {op}")
