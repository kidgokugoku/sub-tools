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

STR_2ND_EN_STYLE = "{\\rEN\\blur3}"
STR_2ND_JP_STYLE = "{\\rJP\\blur3}"


STR_CN_STYLE = "Style: Default,GenYoMin TW B,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0,0,1,1,3,2,30,30,10,1"
STR_EN_STYLE = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,30,30,20,1"
STR_JP_STYLE = "Style: Default,GenYoMin JP B,23,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,30,30,10,1"
"""STR_XX_STYLE .ass文件的XX语言配置

STR_DEFAULT_STYLE 是srt转换ass时的默认样式, 可以通过 Aegisub 自己调整合适后，用文本方式打开字幕复制粘贴过来。
STR_2ND_XX_STYLE  是作为副字幕时的样式
"""

ARGS = ""

INT_TIMESHIFT = 1000
# INT_TIMESHIFT 合并 srt 字幕时的时间偏移量,单位为ms
LIST_EXTRACT_LANGUAGE_ISO639 = [
    "en",
    "zh",
    "eng",
    "zho",
    "chi",
    "jpn",
]
# LIST_EXTRACT_LANGUAGE_ISO639  需要提取的字幕语言的ISO639代码列表

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


class MergeSRT:
    file1 = ""
    file2 = ""
    sub = namedtuple("sub", "begin, end, content,beginTime,endTime")
    subEx = namedtuple("sub", "begin, end, content")
    timeShift = INT_TIMESHIFT  # ms

    def __init__(self, file1, file2) -> None:
        self.file1 = file1
        self.file2 = file2

    def save(self, filename):
        content1 = []
        content = []
        cjk_character_percentage = 0
        inputfile = [self.file1, self.file2]
        logger.info(f"merging: \n{self.file1} \n& \n{self.file2}")
        for f in inputfile:
            line = []
            tmp = read_file(f).replace("\r", "")

            if not tmp:
                logger.error("%s is empty", Path(f).name)
                raise ValueError("empty file")
            # cjk字符检测，自动调整上下顺序
            stripedTMP = re.sub(r"[0123456789\->:\s,.，。\?]", "", tmp)
            cjk_character_percentage = (
                get_CJK_percentage(stripedTMP)
                if cjk_character_percentage == 0
                else get_CJK_percentage(stripedTMP) - cjk_character_percentage
            )
            logger.debug(f"cjk percentage in {f}: {cjk_character_percentage}")

            lines = [x.strip() for x in tmp.split("\n") if x.strip()]

            for l in lines:
                if re.sub(r"[0-9]+", "", l) == "":
                    if not len(line):
                        line = [l]
                    else:
                        content.append(self.__process(line))
                        line = [l]
                else:
                    if len(line):
                        line.append(l)
            content.append(self.__process(line))
            if not len(content1):
                content1 = content
                content = []

        output = (
            self.__time_merge(content1, content)
            if cjk_character_percentage < 0
            else self.__time_merge(content, content1)
        )

        self.__save_merged_sub(output, filename)
        return

    def __save_merged_sub(self, raw, f):
        output = ""
        for index, line in enumerate(raw):
            output += f"{index + 1}\r\n"
            output += f"{line.begin} --> {line.end} \r\n"
            if type(line.content) == list:
                for c in line.content:
                    output += f"{c} \r\n"
            else:
                output += line.content
                output += "\r\n"
        Path(f).write_bytes(output.encode("utf-8"))
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
        lockType = index1 = index2 = 0
        capTime1 = capTime2 = 0
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


def get_CJK_percentage(str):
    return (
        sum(map(lambda c: "\u4e00" <= c <= "\u9fa5", str)) / len(str) if len(str) else 0
    )


def is_bilingual(str):
    return str.count("\n") * 0.6 < str.count("\\N") or 0.98 > (  # 字幕总行数的 60% 都有第二行
        get_CJK_percentage(
            re.sub(
                r"Dialogue:(.*?,.*?,.*?,)(.*),(.*,.*,.*,)|[0-9,.?:->\-!\s\'♪：]", "", str
            )
        )
        > 0.2  # 字幕内容 CJK字符比例大于 20%
        and get_CJK_percentage(
            re.sub(
                r"[a-zA-z]",  # 字幕内容除字母外 CJK字符比例大于 60%
                "",
                re.sub(
                    r"Dialogue:(.*?,.*?,.*?,)(.*),(.*,.*,.*,)|[0-9,.?:->\-!\s\'♪：]",
                    "",
                    str,
                ),
            )
        )
        > 0.6
    )


def get_style(str):
    return (
        STR_JP_STYLE
        if sum(map(lambda c: "\u3040" <= c <= "\u30ff", str))
        else STR_EN_STYLE
        if get_CJK_percentage(str) < 0.05
        else STR_DEFAULT_STYLE
    )


def get_2nd_style(str):
    return (
        STR_2ND_JP_STYLE
        if sum(map(lambda c: "\u3040" <= c <= "\u30ff", str))
        else STR_2ND_EN_STYLE
        if get_CJK_percentage(str) > 0.05
        else ""
    )


def read_file(file: Path):
    return file.read_text(encoding=chardet.detect(file.read_bytes())["encoding"])


