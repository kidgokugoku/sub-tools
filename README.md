# sub-tools

这是一个用于处理视频字幕的 Python 工具，支持字幕提取、格式转换、样式更新和字幕合并等功能。

## 功能特性

- 从视频文件（MKV/MP4）中提取字幕轨道
- 将 SRT 字幕转换为 ASS 格式
- 更新 ASS 字幕的样式
- 合并不同语言的字幕（如中文字幕与英文字幕）

## 依赖要求

- Python 3.7+
- ffmpeg
- Python 库:
  - chardet
  - tqdm
  - ffmpeg-python

## 安装

1. 确保已安装 Python 3.7 或更高版本
2. 安装 ffmpeg 并确保它在系统路径中
3. 安装所需的 Python 库：

```bash
pip install chardet tqdm ffmpeg-python
```

## 使用方法

### 基本语法

```bash
python sub-tools.py [选项] [文件或目录...]
```

### 选项

- `-r, --recurse`: 递归处理指定目录中的所有文件
- `-f, --force`: 强制操作，覆盖已存在的文件
- `-u, --update-ass`: 更新 ASS 字幕的样式
- `-m, --merge-srt`: 合并 SRT 字幕
- `-e, --extract-sub`: 从视频文件中提取字幕

### 示例

1. **从视频文件中提取字幕**:

   ```bash
   python sub-tools.py -e video.mkv
   ```

2. **递归处理目录中的所有视频文件**:

   ```bash
   python sub-tools.py -e -r /path/to/videos/
   ```

3. **将 SRT 字幕转换为 ASS 格式**:

   ```bash
   python sub-tools.py subtitle.srt
   ```

4. **更新 ASS 字幕的样式**:

   ```bash
   python sub-tools.py -u subtitle.ass
   ```

5. **合并两个不同语言的 SRT 字幕**:

   ```bash
   python sub-tools.py -m chinese.srt english.srt
   ```

6. **强制覆盖已存在的文件**:
   ```bash
   python sub-tools.py -f -e video.mkv
   ```

## 配置

工具的默认配置在脚本顶部定义，包括：

- 字幕样式定义 (STYLE_DEFAULT, STYLE_EN 等)
- 需要提取的字幕语言列表 (EXTRACT_LIST)
- 需要合并的语言组合 (MERGE_LIST)

### 参考项目

最初的版本是从 [python-srt2ass](https://github.com/ewwink/python-srt2ass) 修改而来。

合并中英文字幕的代码参考了 [subindex](https://code.google.com/archive/p/subindex/) 和 [subtitle-merger](https://github.com/LittleAprilFool/subtitle-merger).
