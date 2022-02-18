# -*- coding: utf-8 -*-
import argparse
import os
import re
from glob import glob
from utils import fileopen
import opencc

from merge import merge2srts
from merge import extractSrt
# Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
STR_CH_STYLE = '''Style: Default,Droid Sans Fallback,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,88,100,0,0,1,0.2,2,2,10,10,10,1
Style: Eng,Verdana,12,&H003CA8DC,&H000000FF,&H00000000,&H00000000,-1,0,0,0,90,100,0,0,1,0.1,2,2,10,10,10,1'''
STR_EN_STYLE = 'Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.3,3,2,10,10,20,1'
#STR_UNDER_ENG_STYLE = '{\\fsp0\\fnVerdana\\fs12\\1c&H003CA8DC}'
STR_UNDER_ENG_STYLE = '{\\rEng}'


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

    if not re.search(r'[\u4e00-\u9fa5]', tmp):
        en = True

    if u'\ufeff' in tmp:
        tmp = tmp.replace(u'\ufeff', '')
        utf8bom = u'\ufeff'

    tmp = tmp.replace("\r", "")
    lines = [x.strip() for x in tmp.split("\n") if x.strip()]
    subLines = ''
    tmpLines = ''
    lineCount = 0
    output_file = '.'.join(input_file.split('.')[:-1])
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
                        tmpLines += '\\N' + STR_UNDER_ENG_STYLE + line
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
            output_str = re.sub(r'Styles][\s\S]*Format:', '''Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''+STR_EN_STYLE+'''
[Events]
Format:''', tmp)
        else:
            output_str = re.sub(r'Styles][\s\S]*Format:', '''Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
'''+STR_CH_STYLE+'''
[Events]
Format:''', tmp)
            sytlestr = STR_UNDER_ENG_STYLE.replace('\\', '\\\\')
            output_str = re.sub(r'N\{(.*)\}', 'N'+sytlestr,  output_str)
            output_str = re.sub(r'Dialogue:(.*),.*,NTP',
                                r'Dialogue:\1,Default,NTP', output_str)

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
            continue
        else:
            if('ch' in file1 or 'en' in file):
                merge2srts([file1, file], output_file)
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
