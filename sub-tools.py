# -*- coding: utf-8 -*-
import argparse
import json
import logging
import re
import subprocess as sp
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
import itertools
from pathlib import Path

import chardet

# STYLE_DEFAULT = """Style: Default,思源宋体 Heavy,28,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0.1,0,1,1,3,2,30,30,15,1
STYLE_DEFAULT = """Style: Default,GenYoMin TW H,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0.1,0,1,1,3,2,30,30,15,1
Style: ENG,GenYoMin TW B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JPN,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,2,2,30,30,10,1"""
STYLE_2_EN = "{\\rENG}"
STYLE_2_JP = "{\\rJPN}"
STYLE_EN = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
STYLE_JP = "Style: Default,GenYoMin JP H,23,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,30,30,10,1"
ARGS = ""
LIST_LANG = ["eng", "zho", "chi", "jpn"]  # LIST_LANG  需要提取的字幕语言的ISO639代码列表
EFFECT = "{\\blur3}"
logger = logging.getLogger("sub_tools")
executor = ThreadPoolExecutor(max_workers=32)


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
    def fromFile(cls, file, escape=" "):
        def time(rawtime):
            hour, minute, second, millisecond = map(int, re.split(r"[:,]", rawtime))
            return millisecond + 1000 * (second + (60 * (minute + 60 * hour)))

        def process(line):
            begin, end = line[0].strip().split(" --> ")
            return cls.sub(begin, end, [escape.join(line[1:])], time(begin), time(end))

        regex = re.compile(r"\r?\n\r?\n\d+\r?\n")
        return cls([process(x.splitlines()) for x in regex.split(read_file(file)[2:])])

    def merge_with(self, srt, time_shift=1000):
        def time_merge(content1, content2):
            merged_content = []
            merged_caption = None
            while content1 and content2:
                if (
                    abs(content1[0].beginTime - content2[0].beginTime) <= time_shift
                    or abs(content1[0].endTime - content2[0].endTime) <= time_shift
                ):
                    merged_caption = content1[0]._replace(
                        content=content1[0].content + content2.pop(0).content
                    )
                    continue
                if merged_caption:
                    merged_content.append(merged_caption)
                    merged_caption = None
                if content1[0].beginTime < content2[0].beginTime:
                    content1.pop(0)
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
        logger.debug(f"Merge {len(content1)} lines with {len(content2)} lines")
        return SRT(time_merge(content1, content2))

    def save_as(self, file: Path):
        output = ""
        for index, line in enumerate(self.content, start=1):
            c = "\n".join(line.content)
            output += f"{index}\n{line.begin} --> {line.end}\n{c}\n\n"
        file.write_text(output, encoding="utf-8")


class ASS:
    RE_ENG = re.compile(r"[\W\sA-Za-z0-9_\u00A0-\u03FF]+")

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
            l = re.sub(r"</([ubi])>", r"{\\\1}", l)
            l = re.sub(r'<font\s+color="?(\w*?)"?>|</font>', "", l)
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
        output += "\n".join([str(style) for style in self.styles])
        output += """\n[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text\n"""
        output += "\n".join([str(event) for event in self.events])
        file.write_text(output, encoding="utf-8")

    def update(self):
        self.styles = [self.Style(style) for style in self.get_style().splitlines()]
        second_style = self.get_2nd_style() if len(self.styles) > 1 else ""
        [event.update_style(second_style) for event in self.events]
        return self

    def is_eng_only(self, text):
        return self.RE_ENG.fullmatch(text) != None

    def text(self):
        return "".join([event.text for event in self.events])

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
            self.line = line
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
        return (
            STYLE_EN
            if self.is_eng_only(text := self.text())
            else STYLE_JP
            if self.Event.has_jap(text)
            else STYLE_DEFAULT
        )

    def get_2nd_style(self):
        return (
            STYLE_2_JP
            if self.Event.has_jap(re.sub(r"[\u4e00-\u9fa5]", "", txt := self.text()))
            else STYLE_2_EN
            if len(self.RE_ENG.sub("", self.text()).strip()) / len(txt) < 0.5
            else ""
        )


def is_exist(file: Path) -> bool:
    return (
        not ARGS.force or logger.warning(f"{file} exist") if file.is_file() else False
    )


