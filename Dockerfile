FROM python:3.12

WORKDIR /usr/local/website-builder
COPY . .

RUN pip install -U pip setuptools
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /website
ENTRYPOINT ["python", "/usr/local/website-builder/builder.py"]
