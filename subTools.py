# -*- coding: utf-8 -*-
import argparse
import codecs
import os
import re
from collections import namedtuple
from glob import glob

import opencc

# srt2ass config

# Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
# 旧的样式
#STR_CH_STYLE = '''Style: Default,Droid Sans Fallback,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,88,100,0,0,1,0.2,2,2,10,10,10,1
#Style: Eng,Verdana,12,&H003CA8DC,&H000000FF,&H00000000,&H00000000,-1,0,0,0,90,100,0,0,1,0.1,2,2,10,10,10,1
#Style: Jp,MingLiU-ExtB,16,&H003CA8DC,&H000000FF,&H00000000,&H00000000,-1,0,0,0,88,100,0,0,1,0.1,2,2,10,10,10,1'''
STR_CH_STYLE = '''Style: Default,MingLiU-ExtB,20,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,85,100,0,0,1,0.2,2,2,10,10,10,1
Style: Eng,Verdana,12,&H003CA8DC,&H000000FF,&H00000000,&H00000000,-1,0,0,0,90,100,0,0,1,0.1,2,2,10,10,10,1
Style: Jp,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,10,10,10,1'''

STR_EN_STYLE = 'Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,10,10,20,1'
STR_JP_STYLE = 'Style: jp,GenYoMin JP B,15,&H003CA8DC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.1,2,2,10,10,10,1'

STR_UNDER_EN_STYLE = '{\\rEng}'
STR_UNDER_JP_STYLE = '{\\rJp}'

# merge srt config

sub = namedtuple("sub", "begin, end, content,beginTime,endTime")
subEx = namedtuple("sub", "begin, end, content")

utf8bom = ''
enc = ''
inputcontent = []
timeShift = 1000  # ms


def fileopen(input_file):
    encodings = ["utf-32", "utf-16", "utf-8",
                 "cp1252", "gb2312", "gbk", "big5"]
    tmp = ''
    for enc in encodings:
        try:
            with codecs.open(input_file, mode="r", encoding=enc) as fd:
                tmp = fd.read()
                break
        except:
            # print enc + ' failed'
            continue
    return [tmp, enc]


def process(line):
    try:
        (begin, end) = line[1].strip().split(" --> ")
    except:
        print(line)
        return
    content = [''.join(line[2:])]
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


def time(rawtime):
    (hour, minute, seconds) = rawtime.strip().split(":")
    (second, milisecond) = seconds.strip().split(",")
    return int(milisecond) + 1000 * int(second) + 1000 * 60 * int(minute) + 1000 * 60 * 60 * int(hour)


def printsub(raw, f, enc='utf-8'):
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
    CH_first_flag = 0
    for f in inputfile:
        print("merging: "+f)
        line = []
        global enc
        global utf8bom

        src = fileopen(f)
        tmp = src[0]
        if not enc:
            enc = src[1]
        src = ''
        if u'\ufeff' in tmp:
            tmp = tmp.replace(u'\ufeff', '')
            utf8bom = u'\ufeff'
            enc = 'utf-8'
        CH_first_flag = re.search(r'[\u4e00-\u9fa5]', tmp)
        tmp = tmp.replace("\r", "")
        lines = [x.strip() for x in tmp.split("\n") if x.strip()]
        tmp = ''

        for l in lines:
            # print(l)
            if(re.sub(r'[0-9]+', '', l) == ''):
                if(not len(line)):
                    line = [l]
                else:
                    content.append(process(line))
                    line = [l]
            else:
                if(len(line)):
                    line.append(l)
            #line = []
        content.append(process(line))
        if(not len(content1)):
            content1 = content
            content = []

    if not CH_first_flag:
        outputraw = timeMerge(content1, content)
    else:
        outputraw = timeMerge(content, content1)

    printsub(outputraw, outputfile, enc)
    return


