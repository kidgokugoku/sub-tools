# -*- coding: utf-8 -*-
import argparse
import logging
import re
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from pathlib import Path

import chardet

STYLE_DEFAULT = """Style: Default,GenYoMin TW H,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,90,100,0.1,0,1,1,3,2,30,30,15,1
Style: ENG,GenYoMin TW B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JPN,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1"""
STYLE_2_EN = "{\\rENG}"
STYLE_2_JP = "{\\rJPN}"
STYLE_EN = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
ARGS = ""
LIST_LANG = ["eng", "chi", "zho"]  # "jpn", "spa"  # LIST_LANG  需要提取的字幕语言的ISO639代码列表
EFFECT = "{\\blur3}"
logger = logging.getLogger("sub_tools")
executor = ThreadPoolExecutor(max_workers=None)


class CustomFormatter(logging.Formatter):
    reset = "\x1b[0m"
    format = "%(levelname)s - %(message)s"
    debug_format = "%(thread)d - %(asctime)s - %(levelname)s - %(message)s \n(%(filename)s:%(lineno)d)"
    FORMATS = {
        logging.DEBUG: (grey := "\x1b[38;20m") + debug_format + reset,
        logging.INFO: (green := "\x1b[32m") + format + reset,
        logging.WARNING: (yellow := "\x1b[33;20m") + debug_format + reset,
        logging.ERROR: (red := "\x1b[31;20m") + debug_format + reset,
        logging.CRITICAL: (bold_red := "\x1b[31;1m") + format + reset,
    }

    def format(self, record):
        return logging.Formatter(self.FORMATS.get(record.levelno)).format(record)


class SRT:
    sub = namedtuple("sub", ["begin", "end", "content", "beginTime", "endTime"])

    def __init__(self, content) -> None:
        self.content = content

    @classmethod
    def fromFile(cls, file: Path, escape="\\N"):
        def time(rawtime: str) -> int:
            hour, minute, second, millisecond = map(int, re.split(r"[:,]", rawtime))
            return millisecond + 1000 * (second + (60 * (minute + 60 * hour)))

        def process(line: list[str]) -> SRT.sub:
            begin, end = line[0].strip().split(" --> ")
            return SRT.sub(begin, end, [escape.join(line[1:])], time(begin), time(end))

        RE = re.compile(r"\r?\n\r?\n\d+\r?\n")
        return cls([process(x.splitlines()) for x in RE.split(read_file(file)[2:])])

    def __time_merge(self, content1: list[sub], content2: list[sub], time_shift=1000):
        merged_content = []
        while content1 and content2:
            if (
                content1[0].beginTime - time_shift <= content2[0].beginTime
                and content1[0].endTime + time_shift >= content2[0].endTime
            ):
                content1[0] = content1[0]._replace(
                    content=content1[0].content + content2.pop(0).content
                )
                continue
            if content1[0].beginTime < content2[0].beginTime:
                merged_content.append(content1.pop(0))
            else:  # content1[0].beginTime > content2[0].beginTime
                merged_content.append(content2.pop(0))
        merged_content.extend([*content1, *content2])
        return merged_content

    def merge_with(self, srt):
        isCJK = lambda x: "\u4e00" <= x <= "\u9fa5"
        all_text = lambda c: "".join([x for y in c for x in y.content])
        cjk_percentage = lambda z: sum(map(isCJK, (t := all_text(z)))) / (len(t) + 1)
        content1, content2 = self.content, srt.content
        if cjk_percentage(content1) < cjk_percentage(content2):
            content1, content2 = content2, content1
        return SRT(self.__time_merge(content1, content2))

    def save_as(self, file: Path):
        output = [
            "\n".join([str(i), f"{line.begin} --> {line.end}", *line.content, ""])
            for i, line in enumerate(self.content, start=1)
        ]
        file.write_text("\n".join(output), encoding="utf-8")


