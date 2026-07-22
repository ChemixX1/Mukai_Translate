# Third-party notices

## PyWinRT

Mukai Translator uses PyWinRT's Windows Runtime projections to read the active
Windows media session (including Spotify title, artist, playback state, and
timeline) without storing Spotify credentials.

- Project: `pywinrt/pywinrt`
- Source: https://github.com/pywinrt/pywinrt
- Components: `winrt-runtime`, `Windows.Foundation`,
  `Windows.Foundation.Collections`, and `Windows.Media.Control`
- License: MIT

MIT License

Copyright (c) Microsoft Corporation. All rights reserved.
Copyright (c) 2021-2025 David Lechner <david@pybricks.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## OpenCV / opencv-python-headless

Mukai Translator uses OpenCV's geometric image remapping only to produce a
high-quality editable-text deformation preview and final render.

- Projects: `opencv/opencv` and `opencv/opencv-python`
- Sources: https://github.com/opencv/opencv and https://github.com/opencv/opencv-python
- Licenses: Apache License 2.0 (OpenCV) and MIT (Python packaging scripts)
- Full bundled dependency notices: `cv2/LICENSE-3RD-PARTY.txt`

The headless wheel is used because Mukai Translator already provides its GUI
with PySide6 and does not call OpenCV's window or video APIs.

## ComfyUI LayerStyle

Mukai Translator's editable-text layer effects use a small, adapted implementation of the mask expansion, erosion, blur, and layer-compositing approach from:

- Project: `chflame163/ComfyUI_LayerStyle`
- Source: https://github.com/chflame163/ComfyUI_LayerStyle
- Copyright: Copyright (c) 2024 chflame163
- License: MIT

Only the layer-effect algorithm has been adapted. Mukai Translator does not bundle or install ComfyUI, Torch, its model files, or its node runtime.

MIT License

Copyright (c) 2024 chflame163

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Real-CUGAN NCNN Vulkan (optional export component)

Mukai Translator can download the official portable Real-CUGAN NCNN Vulkan
release on first use of an AI manga export profile. The archive URL and SHA-256
are pinned in the application, and the executable runs out of process only
during export.

- Projects: `bilibili/ailab` Real-CUGAN and
  `nihui/realcugan-ncnn-vulkan`
- Sources: https://github.com/bilibili/ailab/tree/main/Real-CUGAN and
  https://github.com/nihui/realcugan-ncnn-vulkan
- License: MIT
- The official Real-CUGAN package retains its upstream `LICENSE` file.

MIT License

Copyright (c) 2022 bilibili

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The Real-CUGAN NCNN Vulkan runtime is MIT licensed:

Copyright (c) 2019 nihui

The MIT permission notice and warranty disclaimer reproduced immediately above
also apply to this runtime copyright notice.

## Real-ESRGAN NCNN Vulkan (optional export component)

Mukai Translator can download the official portable Real-ESRGAN NCNN Vulkan
release on first use of a Real-ESRGAN export profile. The archive URL and
SHA-256 are pinned in the application, and the executable runs out of process
only during export.

- Projects: `xinntao/Real-ESRGAN` and
  `xinntao/Real-ESRGAN-ncnn-vulkan`
- Sources: https://github.com/xinntao/Real-ESRGAN and
  https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan
- Licenses: BSD 3-Clause (Real-ESRGAN/model) and MIT (NCNN runtime)

BSD 3-Clause License

Copyright (c) 2021, Xintao Wang

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

The Real-ESRGAN NCNN Vulkan runtime is MIT licensed:

Copyright (c) 2021 Xintao Wang

The MIT permission notice and warranty disclaimer in the Real-CUGAN section
also apply to this runtime copyright notice.

MangaJaNai models are not bundled or downloaded because their CC BY-NC 4.0
terms are not suitable for Mukai Translator's commercial distribution without
separate permission from the model author.
