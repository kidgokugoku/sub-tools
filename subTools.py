# -*- coding: utf-8 -*-
import argparse
import os
import re
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from glob import glob

import chardet
import opencc
from pymkv import MKVFile, MKVTrack

# srt2ass config

# Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
STR_CH_STYLE = '''Style: Default,思源宋体 CN SemiBold,28,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,85,100,0,0,1,1,3,2,10,10,10,1
Style: Eng,GenYoMin TW M,12,&H003CA8DC,&H000000FF,&H00000000,&H00000000,-1,0,0,0,90,100,0,0,1,1,2,2,10,10,10,1
Style: Jp,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,2,2,10,10,10,1'''

STR_EN_STYLE = 'Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,10,10,20,1'
STR_JP_STYLE = 'Style: jp,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,10,10,10,1'

STR_UNDER_EN_STYLE = '{\\rEng}'
STR_UNDER_JP_STYLE = '{\\rJp}'

# merge srt config

sub = namedtuple("sub", "begin, end, content,beginTime,endTime")
subEx = namedtuple("sub", "begin, end, content")
Args = ''
utf8bom = ''
encoding = ''
timeShift = 1000  # ms


def fileopen(input_file):
    with open(input_file, mode="rb") as f:
        enc = chardet.detect(f.read())['encoding']
    if enc == 'GB2312':
        enc = 'gbk'
    tmp = ''
    with open(input_file, mode="r", encoding=enc, errors='ignore') as fd:
        tmp = fd.read()
    return [tmp, enc]


def process(line):
    try:
        (begin, end) = line[1].strip().split(" --> ")
    except:
        print(f"spliting error:{line}")
        return
    content = [' '.join(line[2:])]
    beginTime = time(begin)
    endTime = time(end)
    return sub(begin, end, content, beginTime, endTime)


def processEx(line):
    (begin, end) = line[1].strip().split(" --> ")
    content1 = line[2]
    content2 = ''
    if len(line)-3:
        content2 = line[3]
    return [subEx(begin, end, content1), subEx(begin, end, content2)]


def mergeFilelist(filelist):
    file1 = ''
    output_filelist = []
    for file in filelist:
        if(not file1):
            file1 = file
            output_file = re.sub(r'_track[\s\S]*]', '', file1)
            output_file = re.sub('.srt', '_merge.srt', file1)
            continue
        else:
            merge2srts([file, file1], output_file)
            output_filelist.append(output_file)
            file1 = ''
    if(Args.delete):
        removeFile(filelist)
    Args.duo = True
    srt2assAll(output_filelist)


def time(rawtime):
    (hour, minute, seconds) = rawtime.strip().split(":")
    (second, milisecond) = seconds.strip().split(",")
    return int(milisecond) + 1000 * int(second) + 1000 * 60 * int(minute) + 1000 * 60 * 60 * int(hour)


def saveMergedSubFile(raw, f, enc='utf-8'):
    output = utf8bom
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
    output = output.encode(enc)
    with open(f, 'wb') as output_file:
        output_file.write(output)
    return


def merge2srts(inputfile, outputfile):
    content1 = []
    content = []
    is_CHI_first_sub = 0
    for f in inputfile:
        print(f"merging: {f}")
        line = []
        global encoding
        global utf8bom

        src = fileopen(f)
        tmp = src[0]
        if not encoding:
            encoding = src[1]
        src = ''
        if u'\ufeff' in tmp:
            tmp = tmp.replace(u'\ufeff', '')
            utf8bom = u'\ufeff'
            encoding = 'utf-8'
        is_CHI_first_sub = re.search(r'[\u4e00-\u9fa5]', tmp)
        tmp = tmp.replace("\r", "")
        lines = [x.strip() for x in tmp.split("\n") if x.strip()]
        tmp = ''

        for l in lines:
            if(re.sub(r'[0-9]+', '', l) == ''):
                if(not len(line)):
                    line = [l]
                else:
                    content.append(process(line))
                    line = [l]
            else:
                if(len(line)):
                    line.append(l)
        content.append(process(line))
        if(not len(content1)):
            content1 = content
            content = []

    if not is_CHI_first_sub:
        outputraw = timeMerge(content1, content)
    else:
        outputraw = timeMerge(content, content1)

    saveMergedSubFile(outputraw, outputfile, encoding)
    return


