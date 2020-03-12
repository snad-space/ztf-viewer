FROM python:3.8-buster

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN pip install gunicorn

COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

WORKDIR /app
EXPOSE 80

ENV PYTHONUNBUFFERED TRUE

COPY ./assets/* /app/assets/
COPY ./static/js/* /app/static/js/
COPY *.py /app/

ENTRYPOINT ["gunicorn", "-w4", "-b0.0.0.0:80", "main:server()"]