class ASS:
    def __init__(self, styles, events):
        self.styles = styles
        self.events = events

    @classmethod
    def from_ASS(cls, file: Path):
        # styles = []
        events = []
        for line in [x for x in read_file(file).splitlines()]:
            # styles += [cls.Style(line)] if line.startswith("Style:") else []
            events += [cls.Event(line)] if line.startswith("Dialogue:") else []
        return cls([], events)

    @classmethod
    def from_SRT(cls, file: Path):
        def rm_style(l):
            l = re.sub(r"<([ubi])>", r"{\\\1}", l)
            return re.sub(r'<font\s+color="?(\w*?)"?>|</font>|</([ubi])>', "", l)

        ftime = lambda x: x.replace(",", ".")[:-1]
        events = [
            cls.Event.fromSrt(ftime(x.begin), ftime(x.end), rm_style(x.content[0]))
            for x in SRT.fromFile(file, escape="\\N").content
        ]
        return cls([], events)

    def save(self, file: Path):
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
        self.styles = [self.Style(style) for style in self.get_style().splitlines()]
        second_style = self.get_2nd_style() if len(self.styles) > 1 else ""
        self.events = [
            e.update_style(second_style) for e in self.events if len(e.text) < 200
        ]
        return self

    def is_eng_only(self, text: str) -> bool:
        return re.fullmatch(r"^[\W\sA-Za-z0-9_\u00A0-\u03FF]+$", text) != None

    def _text(self) -> str:
        return "".join([event.text for event in self.events])

    def _text_2(self) -> str:
        RE = re.compile(r"\{.*\}|[\W\s]")
        lines = [
            RE.sub("", x[-1])
            for e in self.events
            if len(x := e.text.split("\\N", 1)) > 1
        ]
        return "".join(lines)

    class Style:
        def __init__(self, line: str):
            (
                self.name,
                self.fontname,
                self.fontsize,
                self.primarycolour,
                self.secondarycolour,
                self.outlinecolour,
                self.backcolour,
                self.bold,
                self.italic,
                self.underline,
                self.strikeout,
                self.scalex,
                self.scaley,
                self.spacing,
                self.angle,
                self.borderstyle,
                self.outline,
                self.shadow,
                self.alignment,
                self.marginl,
                self.marginr,
                self.marginv,
                self.encoding,
            ) = line.split(":")[1].split(",")

        def __str__(self):
            return f"Style: {self.name},{self.fontname},{self.fontsize},{self.primarycolour},{self.secondarycolour},{self.outlinecolour},{self.backcolour},{self.bold},{self.italic},{self.underline},{self.strikeout},{self.scalex},{self.scaley},{self.spacing},{self.angle},{self.borderstyle},{self.outline},{self.shadow},{self.alignment},{self.marginl},{self.marginr},{self.marginv},{self.encoding}"

    class Event:
        def __init__(self, line: str):
            (
                self.layer,
                self.start,
                self.end,
                self.style,
                self.actor,
                self.marginl,
                self.marginr,
                self.marginv,
                self.effect,
                self.text,
            ) = (
                line.split(":", 1)[1].strip().split(",", 9)
            )

        @classmethod
        def fromSrt(cls, start_time, end_time, text):
            return cls(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}")

        @staticmethod
        def has_jap(x: str) -> bool:
            return re.search(r"[\u3040-\u30f0]", x) != None

        @staticmethod
        def has_cjk(x: str) -> bool:
            return re.search(r"[\u4e00-\u9fa5]", x) != None

        def update_style(self, second_style: str):
            self.text = re.sub(r"\{.*?\}|<.*?>", "", self.text)
            texts = [EFFECT + t for t in self.text.split("\\N")]
            self.text = "\\N".join(
                [
                    t if self.has_cjk(t) and not self.has_jap(t) else second_style + t
                    for t in texts
                ]
            )
            self.style = "Default"
            return self

        def __str__(self):
            return f"Dialogue: {self.layer},{self.start},{self.end},{self.style},{self.actor},{self.marginl},{self.marginr},{self.marginv},{self.effect},{self.text}"

    def get_style(self):
        return STYLE_EN if self.is_eng_only(self._text()) else STYLE_DEFAULT

    def get_2nd_style(self):
        if self.Event.has_jap(txt := self._text_2()):
            return STYLE_2_JP
        elif len(re.sub(r"[a-zA-Z]", "", txt)) / (len(txt) + 1) < 0.1:
            return STYLE_2_EN
        else:
            return ""


def is_exist(f: Path) -> bool:
    return logger.warning(f"{f} exist") or not ARGS.force if f.is_file() else False


def read_file(file: Path) -> str:
    return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])


def merge_SRTs(files: list[Path]):
    from itertools import groupby, combinations

    def merge(file1: Path, file2: Path):
        if file1.suffixes[:-1] in done_list or file2.suffixes[:-1] in done_list:
            return
        if len([x for x in file1.suffixes[:-1] if x in file2.suffixes[:-1]]):
            return
        if is_exist(new_file := file1.with_suffix("".join(file2.suffixes[:]))):
            return
        done_list.append(file1.suffixes[:-1])
        done_list.append(file2.suffixes[:-1])
        logger.info(f"merging:\n{file1.name}\n&\n{file2.name}")
        SRT.fromFile(file1).merge_with(SRT.fromFile(file2)).save_as(new_file)
        SRT_to_ASS(new_file)

    def stem(file):
        while file.with_suffix("") != file:
            file = file.with_suffix("")
        return file

    for _, g in groupby(sorted(files, key=stem), key=stem):
        group = list(g)
        done_list = [l for f in group if len(l := f.suffixes[:-1]) > 2]
        [logger.info(x) for x in group]
        [executor.submit(merge, *tup) for tup in combinations(group, 2)]


