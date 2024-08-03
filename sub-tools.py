# -*- coding: utf-8 -*-
import argparse, logging, re
from dataclasses import dataclass, field
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from tqdm import tqdm
from pathlib import Path
import subprocess as sp
from itertools import groupby, combinations

import chardet

STYLE_DEFAULT = """Style: Default,GenYoMin TW H,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,90,100,0.1,0,1,1,3,2,30,30,15,1
Style: ENG,GenYoMin TW B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JPN,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1"""
STYLE_2_EN = "{\\rENG}"
STYLE_2_JP = "{\\rJPN}"
STYLE_EN = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
ARGS = ""
LIST_LANG = [
  "eng",
  "chi",
  "zho",
  "jpn",
]  # "jpn", "spa"  # LIST_LANG  需要提取的字幕语言的ISO639代码列表
EFFECT = "{\\blur3}"
logger = logging.getLogger("sub_tools")


class CustomFormatter(logging.Formatter):
  reset = "\x1b[0m"
  fmt = "%(levelname)s - %(message)s"
  debug_format = "%(asctime)s - %(levelname)s - %(message)s \n(%(filename)s:%(lineno)d)"
  FORMATS = {
    logging.DEBUG: (grey := "\x1b[38;20m") + debug_format + reset,
    logging.INFO: (green := "\x1b[32m") + fmt + reset,
    logging.WARNING: (yellow := "\x1b[33;20m") + debug_format + reset,
    logging.ERROR: (red := "\x1b[31;20m") + debug_format + reset,
    logging.CRITICAL: (bold_red := "\x1b[31;1m") + fmt + reset,
  }

  def format(self, record):
    return logging.Formatter(self.FORMATS.get(record.levelno)).format(record)


def read_file(file: Path) -> str:
  return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])


def isCJK(x: str) -> bool:
  return "\u4e00" <= x <= "\u9fff"


def has_jp(text: str) -> bool:
  return any("\u3040" <= char <= "\u30f0" for char in text)


def has_cjk(text: str) -> bool:
  return any(isCJK(char) for char in text)


def is_eng_only(text: str) -> bool:
  return re.fullmatch("^[\\W\\sA-Za-z0-9_\\u00A0-\\u03FF]+$", text) is not None


def is_exist(f: Path, force: bool = False) -> bool:
  return logger.warning(f"{f} exist") or not force if f.is_file() else False


@dataclass
class SubtitleLine:
  begin: str
  end: str
  content: List[str]
  begin_time: int
  end_time: int

  @classmethod
  def from_srt(cls, begin: str, end: str, content: List[str]):
    return cls(begin, end, content, cls.time_to_ms(begin), cls.time_to_ms(end))

  @staticmethod
  def time_to_ms(rawtime: str) -> int:
    hour, minute, second, millisecond = map(int, re.split(r"[:,]", rawtime))
    return millisecond + 1000 * (second + (60 * (minute + 60 * hour)))


@dataclass
class SRT:
  content: List[SubtitleLine] = field(default_factory=list)

  @classmethod
  def load(cls, file: Path, escape="\\N"):
    content = []
    for chunk in re.split(r"\r?\n\r?\n\d+\r?\n", read_file(file)[2:]):
      lines = chunk.splitlines()
      begin, end = lines[0].strip().split(" --> ")
      content.append(SubtitleLine.from_srt(begin, end, [escape.join(lines[1:])]))
    return cls(content)

  def merge_with(self, srt: "SRT", time_shift: int = 1000) -> "SRT":
    def cjk_percentage(z):
      all_text = "".join([x for y in z for x in y.content])
      return sum(map(isCJK, all_text)) / (len(all_text) + 1)

    content1, content2 = self.content, srt.content
    if cjk_percentage(content1) < cjk_percentage(content2):
      content1, content2 = content2, content1

    merged_content = []
    i, j = 0, 0
    while i < len(content1) and j < len(content2):
      if content1[i].begin_time - time_shift <= content2[j].begin_time and content1[i].end_time + time_shift >= content2[j].end_time:
        content1[i].content.extend(content2[j].content)
        j += 1
      elif content1[i].begin_time < content2[j].begin_time:
        merged_content.append(content1[i])
        i += 1
      else:
        merged_content.append(content2[j])
        j += 1

    merged_content.extend(content1[i:])
    merged_content.extend(content2[j:])
    return SRT(merged_content)

  def dump(self, file: Path):
    output = ["\n".join([str(i), f"{line.begin} --> {line.end}", *line.content, ""]) for i, line in enumerate(self.content, start=1)]
    file.write_text("\n".join(output), encoding="utf-8")


