FROM python:3.11-slim-bookworm
RUN apt update \
    && apt upgrade -y \
    && apt install -y --no-install-recommends \
    gettext \
    libmpv2 \
    p7zip \
    pulseaudio \
    && apt autoclean \
    && apt clean \
    && rm -rf /var/lib/apt/list
# Install the standalone yt-dlp binary so it can be updated independently of the
# bot; the yt service invokes it by the "yt-dlp" name on PATH by default.
ADD https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp /usr/local/bin/yt-dlp
RUN chmod a+rx /usr/local/bin/yt-dlp
RUN useradd -ms /bin/bash ttbot
USER ttbot
WORKDIR /home/ttbot
COPY --chown=ttbot requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=ttbot . .
RUN python tools/ttsdk_downloader.py && python tools/compile_locales.py
CMD pulseaudio --start && ./Cider.sh -c data/config.json --cache data/CiderCache.dat --log data/Cider.log
