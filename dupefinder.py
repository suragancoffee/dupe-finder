#!/usr/bin/env python3
"""dupefinder: 폴더 안의 중복 파일을 내용(해시) 기준으로 찾습니다.

사용 예:
    python dupefinder.py ~/Downloads                   # 중복 목록만 출력
    python dupefinder.py ~/Downloads --min-size 1MB    # 1MB 이상만 검사
    python dupefinder.py ~/Downloads --move-to ~/dupes # 중복본을 다른 폴더로 이동
    python dupefinder.py ~/Downloads --delete          # 중복본 삭제 (확인 후)
"""
import argparse
import hashlib
import shutil
import sys
from collections import defaultdict
from pathlib import Path

CHUNK = 1024 * 1024  # 1MB씩 읽어서 큰 파일도 메모리를 아낍니다
UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


def parse_size(text: str) -> int:
    """'500KB', '1MB' 같은 문자열을 바이트로 바꿉니다."""
    t = text.strip().upper()
    for unit in ("GB", "MB", "KB", "B"):
        if t.endswith(unit):
            return int(float(t[: -len(unit)]) * UNITS[unit])
    return int(t)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


def file_hash(path: Path, partial: bool = False) -> str:
    """partial=True면 앞 1MB만 해시해서 빠르게 1차 걸러냅니다."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        if partial:
            h.update(f.read(CHUNK))
        else:
            while chunk := f.read(CHUNK):
                h.update(chunk)
    return h.hexdigest()


def scan(root: Path, min_size: int, include_hidden: bool):
    for p in root.rglob("*"):
        try:
            if p.is_symlink() or not p.is_file():
                continue
            if not include_hidden and any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            if p.stat().st_size >= min_size:
                yield p
        except OSError:
            continue  # 권한 문제 등은 건너뜁니다


def find_duplicates(root: Path, min_size: int = 1, include_hidden: bool = False):
    """크기 -> 앞부분 해시 -> 전체 해시 순으로 좁혀서 중복 그룹을 찾습니다."""
    by_size = defaultdict(list)
    for p in scan(root, min_size, include_hidden):
        by_size[p.stat().st_size].append(p)

    groups = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_partial = defaultdict(list)
        for p in paths:
            try:
                by_partial[file_hash(p, partial=True)].append(p)
            except OSError:
                continue
        for same_partial in by_partial.values():
            if len(same_partial) < 2:
                continue
            by_full = defaultdict(list)
            for p in same_partial:
                try:
                    by_full[file_hash(p)].append(p)
                except OSError:
                    continue
            for same in by_full.values():
                if len(same) > 1:
                    # 가장 오래된 파일을 원본으로 보고 맨 앞에 둡니다
                    same.sort(key=lambda x: (x.stat().st_mtime, str(x)))
                    groups.append((size, same))
    groups.sort(key=lambda g: g[0] * (len(g[1]) - 1), reverse=True)  # 낭비 큰 순
    return groups


def main() -> None:
    ap = argparse.ArgumentParser(description="중복 파일 찾기")
    ap.add_argument("folder", type=Path, help="검사할 폴더 (하위 폴더 포함)")
    ap.add_argument("--min-size", default="1B", help="이 크기 이상만 검사 (예: 100KB, 1MB)")
    ap.add_argument("--hidden", action="store_true", help="숨김 파일/폴더도 검사")
    ap.add_argument("--move-to", type=Path, help="중복본(원본 제외)을 이 폴더로 이동")
    ap.add_argument("--delete", action="store_true", help="중복본(원본 제외) 삭제")
    args = ap.parse_args()

    root = args.folder.expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"폴더를 찾을 수 없습니다: {root}")
    if args.move_to and args.delete:
        sys.exit("--move-to 와 --delete 는 함께 쓸 수 없습니다.")

    groups = find_duplicates(root, parse_size(args.min_size), args.hidden)
    if not groups:
        print("중복 파일이 없습니다.")
        return

    wasted = 0
    for i, (size, files) in enumerate(groups, 1):
        wasted += size * (len(files) - 1)
        print(f"\n[{i}] {human(size)} x {len(files)}개")
        for j, f in enumerate(files):
            print(f"   {'원본' if j == 0 else '중복'}  {f.relative_to(root)}")

    dupes = [f for _, files in groups for f in files[1:]]
    print(f"\n중복 그룹 {len(groups)}개, 중복 파일 {len(dupes)}개, 절약 가능 용량 {human(wasted)}")

    if args.move_to:
        dest_root = args.move_to.expanduser().resolve()
        dest_root.mkdir(parents=True, exist_ok=True)
        for f in dupes:
            dest = dest_root / f.name
            n = 1
            while dest.exists():
                dest = dest_root / f"{f.stem} ({n}){f.suffix}"
                n += 1
            shutil.move(str(f), str(dest))
        print(f"{len(dupes)}개 파일을 {dest_root} 로 이동했습니다.")
    elif args.delete:
        if input(f"중복 {len(dupes)}개를 정말 삭제할까요? (y/N) ").strip().lower() != "y":
            print("취소했습니다.")
            return
        for f in dupes:
            f.unlink()
        print(f"{len(dupes)}개 파일을 삭제했습니다.")
    else:
        print("(미리보기) 파일은 바뀌지 않았습니다. 정리하려면 --move-to 또는 --delete 를 쓰세요.")


if __name__ == "__main__":
    main()
