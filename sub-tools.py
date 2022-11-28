# -*- coding: utf-8 -*-
import argparse
import json
import logging
import re
import subprocess as sp
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

import chardet

STR_DEFAULT_STYLE = """Style: Default,思源宋体 Heavy,28,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0.1,0,1,1,3,2,30,30,15,1
Style: ENG,GenYoMin TW B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JPN,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,2,2,30,30,10,1"""
STR_2ND_EN_STYLE = "{\\\\rENG\\\\blur3}"
STR_2ND_JP_STYLE = "{\\\\rJPN\\\\blur3}"
STR_EN_STYLE = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
STR_JP_STYLE = "Style: Default,GenYoMin JP B,23,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,30,30,10,1"

ARGS = ""

LIST_LANG = [
    "eng",
    "zho",
    "chi",
    "jpn",
]  # LIST_LANG  需要提取的字幕语言的ISO639代码列表

logger = logging.getLogger("sub_tools")
executor = ThreadPoolExecutor(max_workers=None)


class CustomFormatter(logging.Formatter):
    reset = "\x1b[0m"
    format = "%(asctime)s - %(levelname)s - %(message)s \n(%(filename)s:%(lineno)d)"
    FORMATS = {
        logging.DEBUG: (grey := "\x1b[38;20m") + format + reset,
        logging.INFO: (green := "\x1b[32m") + format + reset,
        logging.WARNING: (yellow := "\x1b[33;20m") + format + reset,
        logging.ERROR: (red := "\x1b[31;20m") + format + reset,
        logging.CRITICAL: (bold_red := "\x1b[31;1m") + format + reset,
    }

    def format(self, record):
        return logging.Formatter(self.FORMATS.get(record.levelno)).format(record)


INT_TIMESHIFT = 1000  # INT_TIMESHIFT 合并 srt 字幕时的时间偏移量,单位为ms


class MergeSRT:
    sub = namedtuple("sub", ["begin", "end", "content", "beginTime", "endTime"])
    timeShift = INT_TIMESHIFT  # ms

    def __init__(self, file1, file2) -> None:
        self.file1 = file1
        self.file2 = file2

    @classmethod
    def read_content(cls, f, escape=" "):
        CJK_percent = lambda x: sum(map(lambda c: "\u4e00" <= c <= "\u9fa5", x)) / (
            len(x) + 1
        )

        def time(rawtime):
            (hr, min, secs) = rawtime.strip().split(":")
            (sec, ms) = secs.strip().split(",")
            return int(ms) + 1000 * (int(sec) + (60 * (int(min) + 60 * int(hr))))

        def process(line):
            (begin, end) = line[0].strip().split(" --> ")
            return cls.sub(begin, end, [escape.join(line[1:])], time(begin), time(end))

        content = [
            process(x.split("\n"))
            for x in re.split(r"\r?\n\r?\n\d+\r?\n", read_file(f)[2:])
        ]
        return content, CJK_percent("".join([x.content[0] for x in content]))

    def save(self, filename):
        logger.info(f"merging: \n{self.file1} \n& \n{self.file2}")

        c1, cjk1 = self.read_content(self.file1)
        c2, cjk2 = self.read_content(self.file2)
        if cjk1 < cjk2:
            c1, c2 = c2, c1
        output = ""
        for index, line in enumerate(self.time_merge(c1, c2)):
            c = "\n".join(line.content)
            output += f"{index + 1}\n{line.begin} --> {line.end}\n{c}\n\n"
        Path(filename).write_bytes(output.encode("utf-8"))
        return

    def time_merge(self, c1, c2):
        lock_type = index1 = index2 = capTime1 = capTime2 = 0
        merged_content = []
        while index1 < len(c1) or index2 < len(c2):
            captmp = ""
            if (not lock_type == 1) and index1 < len(c1):
                capTime1 = c1[index1].beginTime
            if (not lock_type == 2) and index2 < len(c2):
                capTime2 = c2[index2].beginTime
            lock_type = 0
            if (
                capTime1 > capTime2
                and capTime1 > capTime2 + self.timeShift
                and index2 < len(c2)
                or index1 == len(c1)
            ):
                lock_type = 1
            if (
                capTime2 > capTime1
                and capTime2 > capTime1 + self.timeShift
                and index1 < len(c1)
                or index2 == len(c2)
            ):
                lock_type = 2

            if not lock_type == 1:
                captmp = c1[index1]
                index1 += 1
                if lock_type == 2:
                    merged_content.append(captmp)

            if not lock_type == 2:
                if captmp == "":
                    captmp = c2[index2]
                else:
                    captmp.content.append(c2[index2].content[0])
                merged_content.append(captmp)
                index2 += 1
        return merged_content


