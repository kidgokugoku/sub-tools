# subTools

现有功能：

- 将 srt 字幕转换为 ass 并添加自定义样式
- 更新 ass 字幕的样式
- 将两个 srt 字幕按时间合并为一个 srt 字幕
- 从 mkv 视频文件中提取 srt/ass 文件并 转换成ass/更新样式

不会备份更改前的字幕，请自行做好备份

```
usage: subTools.py [-h] [--english] [--delete] [-d] [-a] [-u | -m | -e | --extract-srt] [file ...]

positional arguments:
  file               srt file location, default all .srt files in current folder

optional arguments:
  -h, --help         show this help message and exit
  --english, -en     handle only ENG subtitles
  --delete           delete the original .srt file
  -d, --duo          .srt file contain two language
  -a, --all-dir      process all .srt/.ass in child dir
  -u, --update-ass   update .ass to custom style
  -m, --merge-srt    merge srts
  -e, --extract-sub  extract subtitles from .mkv
  --extract-srt      extract srt
```


### 参考项目
> https://github.com/ewwink/python-srt2ass
> https://code.google.com/archive/p/subindex/
> https://github.com/LittleAprilFool/subtitle-merger
