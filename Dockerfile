# The platform, as one image.
#
# Built on Playwright's own base rather than a plain Python image. The bot
# drives a real Chromium, and getting its system libraries right by hand is
# an afternoon nobody needs to spend: this image already has them and the
# browser, pinned to a matching Playwright version.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Graphviz is a system binary, not a Python package. Without it the flow
# picture fails while every other page works, which is a confusing way to
# discover it is missing.
RUN apt-get update \
 && apt-get install -y --no-install-recommends graphviz \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so editing the code does not rebuild the whole image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Mounted from the host at run time; created here in case the volume is
# empty on the first start.
RUN mkdir -p out data/inputs/qre_interpretation

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

CMD ["streamlit", "run", "src/dashboard/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.maxUploadSize=50"]
