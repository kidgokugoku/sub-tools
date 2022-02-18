import re
from utils import fileopen
from collections import namedtuple

sub = namedtuple("sub", "begin, end, content,beginTime,endTime")
subEx = namedtuple("sub", "begin, end, content")

utf8bom = ''
enc = ''
inputcontent = []
timeShift = 1000  # ms


def process(line):
    (begin, end) = line[1].strip().split(" --> ")
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
    for f in inputfile:
        print("merging: "+f)
        line = []
        global enc
        global utf8bom

        src = fileopen(f)
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
                    content.append(process(line))
                    line = [l]
            else:
                line.append(l)
            #line = []
        content.append(process(line))
        if(not len(content1)):
            content1 = content
            content = []
    # print(content)
    #timeMerge(content1, content)
    outputraw = timeMerge(content1, content)
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
