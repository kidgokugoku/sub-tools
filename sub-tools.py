from itertools import product
import argparse, re
from dataclasses import dataclass, field
from collections import defaultdict, namedtuple
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Dict, List
from tqdm import tqdm
from pathlib import Path
import subprocess as sp

import chardet

STYLE_DEFAULT = """Style: Default,源樣黑體月 B,22,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,90,100,0.1,0,1,1,3,2,30,30,15,1
Style: ENG,源樣黑體月 B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JPN,GenYoMin2 JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1"""
STYLE_2_EN = "{\\rENG}"
STYLE_2_JP = "{\\rJPN}"
STYLE_EN = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
EFFECT = "{\\blur3}"
EXTRACT_LIST = ["eng", "chi", "zho", "jpn"]  # "jpn", "spa"  # LIST_LANG  需要提取的字幕语言的ISO639代码列表
MERGE_LIST = list(product(["chi", "zho"], ["eng", "jpn"]))


# fmt:off
def read_file(file: Path) -> str: return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])
def isCJK(x: str) -> bool: return "\u4e00" <= x <= "\u9fff"
def has_jp(text: str) -> bool: return any("\u3040" <= char <= "\u30f0" for char in text)
def has_cjk(text: str) -> bool: return any(isCJK(char) for char in text)
def is_eng_only(text: str) -> bool: return re.fullmatch("^[\\W\\sA-Za-z0-9_\\u00A0-\\u03FF]+$", text) is not None
def is_exist(f: Path, force: bool = False) -> bool: return print(f"{f} exist") or not force if f.is_file() else False

@dataclass
class SubtitleLine:
  begin: str
  end: str
  text: List[str]
  begin_ms: int
  end_ms: int

  @classmethod
  def from_srt(cls, begin: str, end: str, text: List[str]):
    def time_to_ms(time):
        hour, minute, second, millisecond = map(int, re.split(r"[:,]", time))
        return millisecond + 1000 * (second + (60 * (minute + 60 * hour)))
    return cls(begin, end, text, time_to_ms(begin), time_to_ms(end))
  def __str__(self): return "\n".join([f"{self.begin} --> {self.end}", *self.text, ""])

@dataclass
class SRT:
  content: List[SubtitleLine] = field(default_factory=list)

  @classmethod
  def load(cls, file: Path, escape="\\N"):
    content = []
    for chunk in re.split(r"\r?\n\r?\n\d+\r?\n", read_file(file)[2:]):
      time, *text = chunk.splitlines()
      content.append(SubtitleLine.from_srt(*time.strip().split(" --> "), [escape.join(text)]))
    return cls(content)

  def merge_with(self, srt: "SRT", shift: int = 1000) -> "SRT":
    def cjk_percentage(z):return sum(map(isCJK, "".join(sum([y.text for y in z],[])))) / (len("".join(sum([y.text for y in z],[]))) + 1)
    sub1, sub2 = self.content, srt.content
    if not cjk_percentage(sub1:=self.content) > cjk_percentage(sub2:=srt.content):
      sub1, sub2 = sub2, sub1
    merged_content = []
    while sub1 and sub2:
      if sub1[0].begin_ms - shift <= sub2[0].begin_ms and sub1[0].end_ms + shift >= sub2[0].end_ms:
        sub1[0].text=sub1[0].text + sub2.pop(0).text
      elif sub1[0].begin_ms < sub2[0].begin_ms: merged_content.append(sub1.pop(0))
      else: merged_content.append(sub2.pop(0)) # content1[0].begin_ms > content2[0].begin_ms
    merged_content.extend([*sub1, *sub2])
    return SRT(merged_content)

  def dump(self, file: Path): file.write_text("\n".join([f"{str(i)}\n{str(line)}" for i, line in enumerate(self.content, start=1)]), encoding="utf-8")


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
  def from_string(cls, s: str): return cls(*s.split(":", 1)[1].strip().split(",", 9))

  def update_style(self, style: str):
    self.text = re.sub(r"\{.*?\}|<.*?>", "", self.text)
    self.text = "\\N".join([t if has_cjk(t) and not has_jp(t) else style + t for t in [EFFECT + t for t in self.text.split("\\N")]])
    self.style = "Default"
    return self

  def __str__(self): return f"Dialogue: {','.join(map(str,self.__dict__.values()))}"


@dataclass
class ASS:
  styles: List[str] = field(default_factory=list)
  events: List[ASSEvent] = field(default_factory=list)

  @classmethod
  def load(cls, file: Path): return cls.from_SRT(file) if file.suffix == ".srt" else cls.from_ASS_file(file)

  @classmethod
  def from_ASS_file(cls, file: Path):
    styles, events = [], []
    for line in read_file(file).splitlines():
      if    line.startswith("Dialogue:"): events.append(ASSEvent.from_string(line))
      elif  line.startswith("Style:"):    styles.append(line)
    return cls(styles, events)

  @classmethod
  def from_SRT(cls, file):
    def rm_style(line): return re.sub(r'<font\s+color="?(\w*?)"?>|</font>|</([ubi])>', "", re.sub(r"<([ubi])>", r"{\\\1}", line))
    def ftime(x): return x.replace(",", ".")[:-1]
    srt = SRT.load(file) if isinstance(file, Path) else file
    return cls([], [ASSEvent(start=ftime(e.begin), end=ftime(e.end), text=rm_style("\\N".join(e.text))) for e in srt.content])

  def dump(self, file: Path):
    output = """[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"""  # noqa: E501
    output += "\n".join(map(str, self.styles))
    output += """\n[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text\n"""
    output += "\n".join(map(str, self.events))
    file.write_text(output, encoding="utf-8")

  def update(self):
    self.styles = list(self.get_style().splitlines())
    second_style = self.get_2nd_style() if len(self.styles) > 1 else ""
    self.events = [e.update_style(second_style) for e in self.events if len(e.text) < 200]
    return self

  def _text(self) -> str: return "".join([event.text for event in self.events])
  def _2nd_text(self) -> str: return "".join([re.sub(r"\{.*\}|[\W\s]", "", x[-1]) for e in self.events if len(x := e.text.split("\\N", 1)) > 1])
  def get_style(self): return STYLE_EN if is_eng_only(self._text()) else STYLE_DEFAULT
  def get_2nd_style(self)->str: return STYLE_2_JP if has_jp(txt:=self._2nd_text()) else STYLE_2_EN if len(re.sub(r"[A-z]","",txt))/(len(txt)+1) < 0.1 else ""

