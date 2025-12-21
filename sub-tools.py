from collections import defaultdict, namedtuple
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from tqdm import tqdm
from typing import Dict, List
import argparse, re
import chardet
import ffmpeg

STYLE_DEFAULT = """Style: Default,源樣黑體月 B,22,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,90,100,0.1,0,1,1,3,2,30,30,15,1
Style: ENG,源樣黑體月 B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JPN,GenYoMin2 JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1"""
STYLE_2_EN = "{\\rENG}"
STYLE_2_JP = "{\\rJPN}"
STYLE_EN = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
EFFECT = "{\\blur3}"
EXTRACT_LIST = [
  "eng",
  "chi",
  "zho",
  # "jpn",
]  # "jpn", "spa"  # LIST_LANG  需要提取的字幕语言的ISO639代码列表
MERGE_LIST = list(
  product(
    ["chi", "zho"],
    [
      "eng",  # "jpn"
    ],
  )
)


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
  return print(f"{f} exist") or not force if f.is_file() else False


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

  def __str__(self):
    return "\n".join([f"{self.begin} --> {self.end}", *self.text, ""])


@dataclass
class SRT:
  content: List[SubtitleLine] = field(default_factory=list)

  @classmethod
  def load(cls, file: Path, escape="\\N"):
    content = []
    for chunk in re.split(r"\r?\n\r?\n\d+\r?\n", read_file(file)[2:]):
      time, *text = chunk.splitlines()
      content.append(
        SubtitleLine.from_srt(*time.strip().split(" --> "), [escape.join(text)])
      )
    return cls(content)

  def merge_with(self, srt: "SRT", shift: int = 1000) -> "SRT":
    def cjk_percentage(z):
      return sum(map(isCJK, "".join(sum([y.text for y in z], [])))) / (
        len("".join(sum([y.text for y in z], []))) + 1
      )

    sub1, sub2 = self.content, srt.content
    if not cjk_percentage(sub1 := self.content) > cjk_percentage(
      sub2 := srt.content
    ):
      sub1, sub2 = sub2, sub1
    merged_content = []
    while sub1 and sub2:
      if (
        sub1[0].begin_ms - shift <= sub2[0].begin_ms
        and sub1[0].end_ms + shift >= sub2[0].end_ms
      ):
        sub1[0].text = sub1[0].text + sub2.pop(0).text
      elif sub1[0].begin_ms < sub2[0].begin_ms:
        merged_content.append(sub1.pop(0))
      else:
        merged_content.append(
          sub2.pop(0)
        )  # content1[0].begin_ms > content2[0].begin_ms
    merged_content.extend([*sub1, *sub2])
    return SRT(merged_content)

  def dump(self, file: Path):
    file.write_text(
      "\n".join([
        f"{str(i)}\n{str(line)}" for i, line in enumerate(self.content, start=1)
      ]),
      encoding="utf-8",
    )


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
    return cls(*s.split(":", 1)[1].strip().split(",", 9))

  def update_style(self, style: str):
    self.text = re.sub(r"\{.*?\}|<.*?>", "", self.text)
    self.text = "\\N".join([
      t if has_cjk(t) and not has_jp(t) else style + t
      for t in [EFFECT + t for t in self.text.split("\\N")]
    ])
    self.style = "Default"
    return self

  def __str__(self):
    return f"Dialogue: {','.join(map(str, self.__dict__.values()))}"


@dataclass
class ASS:
  styles: List[str] = field(default_factory=list)
  events: List[ASSEvent] = field(default_factory=list)

  @classmethod
  def load(cls, file: Path):
    return (
      cls.from_SRT(file) if file.suffix == ".srt" else cls.from_ASS_file(file)
    )

  @classmethod
  def from_ASS_file(cls, file: Path):
    styles, events = [], []
    for line in read_file(file).splitlines():
      if line.startswith("Dialogue:"):
        events.append(ASSEvent.from_string(line))
      elif line.startswith("Style:"):
        styles.append(line)
    return cls(styles, events)

  @classmethod
  def from_SRT(cls, file):
    def rm_style(line):
      return re.sub(
        r'<font\s+color="?(\w*?)"?>|</font>|</([ubi])>',
        "",
        re.sub(r"<([ubi])>", r"{\\\1}", line),
      )

    def ftime(x):
      return x.replace(",", ".")[:-1]

    srt = SRT.load(file) if isinstance(file, Path) else file
    return cls(
      [],
      [
        ASSEvent(
          start=ftime(e.begin),
          end=ftime(e.end),
          text=rm_style("\\N".join(e.text)),
        )
        for e in srt.content
      ],
    )

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
    self.events = [
      e.update_style(second_style) for e in self.events if len(e.text) < 200
    ]
    return self

  def _text(self) -> str:
    return "".join([event.text for event in self.events])

  def _2nd_text(self) -> str:
    return "".join([
      re.sub(r"\{.*\}|[\W\s]", "", x[-1])
      for e in self.events
      if len(x := e.text.split("\\N", 1)) > 1
    ])

  def get_style(self):
    return STYLE_EN if is_eng_only(self._text()) else STYLE_DEFAULT

  def get_2nd_style(self) -> str:
    return (
      STYLE_2_JP
      if has_jp(txt := self._2nd_text())
      else STYLE_2_EN
      if len(re.sub(r"[A-z]", "", txt)) / (len(txt) + 1) < 0.1
      else ""
    )