@dataclass
class ASSEvent:
  layer: str = ""
  start: str = ""
  end: str = ""
  style: str = "Default"
  actor: str = ""
  marginl: int = 0
  marginr: int = 0
  marginv: int = 0
  effect: str = ""
  text: str = ""

  @classmethod
  def from_string(cls, s: str):
    fields = s.split(":", 1)[1].strip().split(",", 9)
    return cls(*fields)

  def update_style(self, second_style: str):
    self.text = re.sub(r"\{.*?\}|<.*?>", "", self.text)
    self.text = "\\N".join([t if has_cjk(t) and not has_jp(t) else second_style + t for t in [EFFECT + t for t in self.text.split("\\N")]])
    self.style = "Default"
    return self

  def __str__(self):
    return f"Dialogue: {self.layer},{self.start},{self.end},{self.style},{self.actor},{self.marginl},{self.marginr},{self.marginv},{self.effect},{self.text}"


@dataclass
class ASS:
  styles: List[str] = field(default_factory=list)
  events: List[ASSEvent] = field(default_factory=list)

  def __init__(self, styles, events):
    self.styles = styles
    self.events = events

  @classmethod
  def load(cls, file: Path):
    if file.suffix == ".srt":
      return cls.from_SRT(file)
    return cls.from_ASS(file)

  @classmethod
  def from_ASS(cls, file: Path):
    content = read_file(file).splitlines()
    styles = [line for line in content if line.startswith("Style:")]
    events = [ASSEvent.from_string(line) for line in content if line.startswith("Dialogue:")]
    return cls(styles, events)

  @classmethod
  def from_SRT(cls, file: Path):
    def rm_style(line):
      line = re.sub(r"<([ubi])>", r"{\\\1}", line)
      return re.sub(r'<font\s+color="?(\w*?)"?>|</font>|</([ubi])>', "", line)

    def ftime(x):
      return x.replace(",", ".")[:-1]

    srt = SRT.load(file)
    events = [ASSEvent(start=ftime(x.begin), end=ftime(x.end), text=rm_style(x.content[0])) for x in srt.content]
    return cls([], events)

  def dump(self, file: Path):
    output = """[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"""
    output += "\n".join(map(str, self.styles))
    output += """\n[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text\n"""
    output += "\n".join(map(str, self.events))
    file.write_text(output, encoding="utf-8")

  def update(self):
    self.styles = [style for style in self.get_style().splitlines()]
    second_style = self.get_2nd_style() if len(self.styles) > 1 else ""
    self.events = [e.update_style(second_style) for e in self.events if len(e.text) < 200]
    return self

  def _all_text(self) -> str:
    return "".join([event.text for event in self.events])

  def _all_2nd_text(self) -> str:
    RE = re.compile(r"\{.*\}|[\W\s]")
    lines = [RE.sub("", x[-1]) for e in self.events if len(x := e.text.split("\\N", 1)) > 1]
    return "".join(lines)

  def get_style(self):
    return STYLE_EN if is_eng_only(self._all_text()) else STYLE_DEFAULT

  def get_2nd_style(self):
    if has_jp(txt := self._all_2nd_text()):
      return STYLE_2_JP
    elif len(re.sub(r"[a-zA-Z]", "", txt)) / (len(txt) + 1) < 0.1:
      return STYLE_2_EN
    else:
      return ""


