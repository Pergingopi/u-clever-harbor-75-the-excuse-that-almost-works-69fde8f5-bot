"""The Excuse That Almost Works -- make.fun entry (program/v1).

Writes a single line of plain text to $MAKEFUN_OUTPUT_DIR/entry.txt:
the excuse a gamer texts the boss to skip work on GTA 6 launch week.

Gate (sealed scorer): /output/entry.txt must be UTF-8 text of 1 to 140
characters, not only white space. The brief also caps it at 20 words and
one line, reading like a real text sent in a hurry.

THE LINE (kept from the builder draft after a judge-brief review):
    "Sorry, my building's doing fire alarm testing all morning "
    "and they won't let anyone back in till lunch."
18 words, 103 characters. Why this one wins the pairwise comparison
against a tired manager who has heard every excuse twice:

* Boring and specific, not dramatic: a scheduled building fire-alarm
  test is the kind of administrative event a real building actually
  runs, and it locks the sender out without any injury, bereavement
  or vehicle trouble -- none of the cliches the manager filters out
  on sight (no dead grandmother, no flat tyre, no sudden fever).
* Almost verifiable: a manager could check with building management,
  which is exactly the "almost believe" bar -- checkable in principle,
  never actually checked for a half-day absence.
* Bounded: "all morning ... till lunch" puts a concrete end on the
  absence instead of an open-ended disappearance, so it reads like a
  real hurried text, not a story.
* No mention of the game, no setup, no signature, no over-explaining.

Alternatives considered and rejected (reviser, 25 Nov 2026):

1. Lift out in the block, 14th floor, bad knee, stairs shut for
   cleaning till noon. Stacks three excuses at once; a tired manager
   smells stacking, and "bad knee" invites a follow-up question the
   sender cannot answer. More melodramatic, less believable.
2. Water off in the whole street for emergency pipe repairs, no
   flushing or showers till midday. Boring and verifiable-sounding,
   but the "no showers" detail is TMI and slightly comic, and being
   without water does not actually stop anyone working remotely --
   the excuse fails its own job.
3. Council dug up the road outside the flat overnight, no cars in or
   out till resurfacing around lunchtime. Specific and verifiable,
   but roadworks is a classic excuse category the manager has heard
   twice already; the fire-alarm lockout is less hackneyed and blocks
   even entering the building, not just driving. At best a tie, so
   switching gains nothing and risks losing a known-good line.

Python 3.13 standard library only. Deterministic: the same bytes on
every run. Writes safely: mkstemp with O_EXCL, fsync of file and
directory, chmod 0644 before and after os.replace, read-back and gate
validation, plus a post-write stat check that the target is a regular
file with mode 0644. Stale partial-write temp files older than one
hour are swept best-effort at startup. Never deletes the output
directory itself.

Usage:
    python3 main.py [--output-dir DIR] [--self-test]
MAKEFUN_OUTPUT_DIR sets the output directory (default /output);
--output-dir overrides it. --self-test validates the entry and
prints its word/character counts without writing anything.
"""

import argparse
import os
import sys
import tempfile
import time

ENTRY = (
    "Sorry, my building's doing fire alarm testing all morning "
    "and they won't let anyone back in till lunch."
)

MAX_CHARS = 140
MAX_WORDS = 20
DEFAULT_OUT_DIR = "/output"
TMP_PREFIX = ".entry-"
TMP_SUFFIX = ".tmp"
STALE_TMP_MAX_AGE_SECONDS = 3600  # one hour


class EntryError(ValueError):
    """Raised when the entry text or the output setup fails a check."""


def validate(text):
    """Gate check: 1-140 chars, non-blank, one line, <=20 words,
    no control characters, no leading/trailing whitespace and no
    doubled spaces (a hurried real text has none of those)."""
    if not isinstance(text, str):
        raise EntryError("entry is not text")
    if not text or not text.strip():
        raise EntryError("entry is empty or only whitespace")
    if text != text.strip():
        raise EntryError("entry has leading or trailing whitespace")
    if "  " in text:
        raise EntryError("entry contains doubled spaces")
    if len(text) > MAX_CHARS:
        raise EntryError("entry exceeds %d characters" % MAX_CHARS)
    if "\n" in text or "\r" in text or "\t" in text:
        raise EntryError("entry must be a single line with no tab")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        raise EntryError("entry contains control characters")
    words = text.split()
    if len(words) > MAX_WORDS:
        raise EntryError("entry exceeds %d words" % MAX_WORDS)
    if len(words) < 1:
        raise EntryError("entry has no words")
    return text


