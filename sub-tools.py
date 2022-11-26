# -*- coding: utf-8 -*-
import argparse
import logging
import re
import subprocess
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

import chardet
from pymkv import MKVFile

# ASS/SSA style config

# Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
STR_DEFAULT_STYLE = """Style: Default,思源宋体 Heavy,28,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0.1,0,1,1,3,2,30,30,15,1
Style: EN,GenYoMin TW B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,30,30,10,1
Style: JP,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,2,2,30,30,10,1"""

STR_2ND_EN_STYLE = "{\\\\rEN\\\\blur3}"
STR_2ND_JP_STYLE = "{\\\\rJP\\\\blur3}"


STR_CN_STYLE = "Style: Default,GenYoMin TW B,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0,0,1,1,3,2,30,30,10,1"
STR_EN_STYLE = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
STR_JP_STYLE = "Style: Default,GenYoMin JP B,23,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,30,30,10,1"
"""STR_XX_STYLE .ass文件的XX语言配置

STR_DEFAULT_STYLE 是srt转换ass时的默认样式, 可以通过 Aegisub 自己调整合适后，用文本方式打开字幕复制粘贴过来。
STR_2ND_XX_STYLE  是作为副字幕时的样式
"""

ARGS = ""


LIST_EXTRACT_ISO639 = [
    "en",
    "zh",
    "eng",
    "zho",
    "chi",
    "jpn",
]
# LIST_EXTRACT_ISO639  需要提取的字幕语言的ISO639代码列表

logger = logging.getLogger("sub_tools")


class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    green = "\x1b[32m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(levelname)s - %(message)s \n(%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: green + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


INT_TIMESHIFT = 1000  # INT_TIMESHIFT 合并 srt 字幕时的时间偏移量,单位为ms


class MergeSRT:
    sub = namedtuple("sub", "begin, end, content,beginTime,endTime")
    subEx = namedtuple("sub", "begin, end, content")
    timeShift = INT_TIMESHIFT  # ms

    def __init__(self, file1, file2) -> None:
        self.file1 = file1
        self.file2 = file2

    def save(self, filename):
        content1 = []
        content = []
        cjk_percentage = 0
        logger.info(f"merging: \n{self.file1} \n& \n{self.file2}")
        for f in [self.file1, self.file2]:
            tmp = read_file(f).replace("\r", "")
            if not tmp:
                logger.error(f"{Path(f).name} is empty")
                raise ValueError("empty file")
            # cjk字符检测，自动调整上下顺序
            striped = re.sub(r"[0123456789\->:\s,.，。\?]", "", tmp)
            cjk_percentage = (
                self.get_CJK_percentage(striped)
                if not cjk_percentage
                else self.get_CJK_percentage(striped) - cjk_percentage
            )
            logger.debug(f"cjk percentage in {f}: {cjk_percentage}")
            line = []
            lines = [x.strip() for x in tmp.split("\n") if x.strip()]
            for l in lines:
                if re.sub(r"[0-9]+", "", l) == "":
                    if not len(line):
                        line = [l]
                    else:
                        content.append(self.__process(line))
                        line = [l]
                elif len(line):
                    line.append(l)
            content.append(self.__process(line))
            if not len(content1):
                content1, content = content, []
        output = (
            self.__time_merge(content1, content)
            if cjk_percentage < 0
            else self.__time_merge(content, content1)
        )
        self.__save_merged_sub(output, filename)
        return

    def get_CJK_percentage(self, str):
        return (
            sum(map(lambda c: "\u4e00" <= c <= "\u9fa5", str)) / len(str)
            if len(str)
            else 0
        )

    def __save_merged_sub(self, raw, file):
        output = ""
        for index, line in enumerate(raw):
            output += f"{index + 1}\r\n"
            output += f"{line.begin} --> {line.end} \r\n"
            c = "\r\n".join(line.content)
            output += f"{c} \r\n"
        Path(file).write_bytes(output.encode("utf-8"))
        return

    def __time(self, rawtime):
        (hour, minute, seconds) = rawtime.strip().split(":")
        (second, milisecond) = seconds.strip().split(",")
        return (
            int(milisecond)
            + 1000 * int(second)
            + 1000 * 60 * int(minute)
            + 1000 * 60 * 60 * int(hour)
        )

    def __process(self, line):
        try:
            (begin, end) = line[1].strip().split(" --> ")
        except:
            logger.error(f"spliting error:{line}")
            return
        content = [" ".join(line[2:])]
        beginTime = self.__time(begin)
        endTime = self.__time(end)
        return self.sub(begin, end, content, beginTime, endTime)

    def __time_merge(self, c1, c2):
        lockType = 0
        index1 = 0
        index2 = 0
        capTime1 = 0
        capTime2 = 0
        mergedContent = []
        while index1 < len(c1) or index2 < len(c2):
            captmp = ""
            if (not lockType == 1) and index1 < len(c1):
                capTime1 = c1[index1].beginTime
            if (not lockType == 2) and index2 < len(c2):
                capTime2 = c2[index2].beginTime
            lockType = 0
            if (
                capTime1 > capTime2
                and capTime1 > capTime2 + self.timeShift
                and index2 < len(c2)
                or index1 == len(c1)
            ):
                lockType = 1
            if (
                capTime2 > capTime1
                and capTime2 > capTime1 + self.timeShift
                and index1 < len(c1)
                or index2 == len(c2)
            ):
                lockType = 2

            if not lockType == 1:
                captmp = c1[index1]
                index1 += 1
                if lockType == 2:
                    mergedContent.append(captmp)

            if not lockType == 2:
                if captmp == "":
                    captmp = c2[index2]
                else:
                    captmp.content.append(c2[index2].content[0])
                mergedContent.append(captmp)
                index2 += 1
        return mergedContent


