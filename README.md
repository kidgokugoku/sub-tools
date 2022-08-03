# subTools
 
 现有功能：

- 将 srt 字幕转换为 ass 并添加自定义样式
- 更新 ass 字幕的样式
- 将两个 srt 字幕按时间合并为一个 srt 字幕                     
- 从 mkv 视频文件中提取 srt/ass 文件并 转换成ass/更新样式      

不会备份更改前的字幕，请自行做好备份。
 
## Install

直接下载.py文件或者克隆项目就可以使用。
```sh
$ git clone https://github.com/kidgokugoku/subTools
```

## usage

```sh
$ subTools.py
# 直接运行默认将运行目录下 .srt 文件转换为 .ass
```
```sh
$ subTools.py [-u | -m | -e]
# -u 参数用于更新 ass 字幕的样式
# -m 参数用于合并双语字幕
# -e 参数用于提取 mkv 文件中的字幕
```

```
usage: subTools.py [-h] [--english] [-d] [-b] [-a] [-u | -m | -e] [file ...]

positional arguments:
  file               srt file location, default all .srt files in current folder

optional arguments:
  -h, --help         show this help message and exit
  --english, -en     handle file that contian only ENG subtitles
  -d, --delete       delete the original .srt file
  -b, --bilingual    handle files that contain two language
  -a, --all-dir      process all .srt/.ass including all children dir
  -u, --update-ass   update .ass to custom style
  -m, --merge-srt    merge srts
  -e, --extract-sub  extract subtitles from .mkv
```

### 参考项目
最初的版本是从 [python-srt2ass](https://github.com/ewwink/python-srt2ass) 修改而来。

合并中英文字幕的代码参考了 [subindex](https://code.google.com/archive/p/subindex/) 和 [subtitle-merger](https://github.com/LittleAprilFool/subtitle-merger).

