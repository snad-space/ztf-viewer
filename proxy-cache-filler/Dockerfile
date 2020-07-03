FROM python:3.8-buster

COPY requirements.txt /requirements.txt
RUN pip install -r requirements.txt

COPY proxy_cache_filler.py /proxy_cache_filler.py

CMD ["python", "/proxy_cache_filler.py"]
