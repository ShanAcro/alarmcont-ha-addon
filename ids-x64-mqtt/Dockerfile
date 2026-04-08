ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ids_x64_mqtt.py .
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
