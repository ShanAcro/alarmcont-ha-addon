ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY ids_x64_mqtt.py .
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