def init_logger():
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)


def read_file(file: Path):
    return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])


def merge_SRTs(files: list[Path]):
    output_file_list = []
    file_groups = []
    it = iter(files)
    last_file = Path(next(it, None))
    file_group = [last_file]
    while (file := next(it, None)) is not None:
        file = Path(file)
        if not (
            file.name.split("_", 1)[0] == last_file.name.split("_", 1)[0]
            or file.stem == last_file.stem
        ):
            file_groups.append(file_group)
            file_group.clear()
            last_file = file
        file_group.append(file)
    file_groups.append(file_group)
    logger.debug(file_groups)
    for g in file_groups:
        for file1, file2 in combinations(g, 2):
            if (
                "_" in str(file1)
                and "_" in str(file2)
                and file1.name.split("_")[-1] == file2.name.split("_")[-1]
            ):
                logger.debug(f"{file1} \n&\n {file2} are same language")
                continue
            # file_track2_chi_track1_eng.srt
            output_file = Path(
                f'{file2.with_suffix("")}_{file1.name.split("_", 1)[-1]}'
            )
            file = Path(str(output_file).split("_")[-1])
            if not (
                file.with_suffix(".ass").is_file() or file.with_suffix(".srt").is_file()
            ):
                output_file = file.with_suffix(".srt")

            if output_file.is_file():
                if not ARGS.force:
                    logger.info(f"{output_file} exist, skipping")
                    continue
                logger.info(f"{output_file} exist, overwriting")
            try:
                MergeSRT(file1, file2).save(output_file)
            except ValueError:
                logger.info(f"skipped {file.name}")
                continue
            output_file_list.append(output_file)

    batch_execute(SRT_to_ASS, output_file_list)


def SRT_to_ASS(file: Path):
    output_file = file.with_suffix(".ass")

    if output_file.is_file():
        logger.info(f"{output_file} exist")
        if not ARGS.force:
            return
    logger.info(f"srt2ass: {file.stem}\n")

    ASS.fromSRT(file).update_style().save(output_file)
    return


def update_ASS_style(file: Path):
    logger.info(f"updateAssStyle: {file.name}\n")
    ASS.fromASS(file).update_style().save(file)
    return


class ASS:
    def __init__(self, styles, events):
        self.styles = styles
        self.events = events

    @classmethod
    def fromASS(cls, file: Path):
        styles = []
        events = []
        for line in [x.strip() for x in file.read_text().split("\n") if x.strip()]:
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
        tmpText = read_file(file).replace("\r", "")
        lines = [x.strip() for x in tmpText.split("\n") if x.strip()]
        lineCount = 0
        subLines = ""
        tmpLines = ""
        for index, line in enumerate(lines):
            if line.isdigit() and re.match(r"-?\d+:\d\d:\d\d", lines[index + 1]):
                if tmpLines:
                    subLines += tmpLines + "\n"
                tmpLines = ""
                lineCount = 0
                continue
            elif re.match(r"-?\d+:\d\d:\d\d", line):
                line = line.replace("-0", "0")
                tmpLines += f"Dialogue: 0,{line},Default,,0,0,0,,"
            elif lineCount < 2:
                tmpLines += line
            else:
                tmpLines += "\\N" + line
            lineCount += 1
        subLines += tmpLines + "\n"
        # timestamp replace
        subLines = re.sub(r"\d*(\d:\d{2}:\d{2}),(\d{2})\d", r"\1.\2", subLines)
        subLines = re.sub(r"\s+-->\s+", ",", subLines)
        # replace style
        subLines = re.sub(r"<([ubi])>", "{\\\\\g<1>1}", subLines)
        subLines = re.sub(r"</([ubi])>", "{\\\\\g<1>0}", subLines)
        subLines = re.sub(r'<font\s+color="?(\w*?)"?>', "", subLines)
        subLines = re.sub(r"</font>", "", subLines)
        events = [cls.Event(x) for x in subLines.split("\n") if x.strip()]
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
        logger.debug(output_str)
        file.write_bytes(output_str.encode("utf-8"))

    def __str__(self):
        return f"{self.file} - {len(self.events)} events"

    def update_style(self):
        self.styles = [self.Style(x) for x in self.get_style().split("\n")]
        second_style = self.get_2nd_style()
        for event in self.events:
            logger.debug(f"event: {event}")
            event.update_style(second_style)
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

        def update_style(self, second_style: str):
            self.text = re.sub(r",\{\\fn(.*?)\}", ",", self.text)
            self.text = re.sub(r"\{\\r\}", "", self.text)
            self.text = self.text.replace("\\N", "\\N" + second_style)
            self.text = "{\\blur3}" + self.text
            return

        def __str__(self):
            return f"Dialogue: {self.layer},{self.start},{self.end},{self.style},{self.actor},{self.marginl},{self.marginr},{self.marginv},{self.effect},{self.text}"

    def get_style(self):
        return (
            STR_EN_STYLE
            if self.is_only_english(self.text())
            else STR_JP_STYLE
            if self.has_japanese(self.text())
            else STR_DEFAULT_STYLE
        )

    def get_2nd_style(self):
        return (
            STR_2ND_JP_STYLE
            if self.has_japanese(self.text())
            else ""
            if self.text().count("\n") * 0.9 < self.text().count("\\N")
            else STR_2ND_EN_STYLE
        )


