# -*- coding: utf-8 -*-
import argparse
import os
import re
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from glob import glob

import chardet
from pymkv import MKVFile


# ASS/SSA style config

# Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
# 默认的字体样式，建议通过 Aegisub 自己调整合适后，用文本方式打开字幕复制粘贴过来。
STR_DEFAULT_STYLE = '''Style: Default,思源宋体 CN SemiBold,28,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0,0,1,1,3,2,10,10,10,1
Style: EN,GenYoMin TW M,12,&H003CA8DC,&H000000FF,&H00000000,&H00000000,-1,0,0,0,90,100,0,0,1,1,2,2,10,10,10,1
Style: JP,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,2,2,10,10,10,1'''

STR_CN_STYLE = 'Style: Default,思源宋体 CN SemiBold,28,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0,0,1,1,3,2,10,10,10,1'
STR_EN_STYLE = 'Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,10,10,20,1'
STR_JP_STYLE = 'Style: Default,GenYoMin JP B,23,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,10,10,10,1'

STR_2nd_EN_STYLE = '{\\rEN}'
STR_2nd_JP_STYLE = '{\\rJP}'

STR_2nd_STYLE = STR_2nd_EN_STYLE

ARGS = ''

# merge srt config
INT_TIMESHIFT = 1000                        # 合并字幕时的偏移量
# iso639 code list for the language you need to extract from MKV file
LIST_EXTRACT_LANGUAGE_ISO639 = [              # 需要提取的字幕语言的ISO639代码
    #    'en',
    'zh',
    #    'eng',
    'zho',
    'chi',
]


class MergeFile:
    file1 = ''
    file2 = ''
    sub = namedtuple("sub", "begin, end, content,beginTime,endTime")
    subEx = namedtuple("sub", "begin, end, content")
    timeShift = INT_TIMESHIFT  # ms
    __encoding = ''

    def __init__(self, file1, file2) -> None:
        self.file1 = file1
        self.file2 = file2

    def saveTo(self, outputfile):
        content1 = []
        content = []
        is_CHI_first_sub = 0
        inputfile = [self.file1, self.file2]
        for f in inputfile:
            print(f"merging: {f}")
            line = []

            src = fileOpen(f)
            tmp = src[0]
            if not self.__encoding:
                self.__encoding = 'utf-8'
            src = ''
            if u'\ufeff' in tmp:
                tmp = tmp.replace(u'\ufeff', '')
                self.__encoding = 'utf-8'
            is_CHI_first_sub = re.search(r'[\u4e00-\u9fa5]', tmp)
            tmp = tmp.replace("\r", "")
            lines = [x.strip() for x in tmp.split("\n") if x.strip()]
            tmp = ''

            for l in lines:
                if(re.sub(r'[0-9]+', '', l) == ''):
                    if(not len(line)):
                        line = [l]
                    else:
                        content.append(self.__process(line))
                        line = [l]
                else:
                    if(len(line)):
                        line.append(l)
            content.append(self.__process(line))
            if(not len(content1)):
                content1 = content
                content = []

        if not is_CHI_first_sub:
            outputraw = self.__timeMerge(content1, content)
        else:
            outputraw = self.__timeMerge(content, content1)

        self.__saveMergedSubFile(outputraw, outputfile)
        return

    def __saveMergedSubFile(self, raw, f):
        #output = UTF8BOM
        output = ''
        for i in range(len(raw)):
            output += ("%d\r\n" % (i+1))
            output += ("%s --> %s \r\n" % (raw[i].begin, raw[i].end))
            if type(raw[i].content) == list:
                for c in raw[i].content:
                    output += ("%s" % c)
                    output += ("\r\n")
            else:
                output += ("%s" % raw[i].content)
                output += ("\r\n")
        output = output.encode(self.__encoding)
        with open(f, 'wb') as output_file:
            output_file.write(output)
        return

    def __time(self, rawtime):
        (hour, minute, seconds) = rawtime.strip().split(":")
        (second, milisecond) = seconds.strip().split(",")
        return int(milisecond) + 1000 * int(second) + 1000 * 60 * int(minute) + 1000 * 60 * 60 * int(hour)

    def __process(self, line):
        try:
            (begin, end) = line[1].strip().split(" --> ")
        except:
            print(f"spliting error:{line}")
            return
        content = [' '.join(line[2:])]
        beginTime = self.__time(begin)
        endTime = self.__time(end)
        return self.sub(begin, end, content, beginTime, endTime)

    def __processEx(self, line):
        (begin, end) = line[1].strip().split(" --> ")
        content1 = line[2]
        content2 = ''
        if len(line)-3:
            content2 = line[3]
        return [self.subEx(begin, end, content1), self.subEx(begin, end, content2)]

    def __timeMerge(self, c1, c2):
        lockType = index1 = index2 = 0
        capTime1 = capTime2 = 0
        mergedContent = []
        while(index1 < len(c1) or index2 < len(c2)):
            captmp = ''
            if((not lockType == 1) and index1 < len(c1)):
                capTime1 = c1[index1].beginTime
            if((not lockType == 2) and index2 < len(c2)):
                capTime2 = c2[index2].beginTime
            lockType = 0
            if(capTime1 > capTime2 and capTime1 > capTime2+self.timeShift and index2 < len(c2) or index1 == len(c1)):
                lockType = 1
            if(capTime2 > capTime1 and capTime2 > capTime1+self.timeShift and index1 < len(c1) or index2 == len(c2)):
                lockType = 2

            if(not lockType == 1):
                captmp = c1[index1]
                index1 += 1
                if(lockType == 2):
                    mergedContent.append(captmp)

            if(not lockType == 2):
                if(captmp == ''):
                    captmp = c2[index2]
                else:
                    captmp.content.append(c2[index2].content[0])
                mergedContent.append(captmp)
                index2 += 1
        return mergedContent


