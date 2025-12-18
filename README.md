
<p align="center">
    <img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/main/assets/boosty-black-badge.png" style="width: 80%; "/>
</p>

# 🖥️ About

Welcome to the **Boosty Downloader** project! 

This CLI tool allows you to download most of the content from Boosty.to in bulk.
The post content itself is saved in html with a little bit of styling.

**You can download:**
- Boosty Videos
- External Videos (YouTube, Vimeo)
- Files
- Full Post content (including photos and links)

## Changes in this fork

### Fixes

* support for audio in posts, including HTML rendering
* disabled giant tracebacks on errors
* videos in HTML render correctly
* faster walk through pages
* retries with actual delay to compensate for unstable APIs and network
* fully downloaded files are never downloaded again, even if app crashed, cache cleared, etc
* multiple boosty videos in a post do not overwrite each other

### Features

* page progress is stored in `username/last.offset` file for fast resume, delete it to start from 1st page
* External videos are not downloaded with yt-dlp anymore: it requires js runtime, auth, cookies, error handling. instead, youtube urls are saved to `.yt` files for manual processing
* create `ignore_me` file inside any post to skip it - a workaround if you have a post that breaks downloading

### Deal with Youtube

Example script to download all videos from `.yt` files and place them in the same folder. They will be picked up by HTML post.

* you need to install yt-dlp dependencies
* provide youtube cookies
* `yt-archive.txt` file will be used to skip downloaded videos
* customize format and other parameters to speed up downloads, change output, etc
* `--paths home:` sets yt-dlp output path for result and temp files to current_post/external_video
* `--postprocessor-args` is a fix for random fails in ffmpeg mkv conversion

```bash
find . -type f -name '*.yt' | sort -r | while read x ; do echo "DOWNLOADING ${x%/*}/${x##*/}.mkv"; yt-dlp -t mkv --cookies cookies.txt --download-archive yt-archive.txt -f "best[height<=720]" -a "$x" --paths "home:${x%/*}" -o "${x##*/}.mkv" --postprocessor-args "VideoRemuxer+ffmpeg:-bsf 'setts=ts=TS-STARTPTS'" || break; done
```


## 📑 Table of Contents
- [🖥️ About](#️-about)
  - [Changes in this fork](#changes-in-this-fork)
    - [Fixes](#fixes)
    - [Features](#features)
    - [Deal with Youtube](#deal-with-youtube)
  - [📑 Table of Contents](#-table-of-contents)
  - [✨ Features](#-features)
  - [📸 Screenshots \& Usage](#-screenshots--usage)
  - [🛠️ Installation](#️-installation)
  - [🚀 Configuration for Usage](#-configuration-for-usage)
    - [Step 1: Get the auth cookie and auth header](#step-1-get-the-auth-cookie-and-auth-header)
    - [Step 2: Paste the cookie and auth header into the config file](#step-2-paste-the-cookie-and-auth-header-into-the-config-file)
    - [Step 3: Run the utility](#step-3-run-the-utility)
  - [💖 Contributing](#-contributing)
  - [📜 License](#-license)



## ✨ Features

- 📦 **Bulk download**: Download all available content from your favorite creator.
- 🔎 **Total checker**: See how many posts are available to you, and which are not.
- 📂 **Content type filters**: Download only the content you need (videos, images, etc), choose what you really want with flags (see below).
- 📄 **Download specific posts**: Download post by url and username.
- 🔃 **Sync content seamlessly**: The utility keeps cache of already downloaded posts, so you can resume your download at any time or get new content after a while.
- 📼 **Choose your video quality**: You can choose preferred video quality to download (for boosty videos)
- 🎨 **Beauty posts preview**: You can see posts content with rendered offline html files with dark/light theme changing.
- 📊 **Order matters**: Posts have dates in names, so you can just sort it by name in your file explorer and see them in the correct chronological order.
- 🆙 **App update checker**: If new updates are available, you'll be notified when you use the application next time.


## 📸 Screenshots & Usage

<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/dev/assets/usage.png">
<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/dev/assets/total_check.png">
<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/dev/assets/example1.png">
<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/dev/assets/example2.png">



## 🛠️ Installation

1. **Install python**:
   - Window:
      ```bash
      winget install Python.Python.3.13
      ```
   - Linux:
      ```bash
      sudo apt-get install python3
      ```
   - macOS:
      ```bash
      brew install python
      ```

2. **Install the boosty-downloader package:**
   ```bash
   pip install boosty-downloader
   ```

3. **Run the application:**
   ```bash
   boosty-downloader --help
   ```

## 🚀 Configuration for Usage

### Step 1: Get the auth cookie and auth header

1. Open the [Boosty](https://boosty.to) website.
2. Click the "Sign in" button and fill you credentials.
3. Navigate to any author you have access to and scroll post a little.
4. Copy auth token and cookie from browser network tab.

<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/main/assets/auth_guide.png">

### Step 2: Paste the cookie and auth header into the config file

This config will be created during first run of the app in the current working directory.

<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/main/assets/config_guide.png">

### Step 3: Run the utility

Now you can just download your content with the following command:

```bash
boosty-downloader --username YOUR_CREATOR_NAME
```

## 💖 Contributing

If you want to contribute to this project, please see the [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