def extractSrtFromAssFile(inputfile):
    print(f"extracting: {inputfile}")
    content1 = []
    content2 = []
    line = []
    global encoding
    global utf8bom

    src = fileopen(inputfile)
    tmp = src[0]
    encoding = src[1]
    src = ''
    if u'\ufeff' in tmp:
        tmp = tmp.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    tmp = tmp.replace("\r", "")
    lines = [x.strip() for x in tmp.split("\n") if x.strip()]
    tmp = ''

    for l in lines:
        if(re.sub(r'[0-9]+', '', l) == ''):
            if(not len(line)):
                line = [l]
            else:
                content1.append(processEx(line)[0])
                content2.append(processEx(line)[1])
                line = [l]
        else:
            line.append(l)
    saveMergedSubFile(content1, re.sub('.srt', '_1.srt', inputfile), encoding)
    saveMergedSubFile(content2, re.sub('.srt', '_2.srt', inputfile), encoding)


def timeMerge(c1, c2):
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
        if(capTime1 > capTime2 and capTime1 > capTime2+timeShift and index2 < len(c2) or index1 == len(c1)):
            lockType = 1
        if(capTime2 > capTime1 and capTime2 > capTime1+timeShift and index1 < len(c1) or index2 == len(c2)):
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


def srt2ass(input_file, isEn=False):
    if not os.path.isfile(input_file):
        print(f"{input_file} not exist")
        return

    print(f"processing srt2ass: {input_file}")

    src = fileopen(input_file)
    tmpText = src[0]
    utf8bom = ''

    if u'\ufeff' in tmpText:
        tmpText = tmpText.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    tmpText = tmpText.replace("\r", "")
    lines = [x.strip() for x in tmpText.split("\n") if x.strip()]
    output_file = '.'.join(input_file.split('.')[:-1]) + '.ass'
    output_file = re.sub(r'(_track[\s\S]*?|_merge)\.', '.', output_file)

    STR_UNDER_STYLE = STR_UNDER_EN_STYLE
    lineCount = 0
    subLines = ''
    tmpLines = ''
    for index in range(len(lines)):
        line = lines[index]
        if line.isdigit() and re.match('-?\d+:\d\d:\d\d', lines[(index+1)]):
            if tmpLines:
                subLines += tmpLines + "\n"
            tmpLines = ''
            lineCount = 0
            continue
        else:
            if re.match('-?\d+:\d\d:\d\d', line):
                line = line.replace('-0', '0')
                tmpLines += 'Dialogue: 0,' + line + ',Default,,0,0,0,,'
            else:
                if lineCount < 2:
                    tmpLines += line
                else:
                    if Args.duo:
                        tmpLines += '\\N' + STR_UNDER_STYLE + line
                    else:
                        tmpLines += '\\N' + line
            lineCount += 1
    subLines += tmpLines + "\r\n"

    subLines = re.sub(r'\d*(\d:\d{2}:\d{2}),(\d{2})\d', '\\1.\\2', subLines)
    subLines = re.sub(r'\s+-->\s+', ',', subLines)
    # replace style
    subLines = re.sub(r'<([ubi])>', "{\\\\\g<1>1}", subLines)
    subLines = re.sub(r'</([ubi])>', "{\\\\\g<1>0}", subLines)
    subLines = re.sub(
        r'<font\s+color="?#(\w{2})(\w{2})(\w{2})"?>', "{\\\\c&H\\3\\2\\1&}", subLines)
    subLines = re.sub(r'</font>', "", subLines)

    # converter = opencc.OpenCC('s2hk.json')  # 将简中转换成繁中
    # subLines = converter.convert(subLines)

    STR_STYLE = STR_EN_STYLE if Args.english or isEn else STR_CH_STYLE
    head_str = f'''[Script Info]
This is an Advanced Sub Station Alpha v4+ script generated by subTools.py.
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{STR_STYLE}
[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text'''

    output_str = utf8bom + head_str + '\n' + subLines
    output_str = output_str.encode('utf-8')

    if Args.delete or '_merge' in input_file:
        removeFile(input_file)

    with open(output_file, 'wb') as output:
        output.write(output_str)

    return


def srt2assAll(filelist):
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(srt2ass, filelist, timeout=15)


def updateAssStyleAll(filelist):
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(updateAssStyle, filelist, timeout=15)