def fileOpen(input_file):
    with open(input_file, mode="rb") as f:
        enc = chardet.detect(f.read())['encoding']
    tmp = ''
    with open(input_file, mode="r", encoding=enc, errors='ignore') as fd:
        tmp = fd.read()
    return [tmp, enc]


def merge2srt(inputfilelist):
    output_filelist = []
    it = iter(inputfilelist)
    for file in it:
        try:
            mergeFile = MergeFile(file, next(it))
        except:
            break
        output_file = re.sub(r'_track[0-9]+?|\.(en|zh)', '', file)
        output_file = re.sub('.srt', '_merge.srt', file)
        mergeFile.saveTo(output_file)
        output_filelist.append(output_file)
    if(ARGS.delete):
        removeFile(inputfilelist)
    ARGS.bilingual = True
    srt2ass(output_filelist)


def srt2ass(input_filelist, isEn=False):
    if type(input_filelist) is list and len(input_filelist) > 1:
        with ThreadPoolExecutor(max_workers=17) as executor:
            return executor.map(srt2ass, input_filelist, timeout=15)
    elif type(input_filelist) is list:
        input_filelist = input_filelist[0]
    if not os.path.isfile(input_filelist):
        print(f"{input_filelist} not exist")
        return

    print(f"processing srt2ass: {input_filelist}\n")

    src = fileOpen(input_filelist)
    tmpText = src[0]
    utf8bom = ''

    if u'\ufeff' in tmpText:
        tmpText = tmpText.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    tmpText = tmpText.replace("\r", "")
    lines = [x.strip() for x in tmpText.split("\n") if x.strip()]
    tmpText = ''
    lineCount = 0
    subLines = ''
    tmpLines = ''
    second_style = STR_2nd_STYLE if ARGS.bilingual else ''

    for index in range(len(lines)):
        line = lines[index]
        if line.isdigit() and re.match('-?\d+:\d\d:\d\d', lines[(index+1)]):
            if tmpLines:
                subLines += tmpLines + "\n"
            tmpLines = ''
            lineCount = 0
            continue
        elif re.match('-?\d+:\d\d:\d\d', line):
            line = line.replace('-0', '0')
            tmpLines += f'Dialogue: 0,{line},Default,,0,0,0,,'
        elif lineCount < 2:
            tmpLines += line
        else:
            tmpLines += '\\N' + second_style + line
        lineCount += 1
    subLines += tmpLines + "\r\n"
    # timestamp replace
    subLines = re.sub(r'\d*(\d:\d{2}:\d{2}),(\d{2})\d', r'\1.\2', subLines)
    subLines = re.sub(r'\s+-->\s+', ',', subLines)
    # replace style
    subLines = re.sub(r'<([ubi])>', "{\\\\\g<1>1}", subLines)
    subLines = re.sub(r'</([ubi])>', "{\\\\\g<1>0}", subLines)
    subLines = re.sub(
        r'<font\s+color="?#(\w{2})(\w{2})(\w{2})"?>', "{\\\\c&H\\3\\2\\1&}", subLines)
    subLines = re.sub(r'</font>', "", subLines)

    # converter = opencc.OpenCC('s2hk.json')  # 将简中转换成繁中
    # subLines = converter.convert(subLines)

    STR_STYLE = STR_EN_STYLE if ARGS.english or isEn else STR_DEFAULT_STYLE
    head_str = f'''[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{STR_STYLE}
[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text'''

    output_str = utf8bom + head_str + '\n' + subLines
    output_str = output_str.encode('utf-8')

    output_file = '.'.join(input_filelist.split('.')[:-1]) + '.ass'
    output_file = re.sub(
        r'_track[A-Za-z0-9_]*|_merge|\.(en|zh)|', '', output_file)
    with open(output_file, 'wb') as output:
        output.write(output_str)
    if ARGS.delete or '_merge' in input_filelist:
        removeFile(input_filelist)
    return


