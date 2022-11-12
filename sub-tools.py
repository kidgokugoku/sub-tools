# -*- coding: utf-8 -*-
import argparse
import logging
import os
import re
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from glob import glob
from itertools import combinations

import chardet
from pymkv import MKVFile

# ASS/SSA style config

# Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
STR_DEFAULT_STYLE = """Style: Default,思源宋体 Heavy,28,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0.1,0,1,1,3,2,10,10,15,1
Style: EN,GenYoMin TW B,11,&H003CA8DC,&H000000FF,&H00000000,&H00000000,1,0,0,0,90,100,0,0,1,1,2,2,10,10,10,1
Style: JP,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,2,2,10,10,10,1"""

STR_2ND_EN_STYLE = "{\\rEN\\blur3}"
STR_2ND_JP_STYLE = "{\\rJP\\blur3}"

STR_2ND_STYLE = STR_2ND_EN_STYLE

STR_CN_STYLE = "Style: Default,GenYoMin TW B,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0,0,1,1,3,2,10,10,10,1"
STR_EN_STYLE = "Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,10,10,20,1"
STR_JP_STYLE = "Style: Default,GenYoMin JP B,23,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,10,10,10,1"
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
    __encoding = ""

    def __init__(self, file1, file2) -> None:
        self.file1 = file1
        self.file2 = file2

    def save(self, outputfile):
        content1 = []
        content = []
        cjk_character_percentage = 0
        inputfile = [self.file1, self.file2]
        logger.info(f"merging: \n{self.file1} \n& \n{self.file2}")
        for f in inputfile:
            line = []

            src = open_file(f)
            tmp = src[0]
            if not tmp:
                logger.error("%s is empty", os.path.basename(f))
                raise ValueError("empty file")
            if not self.__encoding:
                self.__encoding = "utf-8"
            src = ""
            if "\ufeff" in tmp:
                tmp = tmp.replace("\ufeff", "")
                self.__encoding = "utf-8"
            # cjk字符检测，自动调整上下顺序
            stripedTMP = re.sub(r"[0123456789\->:\s,.，。\?]", "", tmp)
            cjk_character_percentage = (
                get_CJK_percentage(stripedTMP)
                if cjk_character_percentage == 0
                else get_CJK_percentage(stripedTMP) - cjk_character_percentage
            )
            logger.debug(f"cjk percentage in {f}: {cjk_character_percentage}")

            tmp = tmp.replace("\r", "")
            lines = [x.strip() for x in tmp.split("\n") if x.strip()]
            tmp = ""

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

        if cjk_character_percentage < 0:
            outputraw = self.__time_merge(content1, content)
            global STR_2ND_STYLE
            if cjk_character_percentage > -0.5:
                STR_2ND_STYLE = STR_2ND_JP_STYLE
        else:
            outputraw = self.__time_merge(content, content1)

        self.__save_merged_sub(outputraw, outputfile)
        return

    def __save_merged_sub(self, raw, f):
        # output = UTF8BOM
        output = ""
        for i in range(len(raw)):
            output += "%d\r\n" % (i + 1)
            output += "%s --> %s \r\n" % (raw[i].begin, raw[i].end)
            if type(raw[i].content) == list:
                for c in raw[i].content:
                    output += "%s" % c
                    output += "\r\n"
            else:
                output += "%s" % raw[i].content
                output += "\r\n"
        output = output.encode(self.__encoding)
        with open(f, "wb") as output_file:
            output_file.write(output)
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