class SubtitleProcessor:
  def __init__(self, force: bool = False):
    self.force = force
    self.executor = ThreadPoolExecutor(max_workers=None)

  def merge_SRTs(self, files: List[Path]):
    def merge(file1: Path, file2: Path):
      if file1.suffixes[:-1] in done_list or file2.suffixes[:-1] in done_list:
        return
      if len([x for x in file1.suffixes[:-1] if x in file2.suffixes[:-1]]):
        return
      new_file = file1.with_suffix("".join(file2.suffixes[:]))
      if is_exist(new_file, self.force):
        return
      done_list.append([*file1.suffixes[:-1], *file2.suffixes[:-1]])
      logger.info(f"merging:\n{file1.name}\n&\n{file2.name}")
      SRT.load(file1).merge_with(SRT.load(file2)).dump(new_file)
      self.SRT_to_ASS(new_file)

    def stem(file: Path):
      return str(file).split(".")[0]

    for _, g in groupby(sorted(files, key=stem), key=stem):
      group = list(g)
      done_list = [suffix for f in group if len(suffix := f.suffixes[:-1]) > 2]
      fs = [self.executor.submit(merge, *tup) for tup in combinations(group, 2)]
      for future in as_completed(fs):
        future.result()

  def SRT_to_ASS(self, file: Path) -> None:
    if not is_exist(new_file := file.with_suffix(".ass"), self.force):
      logger.info(f"Convert to ASS: {file.stem}\n")
      try:
        ASS.load(file).update().dump(new_file)
      except Exception as e:
        logger.warning(e)
        logger.error(f"FAILED Convert to ASS: {file.stem}\n")

  def update_ASS_style(self, file: Path) -> None:
    logger.info(f"Updating style: {file.name}")
    ASS.load(file).update().dump(file)

  def extract_subs(self, files: List[Path]) -> None:
    SubInfo = namedtuple("SubInfo", ["index", "codec", "lang"])
    out_subs = []

    def extract(file: Path, sub: SubInfo, ext: str) -> Path:
      if is_exist(
        out_sub := file.with_suffix(f".track{sub.index}.{sub.lang}.{ext}"),
        self.force,
      ):
        return None
      cmd = [
        "ffmpeg -an -vn -y -i",
        str(file),
        f"-map 0:{sub.index}",
        str(out_sub),
      ]
      sp.run(cmd, stderr=sp.DEVNULL, stdout=sp.DEVNULL, stdin=sp.DEVNULL)
      out_subs.append(out_sub)
      return out_sub

    for file in tqdm(files, position=0):
      fs = []
      logger.info(f"extracting: {file.name}")
      probe_cmd = [
        "ffprobe",
        str(file),
        "-select_streams s",
        "-show_entries stream=index:stream_tags=language:stream=codec_name",
        "-v quiet",
        "-of csv=p=0",
      ]
      probe = sp.check_output(probe_cmd, stdin=sp.DEVNULL).decode("utf-8").splitlines()
      logger.debug(probe)

      subs = [SubInfo(*x.split(",")) for x in probe if len(x.split(",")) == 3]

      for sub in [x for x in subs if x.lang in LIST_LANG]:
        if sub.codec == "ass":
          if out_sub := extract(file, sub, "ass"):
            fs.append(self.executor.submit(self.update_ASS_style, out_sub))
        elif sub.codec in ["subrip", "mov_text"]:
          if out_sub := extract(file, sub, "srt"):
            fs.append(self.executor.submit(self.SRT_to_ASS, out_sub))
      for future in as_completed(fs):
        future.result()
      self.merge_SRTs(out_subs)


def main():
  parser = argparse.ArgumentParser(description="Subtitle Processing Tool")
  parser.add_argument("file", nargs="*", default=".", help="files or directories to process")
  parser.add_argument("-r", "--recurse", action="store_true", help="process all .srt/.ass recursively")
  parser.add_argument(
    "-f",
    "--force",
    action="store_true",
    help="force operation and overwrite existing files",
  )
  parser.add_argument("-v", "--verbose", action="store_true", help="show debug information")
  parser.add_argument("-q", "--quiet", action="store_true", help="show less information")

  group = parser.add_mutually_exclusive_group()
  group.add_argument("-u", "--update-ass", action="store_true", help="update .ass style")
  group.add_argument("-m", "--merge-srt", action="store_true", help="merge srts")
  group.add_argument("-e", "--extract-sub", action="store_true", help="extract subtitles from .mkv")

  args = parser.parse_args()

  # Setup logging
  log_level = logging.INFO
  if args.verbose:
    log_level = logging.DEBUG
  elif args.quiet:
    log_level = logging.ERROR

  ch = logging.StreamHandler()
  ch.setLevel(log_level)
  ch.setFormatter(CustomFormatter())
  logger.addHandler(ch)

  # Get files
  def get_files(paths, pattern):
    return [x for p in paths for x in Path(p).rglob(pattern) if x.is_file()]

  paths = [Path(x).resolve() for x in args.file]
  if args.recurse:
    paths = get_files(paths, "*")

  if args.update_ass:
    files = get_files(paths, "*.ass")
  elif args.extract_sub:
    files = get_files(paths, "*.mkv") + get_files(paths, "*.mp4")
  else:
    files = get_files(paths, "*.srt")

  files = list(set(files + [p for p in paths if p.is_file()]))
  logger.info(f"Found {len(files)} files")

  processor = SubtitleProcessor(force=args.force)
  if args.update_ass:
    list(
      tqdm(
        processor.executor.map(processor.update_ASS_style, files),
        total=len(files),
      )
    )
  elif args.extract_sub:
    processor.extract_subs(files)
  elif args.merge_srt:
    processor.merge_SRTs(files)
  else:
    list(tqdm(processor.executor.map(processor.SRT_to_ASS, files), total=len(files)))


if __name__ == "__main__":
  main()
