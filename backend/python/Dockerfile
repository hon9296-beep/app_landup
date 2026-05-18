FROM python:3.12-slim

WORKDIR /app

COPY ODAFileConverter_QT6_lnxX64_8.3dll_27.1.deb /tmp/odafc.deb
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1 \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libdbus-1-3 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    libfreetype6 \
    libxcb1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-xkb1 \
    xvfb \
    && dpkg -i /tmp/odafc.deb || apt-get install -f -y \
    && rm /tmp/odafc.deb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]