def extractSubFromMKV(input_filelist):
    for file in input_filelist:
        print(f"extracting: {file}")
        mkv = MKVFile(file)
        tracks = list(filter(lambda x: x._track_type ==
                      'subtitles', mkv.get_track()))
        for track in tracks:
            if not 'SubStationAlpha' in str(track._track_codec):
                continue
            dst_srt_path = file.replace(
                '.mkv', f'_track{str(track._track_id)}_{track._language}.ass')
            print(f"mkvextract:{track}")
            os.system(
                f'mkvextract \"{file}\" tracks {track._track_id}:\"{dst_srt_path}\"\n')
            updateAssStyle(dst_srt_path)
            break

        track_cnt = 0
        for track in tracks:
            if not 'SRT' in track._track_codec:
                continue
            isEN = track._language == 'eng'
            # and 'SDH' in str(track.track_name)
            if not (isEN or track._language in LIST_EXTRACT_LANGUAGE_ISO639):
                continue
            dst_srt_path = file.replace(
                '.mkv', f'_track{track._track_id}_{track._language}.srt')
            print(track)
            os.system(
                f'mkvextract \"{file}\" tracks {track._track_id}:\"{dst_srt_path}\"\n')
            track_cnt += 1
        if track_cnt == 1:
            srt2ass([dst_srt_path], isEN)


def updateAssStyle(input_filelist):
    if type(input_filelist) is list and len(input_filelist) > 1:
        with ThreadPoolExecutor(max_workers=17) as executor:
            return executor.map(updateAssStyle, input_filelist, timeout=15)
    elif type(input_filelist) is list:
        input_filelist = input_filelist[0]
    print(f"processing updateAssStyle: {input_filelist}\n")

    src = fileOpen(input_filelist)
    output_file = input_filelist
    tmp = src[0]
    encoding = src[1]

    utf8bom = ''

    if u'\ufeff' in tmp:
        tmp = tmp.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    STR_STYLE = STR_EN_STYLE if ARGS.english else STR_DEFAULT_STYLE
    output_str = re.sub(r'\[Script Info\][\s\S]*?\[Events\]', f'''[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{STR_STYLE}
[Events]''', tmp, 1)
    SECOND_LANG_STYLE = STR_2nd_STYLE.replace('\\', '\\\\')
    output_str = re.sub(r',\{\\fn(.*?)\}', ',',  output_str)
    output_str = re.sub(r'\{\\r\}', '',  output_str)
    output_str = re.sub(r'\\N(\{.*?\})?',
                        rf'\\N{SECOND_LANG_STYLE}',  output_str)  # 英文行
    output_str = re.sub(r'Dialogue:(.*?,.*?,.*?,)(.*),([0-9]+,[0-9]+,[0-9]+,)',
                        r'Dialogue:\1Default,,\3', output_str)  # 默认字体

    output_str += utf8bom
    output_str = output_str.encode(encoding)

    with open(output_file, 'wb') as output:
        output.write(output_str)
    return


def removeFile(filelist):
    if type(filelist) is list:
        for file in filelist:
            os.remove(file)
            print(f'deleted: {file}')
    else:
        os.remove(filelist)
        print(f'deleted: {filelist}')
    return


def loadArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("file",
                        help='srt file location, default all .srt files in current folder',
                        nargs='*',
                        default='.')
    parser.add_argument("--english", "-en",
                        help="handle file that contian only ENG subtitles",
                        action='store_true')
    parser.add_argument("-d", "--delete",
                        help="delete the original .srt file",
                        action='store_true')
    parser.add_argument("-b", "--bilingual",
                        help="handle files that contain two language",
                        action='store_true')
    parser.add_argument("-a", "--all-dir",
                        help="process all .srt/.ass including all children dir",
                        action='store_true')
    group = parser.add_mutually_exclusive_group()

    group.add_argument('-u', "--update-ass",
                       help="update .ass to custom style",
                       action='store_true')
    group.add_argument('-m', "--merge-srt",
                       help="merge srts ",
                       action='store_true')
    group.add_argument('-e', "--extract-sub",
                       help="extract subtitles from .mkv",
                       action='store_true')
    global ARGS
    ARGS = parser.parse_args()
    print(ARGS)


def getFilelist():
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
            filelist += glob(os.path.join(arg, '*.ass'))
        elif ARGS.extract_sub:
            filelist += glob(os.path.join(arg, '*.mkv'))
        else:
            filelist += glob(os.path.join(arg, '*.srt'))
    filelist = list(filter(lambda x: os.path.isfile(x), filelist))
    print(filelist)
    return filelist


def main():
    loadArgs()

    filelist = getFilelist()

    if not filelist:
        return

    if ARGS.update_ass:
        updateAssStyle(filelist)
    elif ARGS.extract_sub:
        extractSubFromMKV(filelist)
    elif ARGS.merge_srt:
        merge2srt(filelist)
    else:
        srt2ass(filelist)
    return


if __name__ == '__main__':
    main()