class ASS:
    def __init__(self, styles, events):
        self.styles = styles
        self.events = events

    @classmethod
    def fromASS(cls, file: Path):
        styles = []
        events = []
        section = ""
        for line in [y for x in read_file(file).split("\n") if (y := x.strip())]:
            if line.startswith("[V4+ Styles]"):
                section = "styles"
                continue
            if line.startswith("[Events]"):
                section = "events"
                continue
            if section == "styles":
                if line.startswith("Format:"):
                    continue
                if line.startswith("Style:"):
                    styles.append(cls.Style(line))
            if section == "events":
                if line.startswith("Format:"):
                    continue
                if line.startswith("Dialogue:"):
                    events.append(cls.Event(line))
        return cls(styles, events)

    @classmethod
    def fromSRT(cls, file: Path):
        def rm_style(l):
            l = re.sub(r"<([ubi])>", "{\\\\\g<1>1}", l)
            l = re.sub(r"</([ubi])>", "{\\\\\g<1>0}", l)
            l = re.sub(r'<font\s+color="?(\w*?)"?>|</font>', "", l)
            return l

        ftime = lambda x: re.sub(r"\d*(\d:\d{2}:\d{2}),(\d{2})\d", r"\1.\2", x)
        events = [
            cls.Event.fromSrt(ftime(x.begin), ftime(x.end), rm_style(x.content[0]))
            for x in MergeSRT.read_content(file, escape="\\N")[0]
        ]
        return cls([], events)

    def save(self, file: Path):
        output_str = "[Script Info]\n"
        output_str += "ScriptType: v4.00+\n"
        output_str += "[V4+ Styles]\n"
        output_str += "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        for style in self.styles:
            output_str += str(style) + "\n"
        output_str += "[Events]\n"
        output_str += "Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text\n"
        for event in self.events:
            output_str += str(event) + "\n"
        file.write_bytes(output_str.encode("utf-8"))

    def update_style(self):
        self.styles = [self.Style(x) for x in self.get_style().split("\n")]
        second_style = self.get_2nd_style()
        [e.update_style(second_style) for e in self.events]
        return self

    def has_japanese(self, string):
        return re.search(r"[\u3040-\u30ff]+", string)

    def is_only_english(self, string):
        try:
            string.encode(encoding="ascii")
        except UnicodeEncodeError:
            return False
        else:
            return True

    def text(self):
        res = ""
        for event in self.events:
            res += event.text + "\n"
        return res

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
            ) = line.split(":", 1)[1].split(",", 9)

        @classmethod
        def fromSrt(cls, start, end, text):
            return cls(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

        def update_style(self, second_style: str) -> None:
            self.text = re.sub(r",\{\\fn(.*?)\}", ",", self.text)
            self.text = re.sub(r"\{.*?\}", "", self.text)
            self.text = self.text.replace("\\N", "\\N" + second_style)
            self.text = (
                second_style + self.text
                if not re.search(r"[\u4e00-\u9fa5]+", self.text)
                else "{\\blur3}" + self.text
            )
            return

        def __str__(self):
            return f"Dialogue: {self.layer},{self.start},{self.end},{self.style},{self.actor},{self.marginl},{self.marginr},{self.marginv},{self.effect},{self.text}"

    def get_style(self):
        return (
            STR_EN_STYLE
            if self.is_only_english(text := self.text())
            else STR_JP_STYLE
            if self.has_japanese(text)
            else STR_DEFAULT_STYLE
        )

    def get_2nd_style(self):
        return (
            STR_2ND_JP_STYLE
            if self.has_japanese(txt := self.text())
            else ""
            if txt.count("\n") * 0.9 < txt.count("\\N")
            else STR_2ND_EN_STYLE
        )


def read_file(file: Path):
    return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])


