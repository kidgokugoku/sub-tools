# -*- coding: utf-8 -*-

import argparse
import codecs
from distutils import filelist
from inspect import getfile
import os
import re
import sys
from ast import Store
from concurrent.futures import process
from glob import glob
from tkinter.tix import Tree

import opencc

STR_CH_STYLE = 'Style: Default,Droid Sans Fallback,23,&H00AAE2E6,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,88,100,0,0,1,0.1,2,2,10,10,10,1'
STR_EN_STYLE = 'Style: eng,Verdana,18,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,90,100,0,0,1,0.1,2,2,10,10,30,1'
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

    print('processing: '+input_file)

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
                if en:
                    tmpLines += 'Dialogue: 0,' + line + ',eng,,0,0,0,,'
                else:
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
[event]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text'''

    output_str = utf8bom + head_str + '\n' + subLines
    output_str = output_str.encode(encoding)

    with open(output_file, 'wb') as output:
        output.write(output_str)

    output_file = output_file.replace('\\', '\\\\')
    output_file = output_file.replace('/', '//')
    return output_file


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
    parser.add_argument("--all-dir", '-a',
                        help="process all .srt in child dir",
                        action='store_true')
    global Args
    Args = parser.parse_args()


def getFilelist():

    file = Args.file
    isAllDir = Args.all_dir

    filelist = []
    # 读所有参数
    if type(file) is list:
        filelist += file
    else:
        if '*' in file:
            filelist += glob(file)
        else:
            filelist.append(file)

    for arg in filelist:
        if isAllDir:
            if os.path.isdir(arg):
                for home, dirs, files in os.walk(arg):
                    for filename in files:
                        filelist.append(os.path.join(home, filename))
        elif os.path.isdir(arg):
            filelist += glob(os.path.join(arg, '*.srt'))

    filelist = list(filter(lambda x: os.path.isfile(x)
                    and '.srt' in x, filelist))
    #print(filelist)
    return filelist


def main():
    loadArgs()
    print(Args)

    isEnglish = Args.english
    isDelete = Args.delete

    filelist = getFilelist()

    for arg in filelist:
        srt2ass(arg, isEnglish)
        if isDelete:
            os.remove(arg)
            print('deleted: '+arg)


if __name__ == '__main__':
    main()