def merge_SRTs(files: list[Path]):
    output_file_list = []
    file_groups = []
    file_group = []
    it = iter(files)
    last_file = ""
    while (file := next(it, None)) is not None:
        if not last_file:
            last_file = file
            file_group.append(file)
            continue
        if (
            file.name.rsplit("_", 2)[0] == last_file.name.rsplit("_", 2)[0]
            or file.stem == last_file.stem
        ):
            file_group.append(file)
        else:
            file_groups.append(file_group)
            last_file = file
            file_group.append(file)
    file_groups.append(file_group)
    logger.debug(file_groups)
    for g in file_groups:
        for file1, file2 in combinations(g, 2):
            if (
                "_" in file1
                and "_" in file2
                and file1.name.split("_")[-1] == file2.name.split("_")[-1]
            ):
                logger.debug(f"{file1} \n&\n {file2} are same language")
                continue
            # file_track2_chi_track1_eng.srt
            output_file = f'{file2.with_suffix("")}_{file1.split("_", 1)[-1]}'

            file = Path(output_file.split("_")[-1])
            if not (
                Path.is_file(file.with_suffix(".ass"))
                or Path.is_file(file.with_suffix(".srt"))
            ):
                output_file = file.with_suffix(".srt")

            if Path.is_file(output_file):
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
        if not ARGS.force:
            logger.info(f"{output_file} exist")
            return
        logger.info(f"{output_file} exist, overwriting")

    logger.info(f"srt2ass: {file.stem}\n")

    tmpText = read_file(file).replace("\r", "")

    second_style = get_2nd_style(tmpText)
    lines = [x.strip() for x in tmpText.split("\n") if x.strip()]
    logger.info(enumerate(lines))

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
            tmpLines += "{\\blur3}" + line
        else:
            if get_CJK_percentage(line) != 0:
                tmpLines += "\\N" + line
            else:
                tmpLines += "\\N" + second_style + line
        lineCount += 1
    subLines += "{\\blur3}" + tmpLines + "\r\n"
    # timestamp replace
    subLines = re.sub(r"\d*(\d:\d{2}:\d{2}),(\d{2})\d", r"\1.\2", subLines)
    subLines = re.sub(r"\s+-->\s+", ",", subLines)
    # replace style
    subLines = re.sub(r"<([ubi])>", "{\\\\\g<1>1}", subLines)
    subLines = re.sub(r"</([ubi])>", "{\\\\\g<1>0}", subLines)
    subLines = re.sub(r'<font\s+color="?(\w*?)"?>', "", subLines)
    subLines = re.sub(r"</font>", "", subLines)

    output_str = f"""[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{get_style(subLines)}
[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text
{subLines}"""

    output_file.write_bytes(output_str.encode("utf-8"))
    return


def batch_execute(func, files):
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(func, files, timeout=15)


def update_ASS_style(file: Path):
    logger.info(f"updateAssStyle: {file.name}\n")

    tmp = read_file(file)

    style = get_style(tmp)
    second_style = ""
    if is_bilingual(tmp):
        second_style = get_2nd_style(tmp)
        logger.debug(f"detected bilingual subtitiles: {file.name}\n")

    output_str = re.sub(
        r"\[Script Info\][\s\S]*?\[Events\]",
        f"""[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}
[Events]""",
        tmp,
        1,
    )
    output_str = re.sub(r",\{\\fn(.*?)\}", ",", output_str)
    output_str = re.sub(r"\{\\r\}", "", output_str)
    output_str = re.sub(r"\\N(\{.*?\})?", rf"\\N{second_style}", output_str)  # 英文行
    output_str = re.sub(
        r"Dialogue:(.*?,.*?,.*?,)(.*),([0-9]+,[0-9]+,[0-9]+,.*?,)",
        r"Dialogue:\1Default,,\3{\\blur3}",
        output_str,
    )  # 默认字体

    file.write_bytes(output_str.encode("utf-8"))
    return


def extract_subs_MKV(files: list[Path]):
    for file in files:
        output_file_list = []
        logger.info(f"extracting: {file.name}")
        mkv = MKVFile(file)
        tracks = [x for x in mkv.get_track() if x._track_type == "subtitles"]
        logger.debug(tracks)
        # 提取所有ass
        for track in tracks:
            if not "SubStationAlpha" in str(track._track_codec):
                continue
            dst_srt_path = file.replace(
                ".mkv", f"_track{str(track._track_id)}_{track._language}.ass"
            )
            if Path.is_file(dst_srt_path):
                if not ARGS.force:
                    continue
                logger.info(f"{dst_srt_path} exist, overwriting")
            logger.debug(f"MKVExtract:{track}")
            subprocess.run(
                f'mkvextract "{file}" tracks {track._track_id}:"{dst_srt_path}"\n'
            )
            update_ASS_style(dst_srt_path)
        # 提取指定語言srt
        track_cnt = 0
        for track in tracks:
            if not "SRT" in track._track_codec:
                continue
            if not (track._language in LIST_EXTRACT_LANGUAGE_ISO639):
                continue
            dst_srt_path = file.replace(
                ".mkv", f"_track{track._track_id}_{track._language}.srt"
            )
            logger.debug(f"MKVExtract:{track}")
            subprocess.run(
                f'mkvextract "{file}" tracks {track._track_id}:"{dst_srt_path}"\n'
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
            dirs = [x for x in arg.glob("**") if Path.is_dir(x)]
            file_list += dirs
        if ARGS.update_ass:
            file_list += arg.glob("*.ass")
        elif ARGS.extract_sub:
            file_list += arg.glob("*.mkv")
            file_list = [
                x for x in file_list if not Path.is_file(Path(x).with_suffix(".ass"))
            ]
        else:
            file_list += arg.glob("*.srt")

    file_list = [x for x in file_list if Path.is_file(x)]

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
