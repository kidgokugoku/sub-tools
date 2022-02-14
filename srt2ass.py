# -*- coding: utf-8 -*-

import argparse
import codecs
import os
import re
import sys
from ast import Store
from concurrent.futures import process
from distutils import filelist
from glob import glob
from inspect import getfile
from tkinter.ttk import Style
import opencc

STR_CH_STYLE = 'Style: Default,Droid Sans Fallback,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,88,100,0,0,1,0.1,2,2,10,10,10,1'
STR_EN_STYLE = 'Style: Default,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.1,2,2,10,10,30,1'
STR_UNDER_ENG_STYLE = '{\\fsp0\\fnVerdana\\fs12\\1c&H003CA8DC}'


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
        if line.isdigit() and re.match('-?\d\d:\d\d:\d\d', lines[(ln+1)]):
            if tmpLines:
                subLines += tmpLines + "\n"
            tmpLines = ''
            lineCount = 0
            continue
        else:
            if re.match('-?\d\d:\d\d:\d\d', line):
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

    subLines += tmpLines + "\n"

    subLines = re.sub(r'\d(\d:\d{2}:\d{2}),(\d{2})\d', '\\1.\\2', subLines)
    subLines = re.sub(r'\s+-->\s+', ',', subLines)
    # replace style
    subLines = re.sub(r'<([ubi])>', "{\\\\\g<1>1}", subLines)
    subLines = re.sub(r'</([ubi])>', "{\\\\\g<1>0}", subLines)
    subLines = re.sub(
        r'<font\s+color="?#(\w{2})(\w{2})(\w{2})"?>', "{\\\\c&H\\3\\2\\1&}", subLines)
    subLines = re.sub(r'</font>', "", subLines)

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
                        help='srt file location',
                        nargs='*',
                        default='.')
    parser.add_argument("-e", "--english", "-en",
                        help="handle only ENG subtitles",
                        action='store_true')
    parser.add_argument("-d", "--delete",
                        help="delete the original .srt file",
                        action='store_true')
    parser.add_argument('-a',"--all-dir", 
                        help="process all .srt/.ass in child dir",
                        action='store_true')
    parser.add_argument('-u',"--update-ass", 
                        help="update .ass to custom style",
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
            os.remove(arg)
            print('deleted: '+arg)

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
            sytlestr=STR_UNDER_ENG_STYLE.replace('\\','\\\\')
            print(re.sub(r'N\{(.*)\}','N'+sytlestr,  output_str))

        output_str += utf8bom
        output_str = output_str.encode(encoding)

        with open(output_file+'.bak', 'wb') as output:
            output.write(output_str)
        if os.path.isfile(output_file):
            os.remove(output_file)
        os.rename("%s.bak" % output_file, output_file)

    return


def main():
    loadArgs()
    print(Args)

    filelist = getFilelist()

    if not Args.update_ass:
        srt2assAll(filelist)
    else:
        print
        updateAssStyle(filelist)


if __name__ == '__main__':
    main()
