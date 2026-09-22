FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Etc/UTC

# Install the system timezone database explicitly; do not rely on slim contents.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Fail the build if libc/Python cannot resolve the QNAP example's timezone.
# 15:00 UTC must be midnight on the following calendar date in Tokyo.
RUN TZ=Asia/Tokyo python -c "from datetime import datetime, timezone; stamp = datetime(2024, 1, 1, 15, tzinfo=timezone.utc).timestamp(); assert datetime.fromtimestamp(stamp) == datetime(2024, 1, 2)"

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir \
    -r /app/requirements.txt \
    && pip check

COPY app /app/app

# Sole owner of the persistent loop. Compose should not override this command.
CMD ["python", "-m", "app.service"]