def read_file(file: Path) -> str:
    return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])


def merge_SRTs(files: list[Path]):
    stem = lambda file: file.with_suffix("").with_suffix("").with_suffix("")

    def merge(file1: Path, file2: Path):
        if len(file2.suffixes) >= 3 and file1.suffixes[-2] == file2.suffixes[-2]:
            return
        if is_exist(new_file := file1.with_suffix("".join(file2.suffixes[-3:]))):
            return
        logger.info(f"merging:\n{file1.name}\n&\n{file2.name}\nas\n{new_file.name}")
        SRT.fromFile(file1).merge_with(SRT.fromFile(file2)).save_as(new_file)
        SRT_to_ASS(new_file)

    [
        merge(*tup)
        # executor.submit(merge, *tup)
        for x, group in itertools.groupby(files, key=stem)
        for tup in itertools.combinations(list(group), 2)
    ]


def SRT_to_ASS(file: Path):
    if is_exist(new_file := file.with_suffix(".ass")):
        return
    logger.info(f"Convert to ASS: {file.stem}\n")
    ASS.from_SRT(file).update().save(new_file)


def update_ASS_style(file: Path):
    logger.info(f"Updating style: {file.name}")
    ASS.from_ASS(file).update().save(file)


def extract_subs_MKV(files: list[Path]):
    SubInfo = namedtuple("SubInfo", ["index", "codec", "lang"])
    get_new_name = lambda file, sub, ext: file.with_suffix(
        f".track{sub.index}.{sub.lang}.{ext}"
    )
    for file in files:
        logger.info(f"extracting: {file.name}")
        subs = [
            SubInfo(int(sub["index"]), sub["codec_name"], sub["tags"].get("language"))
            for sub in json.loads(
                sp.check_output(
                    f'ffprobe "{file}" -hide_banner -select_streams s -show_entries stream=index:stream_tags=language:stream=codec_name -v quiet -print_format json'
                ).decode("utf-8")
            ).get("streams")
        ]

        logger.debug(subs)
        sp_run_quiet = lambda cmd: sp.run(cmd, stderr=sp.DEVNULL, stdout=sp.DEVNULL)
        for sub in [x for x in subs if "ass" in x.codec]:
            if is_exist(sub_file := get_new_name(file, sub, "ass")):
                continue
            sp_run_quiet(f'ffmpeg -y -i "{file}" -map 0:{sub.index} "{sub_file}"')
            executor.submit(update_ASS_style, sub_file)
        for sub in [x for x in subs if "subrip" in x.codec and x.lang in LIST_LANG]:
            if is_exist(sub_file := get_new_name(file, sub, "srt")):
                continue
            sp_run_quiet(f'ffmpeg -y -i "{file}" -map 0:{sub.index} "{sub_file}"')
            executor.submit(SRT_to_ASS, sub_file)
        executor.submit(merge_SRTs, file.rglob(f"{file.stem}*.srt"))


def main():
    def load_args():
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "file",
            help="files, default all files in current folder",
            nargs="*",
            default=".",
        )
        parser.add_argument(
            "-r",
            "--recurse",
            help="process all .srt/.ass",
            action="store_true",
        )
        parser.add_argument(
            "-f",
            "--force",
            help="force operation and overwrite existing files",
            action="store_true",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            help="show debug information",
            action="store_true",
        )
        parser.add_argument(
            "-q",
            "--quite",
            help="show less information",
            action="store_true",
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

    def init_logger():
        logger.setLevel(logging.INFO)
        if ARGS.verbose:
            logger.setLevel(logging.DEBUG)
        if ARGS.quite:
            logger.setLevel(logging.ERROR)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(CustomFormatter())
        logger.addHandler(ch)

    def get_files():
        glob = lambda paths, pattern: sum([list(p.glob(pattern)) for p in paths], [])
        paths = [Path(x).resolve() for x in ARGS.file]
        if ARGS.recurse:
            paths += glob(paths, "**")
        if ARGS.update_ass:
            paths += glob(paths, "*.ass")
        elif ARGS.extract_sub:
            paths += [
                x for x in glob(paths, "*.mkv") if not list(x.glob(f"{x.stem}*.ass"))
            ]
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