def extractSrt(inputfile):
    print("extracting: "+inputfile)
    content1 = []
    content2 = []
    line = []
    global enc
    global utf8bom

    src = fileopen(inputfile)
    tmp = src[0]
    enc = src[1]
    src = ''
    if u'\ufeff' in tmp:
        tmp = tmp.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    tmp = tmp.replace("\r", "")
    lines = [x.strip() for x in tmp.split("\n") if x.strip()]
    tmp = ''

    for l in lines:
        # print(l)
        if(re.sub(r'[0-9]+', '', l) == ''):
            if(not len(line)):
                line = [l]
            else:
                content1.append(processEx(line)[0])
                content2.append(processEx(line)[1])
                line = [l]
        else:
            line.append(l)
    printsub(content1, re.sub('.srt', '_1.srt', inputfile), enc)
    printsub(content2, re.sub('.srt', '_2.srt', inputfile), enc)


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
        #print('captime1:'+str(capTime1)+' captime2:'+str(capTime2))
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
        # print(captmp)
    return mergedContent


def srt2ass(input_file, en=False):

    if not '.srt' in input_file:
        print('input is not .srt file')
        return

    if not os.path.isfile(input_file):
        print(input_file + ' not exist')
        return

    print('processing srt2ass: '+input_file)

    src = fileopen(input_file)
    tmp = src[0]
    encoding = src[1]
    src = ''
    utf8bom = ''
    delete_flag = ''

    STR_UNDER_STYLE = STR_UNDER_EN_STYLE
    if re.search(r'[\u0800-\u4e00]',tmp):
        STR_UNDER_STYLE = STR_UNDER_JP_STYLE
    # if not re.search(r'[\u4e00-\u9fa5]', tmp):
    #    en = True

    if u'\ufeff' in tmp:
        tmp = tmp.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    tmp = tmp.replace("\r", "")
    lines = [x.strip() for x in tmp.split("\n") if x.strip()]
    subLines = ''
    tmpLines = ''
    lineCount = 0
    output_file = '.'.join(input_file.split('.')[:-1])
    if '_merge' in input_file:
        delete_flag = output_file
        delete_flag += '.srt'
        output_file = re.sub(r'_merge', '', output_file)
    output_file += '.ass'
    output_file = re.sub(r'_track[\s\S]*]', '', output_file)

    for ln in range(len(lines)):
        line = lines[ln]
        if line.isdigit() and re.match('-?\d+:\d\d:\d\d', lines[(ln+1)]):
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
                    if en:
                        tmpLines += '\\N' + line
                    else:
                        tmpLines += '\\N' + STR_UNDER_STYLE + line
            lineCount += 1
        ln += 1

    subLines += tmpLines + "\r\n"

    subLines = re.sub(r'\d*(\d:\d{2}:\d{2}),(\d{2})\d', '\\1.\\2', subLines)
    subLines = re.sub(r'\s+-->\s+', ',', subLines)
    # replace style
    subLines = re.sub(r'<([ubi])>', "{\\\\\g<1>1}", subLines)
    subLines = re.sub(r'</([ubi])>', "{\\\\\g<1>0}", subLines)
    subLines = re.sub(
        r'<font\s+color="?#(\w{2})(\w{2})(\w{2})"?>', "{\\\\c&H\\3\\2\\1&}", subLines)
    subLines = re.sub(r'</font>', "", subLines)

    converter = opencc.OpenCC('s2hk.json')
    subLines = converter.convert(subLines)

    head_str = '''[Script Info]
; This is an Advanced Sub Station Alpha v4+ script.
Title:
ScriptType: v4.00+
Collisions: Normal
PlayDepth: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''
    if en:
        head_str += STR_EN_STYLE
    else:
        head_str += STR_CH_STYLE
    head_str += '''
