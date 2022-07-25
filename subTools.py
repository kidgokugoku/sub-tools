# -*- coding: utf-8 -*-
import argparse
from genericpath import isfile
import os
import re
from collections import namedtuple
from glob import glob
import chardet
import opencc
from concurrent.futures import ThreadPoolExecutor, as_completed
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

utf8bom = ''
enc = ''
duo = False
inputcontent = []
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
        print(line)
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

def srt2ass(input_file):
    global duo

    if not '.srt' in input_file:
        print('input is not .srt file')
        return

    if not os.path.isfile(input_file):
        print(input_file + ' not exist')
        return

    print('processing srt2ass: '+input_file)

    src = fileopen(input_file)
    tmp = src[0]
    src = ''
    utf8bom = ''
    delete_flag = ''

    STR_UNDER_STYLE = STR_UNDER_EN_STYLE

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
                    if duo:
                        tmpLines += '\\N' + STR_UNDER_STYLE + line
                    else:
                        tmpLines += '\\N' + line
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
    if Args.english:
        head_str += STR_EN_STYLE
    else:
        head_str += STR_CH_STYLE
    head_str += '''
[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text'''

    output_str = utf8bom + head_str + '\n' + subLines
    output_str = output_str.encode('utf-8')

    if Args.delete:
        delete_flag = input_file
    if delete_flag:
        removeFile(delete_flag)

    with open(output_file, 'wb') as output:
        output.write(output_str)

    return

def extractSub(file):
    print(file)
    mkv = MKVFile(file)
    tracks = mkv.get_track()
    for track in tracks:
        if track._track_type == 'subtitles':
            if 'SRT' in track._track_codec:
                if track._language == 'eng' or track._language == 'chi' or track._language == 'zh' or track._language == 'zho':
                    dst_srt_path = file.replace(
                        '.mkv', '_track'+str(track._track_id)+'_'+track._language+'.srt')
                    print(track)
                    os.system('mkvextract {} tracks {}:{}\n'.format(
                        file, track._track_id, dst_srt_path))
    return

def addSub(file):
    print(file)
    mkv = MKVFile(file)
    subFile=file.replace('.mkv','.ass')
    if not os.path.isfile(subFile):
        print('no subtitles file in the dir.')
    else:
        subTrack=MKVTrack(subFile)
        subTrack.track_name='subTool added sub'
        subTrack.language='eng'
        subTrack.default_track=True
        mkv.add_track(subTrack)
        mkv.mux(file.replace('.mkv','_added.mkv'))
    return

def srt2assAll(filelist):
    # for arg in filelist:
    #    srt2ass(arg, Args.english)
    # return
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(srt2ass, filelist, timeout=15)

def updateAssAll(filelist):
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(updateAssStyle, filelist, timeout=15)

def extractSubAll(filelist):
    for arg in filelist:
       extractSub(arg)
    return
       
def addSubAll(filelist):
    with ThreadPoolExecutor(max_workers=17) as executor:
        return executor.map(addSub, filelist, timeout=15)

def updateAssStyle(input_file):
    print('processing updateAssStyle:'+input_file)

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
Format:''', tmp, 1)
    else:
        output_str = re.sub(r'(Styles])?[\s\S]*Format:', '''[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''+STR_CH_STYLE+'''
[Events]
Format:''', tmp, 1)
        sytlestr = STR_UNDER_EN_STYLE.replace('\\', '\\\\')
        output_str = re.sub(r'\{\\r\}', '',  output_str)
        output_str = re.sub(r'N\{(.*)\}(\S)', 'N' +
                            sytlestr+r'\2',  output_str)  # 英文行
        output_str = re.sub(r'Dialogue:(.*),.*,.*,(.*,[0-9]*,[0-9]*,[0-9]*),',
                            r'Dialogue:\1,Default,,\2,', output_str)  # 默认字体

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

def removeFile(file):
    os.remove(file)
    print('deleted: '+file)

def loadArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument('file',
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
    group.add_argument('-e', "--extract-sub",
                       help="extract subtitles from .mkv",
                       action='store_true')
    group.add_argument("--add-sub",
                       help="add subtitles to mkv",
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
                    for dir in dirs:
                        filelist.append(os.path.join(home, dir))
        
        if Args.update_ass:
            filelist += glob(os.path.join(arg, '*.ass'))
        elif Args.extract_sub or Args.add_sub:
            filelist += glob(os.path.join(arg, '*.mkv'))
        else:
            filelist += glob(os.path.join(arg, '*.srt'))
    filelist = list(filter(lambda x: os.path.isfile(x), filelist))
    print(filelist)
    return filelist

def main():
    global duo

    loadArgs()
    print(Args)

    filelist = getFilelist()

    if Args.extract_srt:
        extractSrt(filelist[0])
    elif Args.update_ass:
        updateAssAll(filelist)
    elif Args.extract_sub:
        extractSubAll(filelist)
    elif Args.add_sub:
        addSubAll(filelist)
    elif Args.merge_srt:
        mergedFiles = mergeFilelist(filelist)
        duo = True
        srt2assAll(mergedFiles)
    else:
        if Args.duo:
            duo = True
        srt2assAll(filelist)
    return

if __name__ == '__main__':
    main()