def merge_SRTs(f1: Path, f2: Path, force: bool = False):
  if is_exist(
    new_file := f1.with_name(f1.stem + "_" + f2.stem.split("__")[-1] + ".ass"),
    force,
  ):
    return
  print(f"merging:{f1.name}& {f2.name} as {new_file.name}")
  ASS.from_SRT(SRT.load(f1).merge_with(SRT.load(f2))).update().dump(new_file)


def merge_SRTs_by_dict(file_dict: Dict[str, List[Path]], force: bool = False):
  lang_pairs = [
    (f1, f2)
    for lang, lang2 in MERGE_LIST
    for f1 in file_dict[lang]
    for f2 in file_dict[lang2]
  ]
  [merge_SRTs(f1, f2, force) for f1, f2 in lang_pairs]


def SRT_to_ASS(file: Path, force: bool = False) -> None:
  if is_exist(new_file := file.with_suffix(".ass"), force):
    return
  ASS.load(file).update().dump(new_file)


def update_ASS_style(file: Path, force: bool = False) -> None:
  print(f"Updating style: {file.name}") or ASS.load(file).update().dump(file)


def extract_subs(files: List[Path], force: bool = False) -> None:
  SubInfo = namedtuple("SubInfo", ["index", "codec", "lang"])
  executor = ThreadPoolExecutor(max_workers=None)

  def extract(file: Path, sub: SubInfo, ext: str) -> Path:
    if is_exist(
      out_sub := file.with_name(
        f"{file.stem}__track{sub.index}_{sub.lang}.{ext}"
      ),
      force,
    ):
      return None

    try:
      stream = ffmpeg.input(str(file))
      stream = ffmpeg.output(
        stream, str(out_sub), map=f"0:{sub.index}", c="copy"
      )
      ffmpeg.run(stream, overwrite_output=True, quiet=True)
    except ffmpeg.Error as e:
      print(f"Error extracting subtitle: {e.stderr.decode('utf8')}")
      return None

    return out_sub

  for file in tqdm(files, position=0):
    out_subs = defaultdict(list)
    print(f"extracting: {file.name}")

    try:
      probe = ffmpeg.probe(str(file), select_streams="s")
      streams = probe.get("streams", [])
    except ffmpeg.Error as e:
      print(f"Error probing file: {e.stderr.decode('utf8')}")
      continue

    fs = []
    for stream in streams:
      index = stream.get("index")
      codec = stream.get("codec_name")
      lang = stream.get("tags", {}).get("language", "")

      if lang in EXTRACT_LIST:
        sub = SubInfo(index, codec, lang)
        ext = (
          "ass"
          if codec == "ass"
          else "srt"
          if codec in ["subrip", "mov_text"]
          else None
        )

        if ext and (out_sub := extract(file, sub, ext)):
          out_subs[lang].append(out_sub)
          if codec == "ass":
            fs.append(executor.submit(update_ASS_style, out_sub, force))
          elif codec in ["subrip", "mov_text"]:
            fs.append(executor.submit(SRT_to_ASS, out_sub, force))

    wait(fs)
    print(out_subs.items())
    merge_SRTs_by_dict(out_subs, force)


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Subtitle Processing Tool")
  parser.add_argument(
    "file", nargs="*", default=".", help="files or directories to process"
  )
  parser.add_argument(
    "-r",
    "--recurse",
    action="store_true",
    help="process all .srt/.ass recursively",
  )
  parser.add_argument(
    "-f",
    "--force",
    action="store_true",
    help="force operation and overwrite existing files",
  )

  group = parser.add_mutually_exclusive_group()
  group.add_argument(
    "-u", "--update-ass", action="store_true", help="update .ass style"
  )
  group.add_argument(
    "-m", "--merge-srt", action="store_true", help="merge srts"
  )
  group.add_argument(
    "-e",
    "--extract-sub",
    action="store_true",
    help="extract subtitles from .mkv",
  )

  args = parser.parse_args()
  print(args)

  def glob(paths, pattern):
    return [x for p in paths for x in p.glob(pattern)]

  files = [Path(x).resolve() for x in args.file]
  if args.recurse:
    files += glob(files, "**")
  if args.update_ass:
    files += glob(files, "*.ass")
  elif args.extract_sub:
    files += glob(files, "*.mkv") + glob(files, "*.mp4")
  else:
    files += glob(files, "*.srt")
  files = [x for x in list(set(files)) if x.is_file()]
  print(f"found {len(files)} files")

  if args.update_ass:
    with ThreadPoolExecutor() as executor:
      list(
        tqdm(
          executor.map(lambda f: update_ASS_style(f, args.force), files),
          total=len(files),
        )
      )
  elif args.extract_sub:
    extract_subs(files, args.force)
  elif args.merge_srt and len(files) == 2:
    merge_SRTs(*files, args.force)
  else:
    with ThreadPoolExecutor() as executor:
      list(
        tqdm(
          executor.map(lambda f: SRT_to_ASS(f, args.force), files),
          total=len(files),
        )
      )