def batch_execute(func, files):
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(func, files, timeout=15)


def extract_subs_MKV(files: list[Path]):
    for file in files:
        output_file_list = []
        logger.info(f"extracting: {file.name}")
        subs = [x for x in MKVFile(file).get_track() if x._track_type == "subtitles"]
        logger.debug(subs)
        for ASS_sub in [x for x in subs if "SubStationAlpha" in x._track_codec]:
            dst_srt_path = str(file).replace(
                ".mkv", f"_track{str(ASS_sub._track_id)}_{ASS_sub._language}.ass"
            )
            if dst_srt_path.is_file():
                if not ARGS.force:
                    continue
                logger.info(f"{dst_srt_path} exist, overwriting")
            logger.debug(f"MKVExtract:{ASS_sub}")
            subprocess.run(
                f'mkvextract "{file}" tracks {ASS_sub._track_id}:"{dst_srt_path}"\n'
            )
            update_ASS_style(dst_srt_path)
        track_cnt = 0
        for SRT_sub in [
            x
            for x in subs
            if "SRT" in x._track_codec and (x._language in LIST_EXTRACT_ISO639)
        ]:
            dst_srt_path = str(file).replace(
                ".mkv", f"_track{SRT_sub._track_id}_{SRT_sub._language}.srt"
            )
            logger.debug(f"MKVExtract:{SRT_sub}")
            subprocess.run(
                f'mkvextract "{file}" tracks {SRT_sub._track_id}:"{dst_srt_path}"\n'
            )
            track_cnt += 1
            output_file_list.append(dst_srt_path)
        if track_cnt == 1:
            SRT_to_ASS(dst_srt_path)
        merge_SRTs(output_file_list)


def load_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "file",
        help="srt file location, default all .srt files in current folder",
        nargs="*",
        default=".",
    )
    parser.add_argument(
        "-r",
        "--recursive",
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
        action="store_true",
        help="show debug info",
    )
    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "-u", "--update-ass", help="update .ass to custom style", action="store_true"
    )
    group.add_argument("-m", "--merge-srt", help="merge srts ", action="store_true")
    group.add_argument(
        "-e", "--extract-sub", help="extract subtitles from .mkv", action="store_true"
    )
    global ARGS
    ARGS = parser.parse_args()
    if ARGS.verbose:
        logger.setLevel(logging.DEBUG)
    logger.debug(ARGS)


def get_file_list():

    file_list = [Path(x).resolve() for x in ARGS.file]

    for arg in file_list:
        if ARGS.recursive and arg.is_dir():
            dirs = [x for x in arg.glob("**") if x.is_dir()]
            file_list += dirs
        if ARGS.update_ass:
            file_list += arg.glob("*.ass")
        elif ARGS.extract_sub:
            file_list += arg.glob("*.mkv")
            file_list = [x for x in file_list if not x.with_suffix(".ass").is_file()]
        else:
            file_list += arg.glob("*.srt")

    file_list = [x for x in file_list if x.is_file()]

    logger.debug(file_list)
    return file_list


def main():
    init_logger()
    load_args()
    files = get_file_list()

    if not files:
        logger.info("nothing found")
        return

    if ARGS.update_ass:
        batch_execute(update_ASS_style, files)
    elif ARGS.extract_sub:
        extract_subs_MKV(files)
    elif ARGS.merge_srt:
        merge_SRTs(files)
    else:
        batch_execute(SRT_to_ASS, files)
    return


if __name__ == "__main__":
    main()
