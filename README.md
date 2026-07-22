# Mukai-Translator

English | [한국어](docs/README_ko.md) | [Français](docs/README_fr.md) | [简体中文](docs/README_zh-CN.md)

## Intro
Mukai-Translator is an advanced Automatic Manga Translator with a modern, Cyberpunk-themed graphical user interface. Many Automatic Manga Translators exist, but very few properly support comics of other kinds in other languages with a premium, user-friendly experience. 
This project was created to utilize the ability of State of the Art (SOTA) Large Language Models (LLMs) like GPT to translate comics from all over the world, paired with a sleek, native Windows-style interface.

Currently, it supports translating comics from the following languages: English, Korean, Japanese, French, Simplified Chinese, Traditional Chinese, Russian, German, Dutch, Spanish and Italian. It can translate to the above mentioned and more. 

- [Features](#features)
- [Getting Started](#installation)
    - [Installation](#installation)
    - [Usage](#usage)
- [How it works](#how-it-works)
    - [Text Detection](#text-detection)
    - [OCR](#OCR)
    - [Inpainting](#inpainting)
    - [Translation](#translation)
    - [Text Rendering](#text-rendering)
- [Acknowledgements](#acknowledgements)

## Features
Mukai-Translator goes beyond simple translations by offering a premium user experience:
- **Cyberpunk-Themed Dashboard:** A modern Home Dashboard with geometric hero graphics, hierarchical typography, and modular info cards.
- **Steam-Style Frameless Splash Screen:** Custom startup sequence with specific branding colors and a progress bar.
- **Global Navigation Sidebar:** Seamlessly switch between the Translator, Settings, and Live Log.
- **Integrated Media Player:** Native Windows System Media Transport Controls (SMTC) support for an immersive experience.
- **State-of-the-Art Translation:** Leveraging GPT-4, Claude 3.5, and Gemini 1.5/2.0 for best-in-class machine translation.

## Installation
### Prerequisites
- Install [Python 3.12](https://www.python.org/downloads/). Tick "Add python.exe to PATH" during the setup.
- Install [Git](https://git-scm.com/)
- Install [uv](https://docs.astral.sh/uv/getting-started/installation/)

### From Source
In the command line:
```bash
git clone https://github.com/ChemixX1/Mukai-Translator.git
cd Mukai-Translator
uv init --python 3.12
```
Install the requirements:
```bash
uv add -r requirements.txt --compile-bytecode
```

To update, run this in the folder:
```bash
git pull
uv add -r requirements.txt --compile-bytecode
```

If you have an NVIDIA GPU, it is recommended to run:
```bash
uv pip install onnxruntime-gpu
```

## Usage
For local development on Windows, run the source-aware launcher from the project root:
```text
MukaiTranslator-Developer.exe
```
It uses the existing `.venv` and always opens the current source code, so normal code changes do not require reinstalling the application. Initial environment setup is handled by `tools\setup_development.ps1`.

Alternatively, from the command line:
```bash
uv run comic.py
```
This will launch the modern GUI.

For customer distribution and signed updates, see [docs/PRODUCCION.md](docs/PRODUCCION.md). Do not share the source folder with end users; share the versioned installer created under `releases\<version>`.

### Tips
* If you have a CBR file, you'll need to install Winrar or 7-Zip then add the folder it's installed to (e.g "C:\Program Files\WinRAR" for Windows) to Path.
* Make sure the selected Font supports characters of the target language.
* In Automatic Mode, once an Image has been processed, it is loaded in the Viewer or stored to be loaded on switch so you can keep reading in the app as the other Images are being translated.
* Ctrl + Mouse Wheel to Zoom otherwise Vertical Scrolling
* Right, Left Keys to Navigate Between Images

## How it works
### Speech Bubble Detection and Text Segmentation
RT-DETR-v2 model trained on 11k images of comics (Manga, Webtoons, Western). Algorithmic segmentation based on the boxes provided from the detection model.

### OCR
By Default:
* manga-ocr for Japanese
* Pororo for Korean 
* PPOCRv5 for Everything Else

Optional:
* Gemini 2.0 Flash
* Microsoft Azure Vision

### Inpainting
To remove the segmented text:
* A Manga/Anime finetuned lama checkpoint.
* AOT-GAN based model.

### Translation
Currently, this supports using GPT-4, Claude-3.5, and Gemini-2.5.
All LLMs are fed the entire page text to aid translations. There is also the Option to provide the Image itself for further context. 

### Text Rendering
Wrapped text in bounding boxes obtained from bubbles and text.

## Acknowledgements
* Built upon the original `comic-translate` by ogkalu2
* lama-cleaner
* AnimeMangaInpainting
* korean_ocr_using_pororo
* manga-ocr
* EasyOCR
* PaddleOCR
* RapidOCR
* dayu_widgets
* ComfyUI_LayerStyle (MIT; adapted mask-based layer effects, without the ComfyUI/Torch runtime)

## License and attribution

Mukai Translator is distributed under the [Apache License 2.0](LICENSE).
Redistributions and derivative works that use the Mukai Translator
modifications must retain the project [NOTICE](NOTICE) and its attribution to
ChemixX1, together with all applicable third-party notices.