def entry_stats(text):
    """Word/character/byte counts for the entry, for --self-test."""
    data = text.encode("utf-8")
    return {
        "words": len(text.split()),
        "chars": len(text),
        "bytes": len(data),
    }


def resolve_output_dir(raw):
    """Turn the raw output-dir setting into a usable absolute path.

    A missing, empty or whitespace-only value falls back to the
    default. An embedded NUL byte is rejected with a clear error
    instead of a bare ValueError from the os calls. A path that
    already exists but is not a directory is rejected the same way.
    """
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        value = DEFAULT_OUT_DIR
    if "\x00" in value:
        raise EntryError("output directory contains a NUL byte")
    path = os.path.abspath(os.path.expanduser(value))
    if os.path.lexists(path) and not os.path.isdir(path):
        raise EntryError("output path %r is not a directory" % path)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise EntryError(
            "cannot create output directory %r: %s" % (path, exc)
        ) from exc
    if not os.path.isdir(path):
        raise EntryError("output directory %r is not a directory" % path)
    return path


def cleanup_stale_tmp(out_dir):
    """Best-effort sweep of our own stale partial-write temp files.

    Only files we created (prefix .entry-, suffix .tmp) that are
    regular files older than STALE_TMP_MAX_AGE_SECONDS are removed,
    so a concurrent fresh write is never touched. Every failure is
    swallowed: a stale temp file must never fail the entry itself.
    """
    try:
        names = os.listdir(out_dir)
    except OSError:
        return 0
    now = time.time()
    removed = 0
    for name in names:
        if not name.startswith(TMP_PREFIX):
            continue
        if not name.endswith(TMP_SUFFIX):
            continue
        path = os.path.join(out_dir, name)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        import stat as statmod

        if not statmod.S_ISREG(st.st_mode):
            continue
        if now - st.st_mtime < STALE_TMP_MAX_AGE_SECONDS:
            continue
        try:
            os.unlink(path)
            removed += 1
        except OSError:
            continue
    return removed


def fsync_dir(path):
    """Flush a directory entry to disk; best-effort on platforms
    where opening a directory for fsync is not supported."""
    try:
        dir_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def write_entry(out_dir, text):
    """Atomically write the entry to out_dir/entry.txt and verify it.

    mkstemp (O_EXCL) -> chmod 0644 -> write -> fsync file ->
    chmod 0644 -> os.replace -> chmod 0644 -> fsync dir ->
    read-back bytes must equal what was written, decode as UTF-8,
    re-validate, and lstat must show a regular file with mode 0644.
    A failure at any step unlinks the temp file and raises.
    """
    data = text.encode("utf-8")
    target = os.path.join(out_dir, "entry.txt")

    fd, tmp_path = tempfile.mkstemp(
        dir=out_dir, prefix=TMP_PREFIX, suffix=TMP_SUFFIX
    )
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
        os.chmod(target, 0o644)
        fsync_dir(out_dir)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    import stat as statmod

    try:
        st = os.lstat(target)
    except OSError as exc:
        raise EntryError("cannot stat written entry: %s" % exc) from exc
    if not statmod.S_ISREG(st.st_mode):
        raise EntryError("written entry is not a regular file")
    if statmod.S_IMODE(st.st_mode) != 0o644:
        raise EntryError(
            "written entry has mode %o, expected 0644"
            % statmod.S_IMODE(st.st_mode)
        )

    with open(target, "rb") as fh:
        back = fh.read()
    if back != data:
        raise EntryError("read-back mismatch")
    validate(back.decode("utf-8"))
    return target


def self_test():
    """Validate the entry without writing anything; print its stats."""
    text = validate(ENTRY)
    stats = entry_stats(text)
    print("entry: %s" % text)
    print(
        "words=%d chars=%d bytes=%d (limits: %d words, %d chars)"
        % (
            stats["words"],
            stats["chars"],
            stats["bytes"],
            MAX_WORDS,
            MAX_CHARS,
        )
    )
    print("gate: PASS")
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Write the one-line excuse to entry.txt."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="output directory (overrides MAKEFUN_OUTPUT_DIR)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="validate the entry and print counts without writing",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.self_test:
        return self_test()

    text = validate(ENTRY)
    raw_dir = args.output_dir
    if raw_dir is None:
        raw_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or ""
    out_dir = resolve_output_dir(raw_dir)
    cleanup_stale_tmp(out_dir)
    write_entry(out_dir, text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EntryError as exc:
        print("error: %s" % exc, file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        sys.exit(1)
