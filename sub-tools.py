# -*- coding: utf-8 -*-
import argparse
import logging
import re
import subprocess as sp
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby, combinations
from pathlib import Path

import chardet

STYLE_DEFAULT = """Style: Default,GenYoMin TW H,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0.1,0,1,1,3,2,30,30,15,1
Style: ENG,GenYoMin TW B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JPN,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,2,2,30,30,10,1"""
STYLE_2_EN = "{\\rENG}"
STYLE_2_JP = "{\\rJPN}"
STYLE_EN = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
ARGS = ""
LIST_LANG = ["eng", "zho", "chi", "jpn"]  # LIST_LANG  需要提取的字幕语言的ISO639代码列表
EFFECT = "{\\blur3}"
logger = logging.getLogger("sub_tools")
executor = ThreadPoolExecutor()


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
    def fromFile(cls, file: Path, escape=" "):
        def time(rawtime):
            hour, minute, second, millisecond = map(int, re.split(r"[:,]", rawtime))
            return millisecond + 1000 * (second + (60 * (minute + 60 * hour)))

        def process(line: list[str]):
            begin, end = line[0].strip().split(" --> ")
            return SRT.sub(begin, end, [escape.join(line[1:])], time(begin), time(end))

        regex = re.compile(r"\r?\n\r?\n\d+\r?\n")
        return cls([process(x.splitlines()) for x in regex.split(read_file(file)[2:])])

    def merge_with(self, srt: Path, time_shift=1000):
        def time_merge(content1: list[SRT.sub], content2: list[SRT.sub]):
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

        isCJK = lambda x: "\u4e00" <= x <= "\u9fa5"
        all_text = lambda y: "".join([x.content[0] for x in y])
        cjk_percentage = lambda z: sum(map(isCJK, (t := all_text(z)))) / (len(t) + 1)
        content1, content2 = self.content, srt.content
        if cjk_percentage(content1) < cjk_percentage(content2):
            content1, content2 = content2, content1
        return SRT(time_merge(content1, content2))

    def save_as(self, file: Path):
        output = [
            "\n".join([i, f"{line.begin} --> {line.end}", *line.content, ""])
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
            l = re.sub(r'<font\s+color="?(\w*?)"?>|</font>|</([ubi])>', "", l)
            return l

        re_time = re.compile(r"\d*(\d:\d{2}:\d{2}),(\d{2})\d")
        ftime = lambda x: re_time.sub(r"\1.\2", x)
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
        [event.update_style(second_style) for event in self.events]
        return self

    def is_eng_only(self, text):
        re_eng = re.compile(r"^[\W\sA-Za-z0-9_\u00A0-\u03FF]+$")
        return re_eng.fullmatch(text) != None

    def _text(self):
        return "".join([event.text for event in self.events])

    def _text_2(self):
        lines = [x[-1] for e in self.events if len(x := e.text.split("\\N", 1)) > 1]
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
        def has_jap(x):
            return re.search(r"[\u3040-\u30f0]", x) != None

        @staticmethod
        def has_cjk(x):
            return re.search(r"[\u4e00-\u9fa5]", x) != None

        def update_style(self, second_style: str) -> None:
            self.text = re.sub(r"\{\\[(fn)rb](.*?)\}", "", self.text)
            self.text = self.text.replace("\\N", "\\N" + second_style + EFFECT)
            self.style = "Default"
            self.text = EFFECT + self.text
            if not self.has_cjk(self.text):
                self.text = second_style + self.text
            return

        def __str__(self):
            return f"Dialogue: {self.layer},{self.start},{self.end},{self.style},{self.actor},{self.marginl},{self.marginr},{self.marginv},{self.effect},{self.text}"

    def get_style(self):
        return STYLE_EN if self.is_eng_only(self._text()) else STYLE_DEFAULT

    def get_2nd_style(self):
        return (
            STYLE_2_JP
            if self.Event.has_jap(txt := self._text_2())
            else STYLE_2_EN
            if self.is_eng_only(txt)
            else ""
        )


def is_exist(f: Path) -> bool:
    return logger.warning(f"{f} exist") or not ARGS.force if f.is_file() else False


def read_file(file: Path) -> str:
    return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])