class SubtitleProcessor:
  def __init__(self, force: bool = False): self.force, self.executor = force, ThreadPoolExecutor(max_workers=None)

  def merge_SRTs (self, f1: Path, f2: Path):
      if is_exist(new_file:=f1.with_name(f1.stem+'_'+f2.stem.split("__")[-1]+'.ass'), self.force): return
      print(f"merging:{ f1.name }& {f2.name} as {new_file.name}")
      ASS.from_SRT(SRT.load(f1).merge_with(SRT.load(f2))).update().dump(new_file)

  def merge_SRTs_by_dict(self, file_dict: Dict[str,List[Path]]):
    lang_pairs = [(f1, f2) for lang, lang2 in MERGE_LIST for f1 in file_dict[lang] for f2 in file_dict[lang2]]
    [self.merge_SRTs(f1,f2) for f1, f2 in lang_pairs]
    # wait([self.executor.submit(self.merge_SRTs, f1, f2) for f1, f2 in lang_pairs])

  def SRT_to_ASS(self, file: Path) -> None:
    if is_exist(new_file := file.with_suffix(".ass"), self.force): return
    ASS.load(file).update().dump(new_file)

  def update_ASS_style(self, file: Path) -> None: print(f"Updating style: {file.name}") or ASS.load(file).update().dump(file)

  def extract_subs(self, files: List[Path]) -> None:
    SubInfo = namedtuple("SubInfo", ["index", "codec", "lang"])
    out_subs = defaultdict(list)

    def extract(file: Path, sub: SubInfo, ext: str) -> Path:
      if is_exist(out_sub := file.with_name(f"{file.stem}__track{sub.index}_{sub.lang}.{ext}"), self.force): return None
      sp.run(["ffmpeg","-an","-vn","-y","-i",str(file),"-map",f"0:{sub.index}", str(out_sub)], stderr=sp.DEVNULL, stdout=sp.DEVNULL, stdin=sp.DEVNULL)
      out_subs[sub.lang].append(out_sub)
      return out_sub

    for file in tqdm(files, position=0):
      out_subs=defaultdict(list)
      print(f"extracting: {file.name}")
      probe = sp.check_output(["ffprobe",str(file),"-select_streams","s","-show_entries","stream=index:stream_tags=language:stream=codec_name",
                               "-v","quiet","-of","csv=p=0"], stdin=sp.DEVNULL).decode("utf-8").splitlines()
      fs = []
      for sub in [x for x in [SubInfo(*x.split(",")) for x in probe if len(x.split(",")) == 3] if x.lang in EXTRACT_LIST]:
        if sub.codec == "ass" and (out_sub := extract(file, sub, "ass")): fs.append(self.executor.submit(self.update_ASS_style, out_sub))
        elif sub.codec in ["subrip", "mov_text"] and (out_sub := extract(file, sub, "srt")): fs.append(self.executor.submit(self.SRT_to_ASS, out_sub))
      wait(fs)
      print(out_subs.items())
      self.merge_SRTs_by_dict(out_subs)


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Subtitle Processing Tool")
  parser.add_argument("file", nargs="*", default=".", help="files or directories to process")
  parser.add_argument("-r", "--recurse", action="store_true", help="process all .srt/.ass recursively")
  parser.add_argument("-f", "--force", action="store_true", help="force operation and overwrite existing files")

  group = parser.add_mutually_exclusive_group()
  group.add_argument("-u", "--update-ass", action="store_true", help="update .ass style")
  group.add_argument("-m", "--merge-srt", action="store_true", help="merge srts")
  group.add_argument("-e", "--extract-sub", action="store_true", help="extract subtitles from .mkv")

  args = parser.parse_args()
  print(args )
  def glob(paths, pattern): return [x for p in paths for x in p.glob(pattern)]
  files = [Path(x).resolve() for x in args.file]
  if args.recurse: files += glob(files, "**")
  if args.update_ass: files += glob(files, "*.ass")
  elif args.extract_sub: files += glob(files, "*.mkv") + glob(files, "*.mp4")
  else: files += glob(files, "*.srt")
  files = [x for x in list(set(files)) if x.is_file()]
  print(f"found {len(files)} files")

  processor = SubtitleProcessor(force=args.force)
  if    args.update_ass:  list(tqdm(processor.executor.map(processor.update_ASS_style, files), total=len(files)))
  elif  args.extract_sub: processor.extract_subs(files)
  elif  args.merge_srt and len(files)==2: processor.merge_SRTs(*files)
  else: list(tqdm(processor.executor.map(processor.SRT_to_ASS, files), total=len(files)))

# fmt:on
