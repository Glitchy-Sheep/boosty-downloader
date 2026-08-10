
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

## 📑 Table of Contents
- [🖥️ About](#️-about)
  - [📑 Table of Contents](#-table-of-contents)
  - [✨ Features](#-features)
  - [📸 Screenshots \& Usage](#-screenshots--usage)
  - [🛠️ Installation](#️-installation)
  - [🚀 Configuration for Usage](#-configuration-for-usage)
    - [Step 1: Get the auth cookie and auth header](#step-1-get-the-auth-cookie-and-auth-header)
      - [Option 1 - Manually](#option-1---manually)
      - [Option 2 - With helper script](#option-2---with-helper-script)
    - [Step 2: Paste the cookie and auth header into the config file](#step-2-paste-the-cookie-and-auth-header-into-the-config-file)
    - [Step 3: Run the utility](#step-3-run-the-utility)
  - [🛡️ When downloads fail](#️-when-downloads-fail)
  - [💖 Contributing](#-contributing)
  - [📜 License](#-license)



## ✨ Features

- 📦 **Bulk download**: Download all available content from your favorite creator.
- 🔎 **Total checker**: See how many posts are available to you, and which are not.
- 📂 **Content type filters**: Download only the content you need (videos, images, etc) with `--content-type-filter`.
- 📄 **Download specific posts**: Download post by url and username.
- 🔃 **Sync content seamlessly**: The utility keeps cache of already downloaded posts, so you can resume your download at any time or get new content after a while.
- 📼 **Choose your video quality**: You can choose preferred video quality to download (for boosty videos)
- 🎨 **Beauty posts preview**: You can see posts content with rendered offline html files with dark/light theme changing.
- 📊 **Order matters**: Posts have dates in names, so you can just sort it by name in your file explorer and see them in the correct chronological order.
- 🆙 **App update checker**: If new updates are available, you'll be notified when you use the application next time.
- 🔑 **Auth helper script**: Run `boosty-downloader show-auth-script` to get a browser console script that extracts your credentials automatically.


## 📸 Screenshots & Usage

<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/main/assets/usage.png">
<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/main/assets/total_check.png">
<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/main/assets/example1.png">
<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/refs/heads/main/assets/example2.png">



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

#### Option 1 - Manually

1. Open the [Boosty](https://boosty.to) website.
2. Click the "Sign in" button and fill you credentials.
3. Navigate to any author you have access to and scroll post a little.
4. Copy auth token and cookie from browser network tab.

<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/main/assets/auth_guide.png">

#### Option 2 - With helper script

1. Run `boosty-downloader show-auth-script` to show the helper script (it will be copied to your clipboard automatically).
2. Open the [Boosty](https://boosty.to) website and log in.
3. Open browser console (F12) and paste the script.
4. Scroll the page a little - a floating box with your credentials will appear.

### Step 2: Paste the cookie and auth header into the config file

This config will be created during first run of the app in the current working directory.

<img src="https://raw.githubusercontent.com/Glitchy-Sheep/boosty-downloader/main/assets/config_guide.png">

### Step 3: Run the utility

Now you can just download your content with the following command:

```bash
boosty-downloader download --username YOUR_CREATOR_NAME
```

## 🛡️ When downloads fail

One bad post never costs you the whole run:

- A post that fails to download is skipped, and the run continues.
- Every skipped post is written to `failed_downloads.log` next to your downloads.
- At the end, a summary lists everything that was skipped and why.
- If 5 posts in a row fail, the downloader stops early: a streak like this means the problem is not in the posts - check your disk, folder permissions, or network.
- Prefer to finish the pass no matter what? Add `--skip-all-failures` - the run never stops on a failure streak.

Downloaded posts are cached. After you fix the cause, run the same command again - finished posts are skipped in seconds, and the download continues where it stopped.

Can't tell what's breaking? Re-run with `--debug`: it writes `boosty-downloader-debug.log` with every request and full error details, safe to attach to a [GitHub issue](https://github.com/Glitchy-Sheep/boosty-downloader/issues) - download links are logged without their signed keys.

## 💖 Contributing

If you want to contribute to this project, please see the [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