def SRT_to_ASS(file: Path) -> None:
    if not is_exist(new_file := file.with_suffix(".ass")):
        logger.info(f"Convert to ASS: {file.stem}\n")
        ASS.from_SRT(file).update().save(new_file)


def update_ASS_style(file: Path) -> None:
    logger.info(f"Updating style: {file.name}")
    ASS.from_ASS(file).update().save(file)


def extract_subs(files: list[Path]) -> None:
    import subprocess as sp

    SubInfo = namedtuple("SubInfo", ["index", "codec", "lang"])

    def extract(sub: SubInfo, ext) -> list[Path]:
        if is_exist(out_sub := file.with_suffix(f".track{sub.index}.{sub.lang}.{ext}")):
            return []
        cmd = [
            "ffmpeg",
            "-an",
            "-vn",
            "-y",
            "-i",
            file,
            "-map",
            f"0:{sub.index}",
            out_sub,
        ]
        sp.run(
            cmd,
            stderr=sp.DEVNULL,
            stdout=sp.DEVNULL,
            stdin=sp.DEVNULL,
        )
        return [out_sub]

    for file in tqdm(files, position=0):
        logger.info(f"extracting: {file.name}")
        probe_cmd = [
            "ffprobe",
            file,
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index:stream_tags=language:stream=codec_name",
            "-v",
            "quiet",
            "-of",
            "csv=p=0",
        ]
        probe = (
            sp.check_output(probe_cmd, stdin=sp.DEVNULL).decode("utf-8").splitlines()
        )
        logger.debug(probe)
        subs = [SubInfo._make(x) for sub in probe if len(x := sub.split(",")) == 3]
        for sub in [x for x in subs if x.lang in LIST_LANG]:
            if "ass" in sub.codec:
                executor.map(update_ASS_style, extract(sub, "ass"))
            elif sub.codec in ["subrip", "mov_text"]:
                executor.map(SRT_to_ASS, extract(sub, "srt"))
        merge_SRTs(list(file.rglob(f"{file.stem}*.srt")))


def main():
    def load_args() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "file",
            help="files, default all files in current folder",
            nargs="*",
            default=".",
        )
        parser.add_argument(
            "-r", "--recurse", help="process all .srt/.ass", action="store_true"
        )
        parser.add_argument(
            "-f",
            "--force",
            help="force operation and overwrite existing files",
            action="store_true",
        )
        parser.add_argument(
            "-v", "--verbose", help="show debug information", action="store_true"
        )
        parser.add_argument(
            "-q", "--quite", help="show less information", action="store_true"
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "-u", "--update-ass", help="update .ass style", action="store_true"
        )
        group.add_argument("-m", "--merge-srt", help="merge srts", action="store_true")
        group.add_argument(
            "-e",
            "--extract-sub",
            help="extract subtitles from .mkv",
            action="store_true",
        )
        global ARGS
        ARGS = parser.parse_args()
        logger.debug(ARGS)

    def init_logger() -> None:
        logger.setLevel(logging.INFO)
        if ARGS.verbose:
            logger.setLevel(logging.DEBUG)
        if ARGS.quite:
            logger.setLevel(logging.ERROR)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(CustomFormatter())
        logger.addHandler(ch)

    def get_files() -> list[Path]:
        glob = lambda paths, pattern: [x for p in paths for x in p.glob(pattern)]
        paths = [Path(x).resolve() for x in ARGS.file]
        if ARGS.recurse:
            paths += glob(paths, "**")
        if ARGS.update_ass:
            paths += glob(paths, "*.ass")
        elif ARGS.extract_sub:
            paths += glob(paths, "*.mkv") + glob(paths, "*.mp4")
        else:
            paths += glob(paths, "*.srt")
        paths = [x for x in list(set(paths)) if x.is_file()]
        logger.debug(paths)
        logger.info(f"found {len(paths)} files")
        return paths

    load_args()
    init_logger()
    files = get_files()
    if ARGS.update_ass:
        list(tqdm(executor.map(update_ASS_style, files), total=len(files)))
    elif ARGS.extract_sub:
        extract_subs(files)
    elif ARGS.merge_srt:
        merge_SRTs(files)
    else:
        list(tqdm(executor.map(SRT_to_ASS, files), total=len(files)))
    return


if __name__ == "__main__":
    main()