def merge_SRTs(files: list[Path]):
    stem = lambda file: file.with_suffix("").with_suffix("").with_suffix("")

    def merge(f1: Path, f2: Path):
        if len(f2.suffixes) >= 3 and f1.suffixes[-2] == f2.suffixes[-2]:
            return
        output_file = f1.with_suffix("".join(f2.suffixes[-3:]))
        file = stem(f2)
        if not (
            file.with_suffix(".ass").is_file() or file.with_suffix(".srt").is_file()
        ):
            output_file = file.with_suffix(".srt")
        if output_file.is_file():
            logger.info(f"{output_file} exist")
            if not ARGS.force:
                return
        MergeSRT(f1, f2).save(output_file)
        SRT_to_ASS(output_file)

    [
        executor.submit(merge, tup[0], tup[1])
        for comb in [
            combinations(g, 2)
            for g in [
                [x for x in files if stem(x) == value]
                for value in set([stem(f) for f in files])
            ]
        ]
        for tup in comb
    ]


def SRT_to_ASS(file: Path):
    output_file = file.with_suffix(".ass")
    if output_file.is_file():
        logger.info(f"{output_file} exist")
        if not ARGS.force:
            return
    logger.info(f"srt2ass: {file.stem}\n")
    ASS.fromSRT(file).update_style().save(output_file)


def update_ASS_style(file: Path):
    logger.info(f"Updating style: {file.name}\n")
    ASS.fromASS(file).update_style().save(file)


def extract_subs_MKV(files: list[Path]):
    SubInfo = namedtuple("SubInfo", ["index", "codec", "lang"])
    dst = lambda file, sub, ext: file.with_suffix(f".track{sub.index}.{sub.lang}.{ext}")
    for file in files:
        logger.info(f"extracting: {file.name}")
        subs = [
            SubInfo(
                int(sub["index"]),
                sub["codec_name"],
                sub["tags"]["language"],
            )
            for sub in json.loads(
                sp.check_output(
                    f'ffprobe "{file}" -hide_banner -select_streams s -show_entries stream=index:stream_tags=language:stream=codec_name -v quiet -print_format json',
                ).decode("utf-8")
            )["streams"]
        ]
        logger.debug(subs)
        for sub in [x for x in subs if "ass" in x.codec]:
            dst_file = dst(file, sub, "ass")
            sp.run(f'ffmpeg -y -i "{file}" -map 0:{sub.index} "{dst_file}"')
            executor.submit(update_ASS_style, dst_file)
        for sub in [x for x in subs if "subrip" in x.codec and x.lang in LIST_LANG]:
            dst_file = dst(file, sub, "srt")
            sp.run(f'ffmpeg -y -i "{file}" -map 0:{sub.index} "{dst_file}"')
            executor.submit(SRT_to_ASS, dst_file)
        executor.submit(merge_SRTs, file.rglob(f"{file.stem}*.srt"))


def main():
    def init_logger():
        logger.setLevel(logging.INFO)
        if ARGS.verbose:
            logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(CustomFormatter())
        logger.addHandler(ch)

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

    def get_files():
        files = [Path(x).resolve() for x in ARGS.file]
        for file in files:
            if ARGS.recurse and file.is_dir():
                files += [x for x in file.glob("**") if x.is_dir() and x not in files]
            if ARGS.update_ass:
                files += file.glob("*.ass")
            elif ARGS.extract_sub:
                files += file.glob("*.mkv")
                files = [x for x in files if not x.with_suffix(".ass").is_file()]
            else:
                files += file.glob("*.srt")
        files = [x for x in files if x.is_file()]
        logger.debug(files)
        if not files:
            logger.info("nothing found")
            quit()
        return files

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