def merge_SRTs(files: list[Path]):
    stem = lambda file: file.with_suffix("").with_suffix("").with_suffix("")
    len_suffixes = lambda x: len(x.suffixes)

    def merge(file1: Path, file2: Path):
        if len(file2.suffixes) >= 3 and file1.suffixes[-2] == file2.suffixes[-2]:
            return
        if is_exist(new_file := file1.with_suffix("".join(file2.suffixes[-3:]))):
            return
        logger.info(f"merging:\n{file1.name}\n&\n{file2.name}\nas\n{new_file.name}")
        SRT.fromFile(file1).merge_with(SRT.fromFile(file2)).save_as(new_file)
        SRT_to_ASS(new_file)

    sorted_files = sorted([x for x in files if len(x.suffixes) < 5], key=len_suffixes)
    for x, group in groupby(sorted_files, key=stem):
        executor.map(merge, combinations(list(group), 2))


def SRT_to_ASS(file: Path) -> None:
    if not is_exist(new_file := file.with_suffix(".ass")):
        logger.info(f"Convert to ASS: {file.stem}\n")
        ASS.from_SRT(file).update().save(new_file)


def update_ASS_style(file: Path) -> None:
    logger.info(f"Updating style: {file.name}")
    ASS.from_ASS(file).update().save(file)


def extract_subs_MKV(files: list[Path]) -> None:
    SubInfo = namedtuple("SubInfo", ["index", "codec", "lang"])
    sp_run_quiet = lambda cmd: sp.run(cmd, stderr=sp.DEVNULL, stdout=sp.DEVNULL)

    def extract_fname(file: Path, sub: SubInfo, ext) -> Path:
        return file.with_suffix(f".track{sub.index}.{sub.lang}.{ext}")

    def extract(sub: SubInfo, ext) -> Path:
        if is_exist(out_sub := extract_fname(file, sub, ext)):
            return Path()
        sp_run_quiet(f'ffmpeg -y -i "{file}" -map 0:{sub.index} "{out_sub}" -an -vn')
        return out_sub

    for file in files:
        logger.info(f"extracting: {file.name}")
        probe_cmd = f'ffprobe "{file}" -select_streams s -show_entries stream=index:stream_tags=language:stream=codec_name -v quiet -print_format csv'
        probe = sp.check_output(probe_cmd).decode("utf-8").splitlines()
        subs = [SubInfo._make(sub.split(",")[1:]) for sub in probe]
        logger.debug(subs)
        for sub in subs:
            if "ass" in sub.codec:
                update_ASS_style(extract(sub, "ass"))
            elif "subrip" in sub.codec and sub.lang in LIST_LANG:
                SRT_to_ASS(extract(sub, "srt"))
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
        glob = lambda paths, pattern: sum([list(p.glob(pattern)) for p in paths], [])
        paths = [Path(x).resolve() for x in ARGS.file]
        if ARGS.recurse:
            paths += glob(paths, "**")
        if ARGS.update_ass:
            paths += glob(paths, "*.ass")
        elif ARGS.extract_sub:
            paths += glob(paths, "*.mkv")
        else:
            paths += glob(paths, "*.srt")
        paths = [x for x in paths if x.is_file()]
        logger.debug(paths)
        logger.info(f"found {len(paths)} files")
        return paths

    load_args()
    init_logger()
    files = get_files()
    if ARGS.update_ass:
        executor.map(update_ASS_style, files)
    elif ARGS.extract_sub:
        extract_subs_MKV(files)
    elif ARGS.merge_srt:
        merge_SRTs(files)
    else:
        executor.map(SRT_to_ASS, files)
    return


if __name__ == "__main__":
    main()
