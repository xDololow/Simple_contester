FROM python:3.12-slim

WORKDIR /judger

# C# submissions use Mono (mcs + mono) instead of the full .NET SDK to keep the image practical.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-jdk \
        fp-compiler \
        g++ \
        gcc \
        gfortran \
        golang-go \
        lua5.4 \
        mono-devel \
        nodejs \
        npm \
    && npm install -g typescript \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py runners.py .
RUN useradd --create-home --shell /usr/sbin/nologin judge \
    && chown -R judge:judge /judger

USER judge

CMD ["python", "worker.py"]
