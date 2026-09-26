# The data analyst: HolmesGPT in its own image. It can't share the app's environment (0.42.0
# needs openai<3 and fastapi<0.137; Pydantic AI 2.x needs openai 3), so it runs on the shop's
# Docker network and the data_analyst node calls it. curl, psql and python3 are what the custom
# toolsets in toolsets.yaml run.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir holmesgpt==0.42.0
COPY condense_traces.py /tools/condense_traces.py
COPY toolsets.yaml /etc/holmes/toolsets.yaml