def extractSub(file):
    track_cnt = 0
    mkv = MKVFile(file)
    tracks = mkv.get_track()
    for track in tracks:
        if not track._track_type == 'subtitles' and 'SubStationAlpha' in str(track._track_codec):
            continue
        dst_srt_path = file.replace(
            '.mkv', f'_track{str(track._track_id)}_{track._language}.ass')
        print(f"mkvextract:{track}")
        os.system(
            f'mkvextract \"{file}\" tracks {track._track_id}:\"{dst_srt_path}\"\n')
        updateAssStyle(dst_srt_path)
        return

    for track in tracks:
        if not track._track_type == 'subtitles' and 'SRT' in track._track_codec:
            continue
        isEN = track._language == 'eng' and 'SDH' in str(track.track_name)
        if not isEN or track._language == 'chi' or track._language == 'zh' or track._language == 'zho':
            continue
        dst_srt_path = file.replace(
            '.mkv', '_track'+str(track._track_id)+'_'+track._language+'.srt')
        print(track)
        os.system(
            f'mkvextract \"{file}\" tracks {track._track_id}:\"{dst_srt_path}\"\n')
        track_cnt += 1
        if track_cnt == 1:
            srt2ass(dst_srt_path, isEN)


def extractSubAll(filelist):
    for file in filelist:
        extractSub(file)
    return


def updateAssStyle(input_file):
    print(f"processing updateAssStyle: {input_file}")

    src = fileopen(input_file)
    output_file = input_file
    output_file = re.sub(r'_track[\s\S]*]', '', output_file)
    tmp = src[0]
    encoding = src[1]

    utf8bom = ''

    if u'\ufeff' in tmp:
        tmp = tmp.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    STR_STYLE = STR_EN_STYLE if Args.english else STR_CH_STYLE
    output_str = re.sub(r'\[V4(\+)? Styles\][\s\S]*?\[Events\]', f'''generated by subTool.py
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{STR_STYLE}
[Events]''', tmp, 1)
    SECOND_LANG_STYLE = STR_UNDER_EN_STYLE.replace('\\', '\\\\')
    output_str = re.sub(r',\{\\fn(.*?)\}', ',',  output_str)
    output_str = re.sub(r'\{\\r\}', '',  output_str)
    output_str = re.sub(r'\\N\{.*?\}',
                        rf'\\N{SECOND_LANG_STYLE}',  output_str)  # 英文行
    output_str = re.sub(r'Dialogue:(.*?,.*?,.*?,)(.*),([0-9]+,[0-9]+,[0-9]+,)',
                        r'Dialogue:\1Default,,\3', output_str)  # 默认字体

    output_str += utf8bom
    output_str = output_str.encode(encoding)

    with open(output_file+'.bak', 'wb') as output:
        output.write(output_str)
    if os.path.isfile(output_file):
        os.remove(output_file)
    if Args.delete:
        removeFile(input_file)
    os.rename(f"{output_file}.bak", output_file)
    return


def removeFile(filelist):
    if type(filelist) is list:
        for file in filelist:
            os.remove(file)
            print(f'deleted: {file}')
    else:
        os.remove(filelist)
        print(f'deleted: {filelist}')


def loadArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("file",
                        help='srt file location, default all .srt files in current folder',
                        nargs='*',
                        default='.')
    parser.add_argument("--english", "-en",
                        help="handle only ENG subtitles",
                        action='store_true')
    parser.add_argument("--delete",
                        help="delete the original .srt file",
                        action='store_true')
    parser.add_argument("-d", "--duo",
                        help=".srt file contain two language",
                        action='store_true')
    parser.add_argument("-a", "--all-dir",
                        help="process all .srt/.ass in child dir",
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
    group.add_argument('--extract-srt',
                       help="extract srt ",
                       action='store_true')
    global Args
    Args = parser.parse_args()
    print(Args)


def getFilelist():
    file = Args.file

    filelist = []

    if type(file) is list:
        filelist += file
    else:
        filelist.append(file)

    for arg in filelist:
        if Args.all_dir and os.path.isdir(arg):
            for home, dirs, files in os.walk(arg):
                for dir in dirs:
                    filelist.append(os.path.join(home, dir))
        if Args.update_ass:
            filelist += glob(os.path.join(arg, '*.ass'))
        elif Args.extract_sub:
            filelist += glob(os.path.join(arg, '*.mkv'))
        else:
            filelist += glob(os.path.join(arg, '*.srt'))
    filelist = list(filter(lambda x: os.path.isfile(x), filelist))
    print(filelist)
    return filelist


def main():
    global Args
    loadArgs()

    filelist = getFilelist()

    if Args.extract_srt:
        extractSrtFromAssFile(filelist[0])
    elif Args.update_ass:
        updateAssStyleAll(filelist)
    elif Args.extract_sub:
        extractSubAll(filelist)
    elif Args.merge_srt:
        mergeFilelist(filelist)
    else:
        srt2assAll(filelist)
    return


if __name__ == '__main__':
    main()