def initLogger():
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
    return str.count("\n") * 0.6 < str.count("\\N") or (
        get_CJK_percentage(
            re.sub(
                r"Dialogue:(.*?,.*?,.*?,)(.*),(.*,.*,.*,)|[0-9,.?:->\-!\s\'♪：]", "", str
            )
        )
        > 0.2
        and get_CJK_percentage(
            re.sub(
                r"[a-zA-z]",
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


def open_file(file):
    with open(file, mode="rb") as f:
        enc = chardet.detect(f.read())["encoding"]
    tmp = ""
    with open(file, mode="r", encoding=enc, errors="ignore") as fd:
        tmp = fd.read()
    return [tmp, enc]


def merge_SRTs(input_filelist):
    output_filelist = []
    it = iter(input_filelist)
    file_groups = []
    file_group = []
    last = ""
    while (file := next(it, None)) is not None:
        if not last:
            last = file
            file_group = [file]
            continue
        if os.path.basename(file).split("_")[0] == os.path.basename(last).split("_")[0]:
            file_group.append(file)
        else:
            file_groups.append(file_group)
            last = file
            file_group = [file]
    file_groups.append(file_group)
    logger.debug(file_groups)
    for g in file_groups:
        for file1, file2 in combinations(g, 2):
            if (
                os.path.basename(file1).split("_")[-1]
                == os.path.basename(file2).split("_")[-1]
            ):
                continue
            # file_track1_eng.srt --> track1_eng.srt
            surfix = "_".join(file1.split("_")[1:])
            output_file = "_".join([file2.replace(".srt", ""), surfix]) + ".srt"

            output_file = (
                "_".join(output_file.split("_")[:-4]) + ".srt"
                if not os.path.isfile("_".join(output_file.split("_")[:-4]) + ".ass")
                else output_file
            )

            if os.path.isfile(output_file):
                if not ARGS.force:
                    logger.info(f"{output_file} exist, skipping")
                    continue
                logger.info(f"{output_file} exist, overwriting")

            try:
                MergeSRT(file1, file2).save(output_file)
            except ValueError:
                logger.info(f"skipped {os.path.basename(file)}")
                continue
            output_filelist.append(output_file)

    batch_execute(SRT_to_ASS, output_filelist)


def SRT_to_ASS(file):
    if not os.path.isfile(file):
        logger.error(f"{os.path.basename(file)} not found")
        return

    logger.info(f"srt2ass: {os.path.basename(file)}\n")

    src = open_file(file)
    tmpText = src[0]
    utf8bom = ""

    if "\ufeff" in tmpText:
        tmpText = tmpText.replace("\ufeff", "")
        utf8bom = "\ufeff"

    tmpText = tmpText.replace("\r", "")
    second_style = STR_2ND_STYLE if is_bilingual(tmpText) else ""
    lines = [x.strip() for x in tmpText.split("\n") if x.strip()]
    tmpText = ""
    lineCount = 0
    subLines = ""
    tmpLines = ""

    for index in range(len(lines)):
        line = lines[index]
        if line.isdigit() and re.match("-?\d+:\d\d:\d\d", lines[(index + 1)]):
            if tmpLines:
                subLines += tmpLines + "\n"
            tmpLines = ""
            lineCount = 0
            continue
        elif re.match("-?\d+:\d\d:\d\d", line):
            line = line.replace("-0", "0")
            tmpLines += f"Dialogue: 0,{line},Default,,0,0,0,,"
        elif lineCount < 2:
            tmpLines += line
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

    STR_STYLE = STR_EN_STYLE if ARGS.english else STR_DEFAULT_STYLE
    head_str = f"""[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{STR_STYLE}
[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text"""

    output_str = utf8bom + head_str + "\n" + subLines
    output_str = output_str.encode("utf-8")

    output_file = ".".join(file.split(".")[:-1]) + ".ass"

    if os.path.isfile(output_file):
        if not ARGS.force:
            logger.info(f"{output_file} exist")
            return
        logger.info(f"{output_file} exist, overwriting")

    with open(output_file, "wb") as output:
        output.write(output_str)
    return


def batch_execute(func, input_filelist):
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(func, input_filelist, timeout=15)


def update_ASS_style(file):
    if not os.path.isfile(file):
        logger.error(f"{os.path.basename(file)} not found")
        return

    logger.info(f"updateAssStyle: {os.path.basename(file)}\n")

    src = open_file(file)
    output_file = file
    tmp = src[0]
    encoding = src[1]

    STR_STYLE = STR_EN_STYLE if ARGS.english else STR_DEFAULT_STYLE
    SECOND_LANG_STYLE = STR_2ND_STYLE.replace("\\", "\\\\") if is_bilingual(tmp) else ""
    if SECOND_LANG_STYLE != "":
        logger.debug(f"detected bilingual subtitiles: {os.path.basename(file)}\n")
    output_str = re.sub(
        r"\[Script Info\][\s\S]*?\[Events\]",
        f"""[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{STR_STYLE}
[Events]""",
        tmp,
        1,
    )
    output_str = re.sub(r",\{\\fn(.*?)\}", ",", output_str)
    output_str = re.sub(r"\{\\r\}", "", output_str)
    output_str = re.sub(r"\\N(\{.*?\})?", rf"\\N{SECOND_LANG_STYLE}", output_str)  # 英文行
    output_str = re.sub(
        r"Dialogue:(.*?,.*?,.*?,)(.*),([0-9]+,[0-9]+,[0-9]+,.*?,)",
        r"Dialogue:\1Default,,\3{\\blur3}",
        output_str,
    )  # 默认字体

    output_str = output_str.encode(encoding)

    with open(output_file, "wb") as output:
        output.write(output_str)
    return


def extract_subs_MKV(input_filelist):
    for file in input_filelist:
        output_filelist = []
        logger.info(f"extracting: {os.path.basename(file)}")
        mkv = MKVFile(file)
        tracks = list(filter(lambda x: x._track_type == "subtitles", mkv.get_track()))
        logger.debug(tracks)
        # 提取所有ass
        for track in tracks:
            if not "SubStationAlpha" in str(track._track_codec):
                continue
            dst_srt_path = file.replace(
                ".mkv", f"_track{str(track._track_id)}_{track._language}.ass"
            )
            if os.path.isfile(dst_srt_path):
                if not ARGS.force:
                    continue
                logger.info(f"{dst_srt_path} exist, overwriting")
            logger.debug(f"MKVExtract:{track}")
            os.system(
                f'mkvextract "{os.path.basename(file)}" tracks {track._track_id}:"{dst_srt_path}"\n'
            )
            update_ASS_style(dst_srt_path)
            continue
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
            logger.debug(track)
            os.system(
                f'mkvextract "{os.path.basename(file)}" tracks {track._track_id}:"{dst_srt_path}"\n'
            )
            track_cnt += 1
            output_filelist.append(dst_srt_path)
        if track_cnt == 1:
            SRT_to_ASS(dst_srt_path)
        merge_SRTs(output_filelist)


def load_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "file",
        help="srt file location, default all .srt files in current folder",
        nargs="*",
        default=".",
    )
    parser.add_argument(
        "--english",
        "-en",
        help="handle file that contian only ENG subtitles",
        action="store_true",
    )
    parser.add_argument(
        "-d", "--delete", help="delete the original .srt file", action="store_true"
    )
    parser.add_argument(
        "-a",
        "--all-dir",
        help="process all .srt/.ass including all children dir",
        action="store_true",
    )
    parser.add_argument(
        "-f",
        "--force",
        help="force operation and overwrite existing files",
        action="store_true",
    )
    parser.add_argument("--debug", help="print debug level log", action="store_true")

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

    if ARGS.debug:
        logger.setLevel(logging.DEBUG)

    logger.debug(ARGS)


def get_filelist():
    file = ARGS.file

    filelist = []

    if type(file) is list:
        filelist += file
    else:
        filelist.append(file)

    for arg in filelist:
        if ARGS.all_dir and os.path.isdir(arg):
            for home, dirs, files in os.walk(arg):
                for dir in dirs:
                    filelist.append(os.path.join(home, dir))
        if ARGS.update_ass:
            filelist += glob(os.path.join(arg, "*.ass"))
        elif ARGS.extract_sub:
            filelist += glob(os.path.join(arg, "*.mkv"))
            filelist = list(
                filter(
                    lambda x: not os.path.isfile(re.sub(r"\.mkv", ".ass", x)), filelist
                )
            )
        else:
            filelist += glob(os.path.join(arg, "*.srt"))
            # filelist = list(filter(lambda x: not os.path.isfile(
            #     re.sub(r'\.mkv', '.ass', x)), filelist))

    filelist = list(filter(lambda x: os.path.isfile(x), filelist))

    logger.debug(filelist)
    return filelist


def main():
    initLogger()
    load_args()
    filelist = get_filelist()

    if not filelist:
        logger.info("nothing found")
        return

    if ARGS.update_ass:
        batch_execute(update_ASS_style, filelist)
    elif ARGS.extract_sub:
        extract_subs_MKV(filelist)
    elif ARGS.merge_srt:
        merge_SRTs(filelist)
    else:
        batch_execute(SRT_to_ASS, filelist)
    return


if __name__ == "__main__":
    main()