[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text'''

    output_str = utf8bom + head_str + '\n' + subLines
    output_str = output_str.encode(encoding)

    if delete_flag:
        removeFile(delete_flag)

    with open(output_file, 'wb') as output:
        output.write(output_str)

    return


def loadArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument('file',
                        help='srt file location, default all .srt files in current folder',
                        nargs='*',
                        default='.')
    parser.add_argument("-e", "--english", "-en",
                        help="handle only ENG subtitles",
                        action='store_true')
    parser.add_argument("-d", "--delete",
                        help="delete the original .srt file",
                        action='store_true')
    parser.add_argument('-a', "--all-dir",
                        help="process all .srt/.ass in child dir",
                        action='store_true')
    group = parser.add_mutually_exclusive_group()

    group.add_argument('-u', "--update-ass",
                       help="update .ass to custom style",
                       action='store_true')
    group.add_argument('-m', "--merge-srt",
                       help="merge srts ",
                       action='store_true')
    group.add_argument('--extract-srt',
                       help="extract srt ",
                       action='store_true')
    global Args
    Args = parser.parse_args()


def getFilelist():

    file = Args.file

    filelist = []
    # read input from args
    if type(file) is list:
        filelist += file
    else:
        if '*' in file:
            filelist += glob(file)
        else:
            filelist.append(file)

    for arg in filelist:
        if Args.all_dir:
            if os.path.isdir(arg):
                for home, dirs, files in os.walk(arg):
                    for filename in files:
                        filelist.append(os.path.join(home, filename))
        elif os.path.isdir(arg):
            filelist += glob(os.path.join(arg, '*.srt'))
            filelist += glob(os.path.join(arg, '*.ass'))

    filelist = list(filter(lambda x: os.path.isfile(x), filelist))
    if not Args.update_ass:
        filelist = list(filter(lambda x: '.srt' in x, filelist))
    else:
        filelist = list(filter(lambda x: '.ass' in x, filelist))

    print(filelist)
    return filelist


def srt2assAll(filelist):

    for arg in filelist:
        srt2ass(arg, Args.english)
        if Args.delete:
            removeFile(arg)
    return


def updateAssStyle(filelist):

    for input_file in filelist:
        print('processing updateAssStyle: '+input_file)

        src = fileopen(input_file)
        output_file = input_file
        output_file = re.sub(r'_track[\s\S]*]', '', output_file)
        tmp = src[0]
        encoding = src[1]

        src = ''
        utf8bom = ''

        if u'\ufeff' in tmp:
            tmp = tmp.replace(u'\ufeff', '')
            utf8bom = u'\ufeff'
        if Args.english:
            output_str = re.sub(r'(Styles])?[\s\S]*Format:', '''[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''+STR_EN_STYLE+'''
[Events]
Format:''', tmp)
        else:
            output_str = re.sub(r'(Styles])?[\s\S]*Format:', '''[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''+STR_CH_STYLE+'''
[Events]
Format:''', tmp)
            sytlestr = STR_UNDER_EN_STYLE.replace('\\', '\\\\')
            output_str = re.sub('{\r}', '',  output_str)
            output_str = re.sub(r'N\{(.*)\}', 'N'+sytlestr,  output_str)  # 英文行
            output_str = re.sub(r'Dialogue:(.*),.*,,0,0,0,,',
                                r'Dialogue:\1,Default,,0,0,0,,', output_str)  # 默认字体

        output_str += utf8bom
        output_str = output_str.encode(encoding)

        with open(output_file+'.bak', 'wb') as output:
            output.write(output_str)
        if os.path.isfile(output_file):
            os.remove(output_file)
        if Args.delete:
            removeFile(input_file)
        os.rename("%s.bak" % output_file, output_file)

    return


def mergeFilelist(filelist):
    file1 = ''
    outFilelist = []
    for file in filelist:
        if(not file1):
            file1 = file
            output_file = re.sub(r'_track[\s\S]*]', '', file1)
            output_file = re.sub('.srt', '_merge.srt', file1)
            continue
        else:
            merge2srts([file, file1], output_file)
            outFilelist.append(output_file)
            file1 = ''
    if(Args.delete):
        for arg in filelist:
            os.remove(arg)
            print('deleted: '+arg)
    return outFilelist


def removeFile(file):
    os.remove(file)
    print('deleted: '+file)


def main():
    loadArgs()
    print(Args)

    filelist = getFilelist()

    if Args.extract_srt:
        extractSrt(filelist[0])
    elif Args.update_ass:
        updateAssStyle(filelist)
    elif Args.merge_srt:
        mergedFiles = mergeFilelist(filelist)
        srt2assAll(mergedFiles)
    else:
        srt2assAll(filelist)
    return


if __name__ == '__main__':
    main()
